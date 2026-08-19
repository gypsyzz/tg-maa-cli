from __future__ import annotations

import asyncio
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from telegram.ext import Application

from i18n import text_for
from maa_config import (
    AUTHORIZED_BY_NAME,
    service_unit_for,
)
from profile_store import (
    get_profile,
)
from systemd_utils import (
    systemctl_value,
)
from telegram_ui import (
    send_profile_preformatted,
)


# ---------------------------------------------------------------------------
# MaaCore log parsing
# ---------------------------------------------------------------------------

ANSI_RE = re.compile(
    r"\x1b\[[0-?]*[ -/]*[@-~]"
)

PID_RE = re.compile(
    r"\[Px(?P<pid>\d+)\]"
)

TASKCHAIN_CALLBACK_RE = re.compile(
    r"Assistant::append_callback \| "
    r"(?P<event>"
    r"TaskChainStart|"
    r"TaskChainCompleted|"
    r"TaskChainError|"
    r"TaskChainStopped"
    r") "
    r"(?P<payload>\{.*\})\s*$"
)

TERMINAL_EVENTS = {
    "TaskChainCompleted",
    "TaskChainError",
    "TaskChainStopped",
}

EVENT_STATUS = {
    "TaskChainCompleted": "Completed",
    "TaskChainError": "Error",
    "TaskChainStopped": "Stopped",
}


# ---------------------------------------------------------------------------
# Runtime state
# ---------------------------------------------------------------------------

@dataclass
class LogCursor:
    inode: int | None = None
    offset: int = 0
    partial: bytes = b""


@dataclass
class ActiveTask:
    taskchain: str
    taskid: int

    lines: list[str] = field(
        default_factory=list
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def strip_ansi(
    text: str,
) -> str:
    return ANSI_RE.sub(
        "",
        text,
    )


def normalize_log_mode(
    value,
) -> str:
    # YAML 1.1 may interpret ON/OFF as bool.
    if value is True:
        return "ON"

    if value is False:
        return "OFF"

    mode = str(
        value
    ).strip().upper()

    if mode not in {
        "OFF",
        "ON",
        "FULL",
    }:
        return "OFF"

    return mode


async def resolve_asst_log_path() -> Path:
    """
    Resolve:

        $(maa dir log)/asst.log

    Example:

        ~/.local/state/maa/debug/asst.log
    """

    maa_bin = shutil.which(
        "maa"
    )

    if not maa_bin:
        candidate = (
            Path.home()
            / ".local"
            / "bin"
            / "maa"
        )

        if candidate.is_file():
            maa_bin = str(
                candidate
            )

    if maa_bin:
        try:
            proc = await asyncio.create_subprocess_exec(
                maa_bin,
                "dir",
                "log",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )

            stdout, _ = (
                await proc.communicate()
            )

            if (
                proc.returncode == 0
                and stdout
            ):
                directory = Path(
                    stdout.decode(
                        "utf-8",
                        errors="replace",
                    ).strip()
                )

                return (
                    directory
                    / "asst.log"
                )

        except Exception:
            pass

    return (
        Path.home()
        / ".local"
        / "state"
        / "maa"
        / "debug"
        / "asst.log"
    )


def initial_cursor(
    path: Path,
) -> LogCursor:
    """
    Start at EOF.

    This prevents restarting the Telegram bot
    from replaying old MaaCore events.
    """

    try:
        stat = path.stat()
    except OSError:
        return LogCursor()

    return LogCursor(
        inode=stat.st_ino,
        offset=stat.st_size,
    )


def read_new_log_lines(
    path: Path,
    cursor: LogCursor,
) -> list[str]:
    """
    Incrementally read only newly appended
    lines from asst.log.
    """

    try:
        stat = path.stat()
    except OSError:
        return []

    # File replaced/rotated/truncated.
    if (
        cursor.inode != stat.st_ino
        or stat.st_size < cursor.offset
    ):
        cursor.inode = stat.st_ino
        cursor.offset = 0
        cursor.partial = b""

    try:
        with path.open(
            "rb"
        ) as f:
            f.seek(
                cursor.offset
            )

            data = f.read()

            cursor.offset = (
                f.tell()
            )

    except OSError:
        return []

    if not data:
        return []

    data = (
        cursor.partial
        + data
    )

    parts = data.split(
        b"\n"
    )

    # Last element may not yet be a complete
    # line.
    cursor.partial = (
        parts.pop()
    )

    return [
        part.decode(
            "utf-8",
            errors="replace",
        )
        for part in parts
    ]


def parse_pid(
    line: str,
) -> int | None:
    """
    Parse:

        [Px2888354]

    from MaaCore log.
    """

    match = PID_RE.search(
        line
    )

    if not match:
        return None

    return int(
        match.group(
            "pid"
        )
    )


def parse_taskchain_callback(
    line: str,
) -> tuple[
    str,
    str,
    int,
] | None:
    """
    Parse top-level MaaCore callbacks such as:

        TaskChainStart
        TaskChainCompleted
        TaskChainError
        TaskChainStopped
    """

    match = (
        TASKCHAIN_CALLBACK_RE.search(
            line
        )
    )

    if not match:
        return None

    try:
        payload = json.loads(
            match.group(
                "payload"
            )
        )
    except (
        json.JSONDecodeError,
        TypeError,
    ):
        return None

    taskchain = str(
        payload.get(
            "taskchain",
            "",
        )
    ).strip()

    try:
        taskid = int(
            payload.get(
                "taskid"
            )
        )
    except (
        TypeError,
        ValueError,
    ):
        return None

    if not taskchain:
        return None

    return (
        match.group(
            "event"
        ),
        taskchain,
        taskid,
    )


def task_result_text(
    task: ActiveTask,
    event: str,
) -> str:
    status = EVENT_STATUS.get(
        event,
        event,
    )

    return (
        f"[{task.taskid}] "
        f"{task.taskchain} "
        f"{status}"
    )


# ---------------------------------------------------------------------------
# Telegram reporting
# ---------------------------------------------------------------------------

async def report_finished_task(
    application: Application,
    name: str,
    task: ActiveTask,
    event: str,
) -> None:
    """
    Called IMMEDIATELY when a top-level
    TaskChain terminal event appears.
    """

    profile = get_profile(
        name
    )

    mode = normalize_log_mode(
        profile.log
    )

    lang = profile.lang

    # -------------------------------------------------------
    # OFF
    # -------------------------------------------------------

    if mode == "OFF":
        return

    # -------------------------------------------------------
    # ON
    #
    # Completed -> nothing
    # Stopped   -> nothing
    # Error     -> report immediately
    # -------------------------------------------------------

    if mode == "ON":
        if event != "TaskChainError":
            return

        await send_profile_preformatted(
            application,
            name=name,
            title=text_for(
                lang,
                "incomplete_log_title",
                name=name,
            ),
            text=task_result_text(
                task,
                event,
            ),
        )

        return

    # -------------------------------------------------------
    # FULL
    #
    # Report every top-level task immediately when it ends.
    # -------------------------------------------------------

    if mode == "FULL":
        result = task_result_text(
            task,
            event,
        )

        log_text = "\n".join(
            task.lines
        )

        if log_text:
            text = (
                f"{result}\n\n"
                f"{log_text}"
            )
        else:
            text = result

        await send_profile_preformatted(
            application,
            name=name,
            title=text_for(
                lang,
                "full_log_title",
                name=name,
            ),
            text=text,
        )


# ---------------------------------------------------------------------------
# MaaCore log processing
# ---------------------------------------------------------------------------

async def process_log_line(
    application: Application,
    line: str,
    pid_to_profile: dict[
        int,
        str,
    ],
    active_tasks: dict[
        int,
        ActiveTask,
    ],
) -> None:
    line = strip_ansi(
        line
    )

    pid = parse_pid(
        line
    )

    if pid is None:
        return

    name = pid_to_profile.get(
        pid
    )

    # Ignore MaaCore processes that do not
    # belong to a managed systemd profile.
    #
    # For example:
    #
    #     maa run failtest -p yan
    #
    # started manually from a terminal will
    # not generate Telegram notifications.
    if name is None:
        return

    current = active_tasks.get(
        pid
    )

    # Once TaskChainStart has been observed,
    # accumulate this process's log lines
    # until the corresponding terminal event.
    if current is not None:
        current.lines.append(
            line
        )

    callback = (
        parse_taskchain_callback(
            line
        )
    )

    if callback is None:
        return

    (
        event,
        taskchain,
        taskid,
    ) = callback

    # -------------------------------------------------------
    # Top-level task started
    # -------------------------------------------------------

    if event == "TaskChainStart":
        active_tasks[
            pid
        ] = ActiveTask(
            taskchain=taskchain,
            taskid=taskid,
            lines=[
                line
            ],
        )

        return

    # -------------------------------------------------------
    # Ignore anything except terminal TaskChain events
    # -------------------------------------------------------

    if event not in TERMINAL_EVENTS:
        return

    task = active_tasks.get(
        pid
    )

    # Bot may have restarted after TaskChainStart,
    # in which case we can still report the
    # terminal state.
    if (
        task is None
        or task.taskid != taskid
    ):
        task = ActiveTask(
            taskchain=taskchain,
            taskid=taskid,
            lines=[
                line
            ],
        )

    try:
        await report_finished_task(
            application,
            name,
            task,
            event,
        )

    finally:
        active_tasks.pop(
            pid,
            None,
        )


# ---------------------------------------------------------------------------
# systemd PID mapping
# ---------------------------------------------------------------------------

async def refresh_profile_pids(
    pid_to_profile: dict[
        int,
        str,
    ],
) -> None:
    """
    Map:

        MaaCore Px PID -> Telegram profile

    using each managed systemd worker's MainPID.
    """

    for name in AUTHORIZED_BY_NAME:
        unit = service_unit_for(
            name
        )

        try:
            value = await systemctl_value(
                unit,
                "MainPID",
            )

            pid = int(
                value or 0
            )

        except (
            Exception,
            TypeError,
            ValueError,
        ):
            continue

        if pid <= 0:
            continue

        pid_to_profile[
            pid
        ] = name


# ---------------------------------------------------------------------------
# Monitor
# ---------------------------------------------------------------------------

async def log_monitor_loop(
    application: Application,
) -> None:
    log_path = (
        await resolve_asst_log_path()
    )

    cursor = initial_cursor(
        log_path
    )

    # Maa process PID -> profile name
    pid_to_profile: dict[
        int,
        str,
    ] = {}

    # Maa process PID -> current top-level task
    active_tasks: dict[
        int,
        ActiveTask,
    ] = {}

    try:
        while True:
            # First associate running systemd
            # workers with their MaaCore PID.
            await refresh_profile_pids(
                pid_to_profile
            )

            # Then consume only newly written
            # MaaCore log lines.
            lines = await asyncio.to_thread(
                read_new_log_lines,
                log_path,
                cursor,
            )

            for line in lines:
                try:
                    await process_log_line(
                        application,
                        line,
                        pid_to_profile,
                        active_tasks,
                    )

                except Exception:
                    # A malformed MaaCore log line
                    # must not terminate the entire
                    # Telegram monitor.
                    continue

            await asyncio.sleep(
                0.5
            )

    except asyncio.CancelledError:
        return