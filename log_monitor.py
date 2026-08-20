from __future__ import annotations

import asyncio
import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from telegram.ext import Application

from i18n import text_for
from maa_config import AUTHORIZED_BY_NAME, service_unit_for
from profile_store import get_profile
from systemd_utils import systemctl_value
from telegram_ui import send_profile_preformatted

# ---------------------------------------------------------------------------
# MaaCore log parsing
# ---------------------------------------------------------------------------

ANSI_RE = re.compile(
    r"\x1b\[[0-?]*[ -/]*[@-~]"
)

PID_RE = re.compile(r"\[Px(?P<pid>\d+)\]")

TASKCHAIN_CALLBACK_RE = re.compile(r"Assistant::append_callback \| " r"(?P<event>" r"TaskChainStart|" r"TaskChainCompleted|" r"TaskChainError|" r"TaskChainStopped" r") " r"(?P<payload>\{.*\})\s*$")

TERMINAL_EVENTS = {"TaskChainCompleted", "TaskChainError", "TaskChainStopped", }

EVENT_STATUS = {"TaskChainCompleted": "Completed", "TaskChainError": "Error", "TaskChainStopped": "Stopped", }

# Lines worth retaining when diagnosing a failed task.
#
# Important:
# SubTaskError alone does NOT mean the whole task failed.
# These lines are collected, but they are only sent if the
# top-level task eventually emits TaskChainError.
FAILURE_LINE_RE = re.compile(
    r"(?:"
    r"Assistant::append_callback \| "
    r"(?:SubTaskError|TaskChainError)\b"
    r"|"
    r"\[(?:ERR|ERROR)\]"
    r"|"
    r"\b(?:error|failed|failure|fatal|exception)\b"
    r")",
    re.IGNORECASE,
)

# Remove the verbose MaaCore prefix:
#
# [2026-08-19 00:22:11.088][INF][Px2921942][Tx50880]
#
LOG_PREFIX_RE = re.compile(
    r"^"
    r"\[[^\]]+\]"
    r"\[[^\]]+\]"
    r"\[Px\d+\]"
    r"\[Tx\d+\]"
    r"\s*"
)


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

    # Only explicit error/failure-related lines
    # are kept. Normal OCR/ADB/TRC lines are not.
    failure_lines: list[str] = field(
        default_factory=list
    )


# ---------------------------------------------------------------------------
# General helpers
# ---------------------------------------------------------------------------

def strip_ansi(
        text: str,
) -> str:
    return ANSI_RE.sub("", text, )


def normalize_log_mode(value, ) -> str:
    # YAML may interpret unquoted ON/OFF
    # as bool values.
    if value is True:
        return "ON"

    if value is False:
        return "OFF"

    mode = str(value).strip().upper()

    if mode not in {"OFF", "ON", "FULL", }:
        return "OFF"

    return mode


# ---------------------------------------------------------------------------
# asst.log handling
# ---------------------------------------------------------------------------

async def resolve_asst_log_path() -> Path:
    """
    Resolve:

        $(maa dir log)/asst.log

    Typical Linux result:

        ~/.local/state/maa/debug/asst.log
    """

    maa_bin = shutil.which("maa")

    if not maa_bin:
        candidate = (Path.home() / ".local" / "bin" / "maa")

        if candidate.is_file():
            maa_bin = str(candidate)

    if maa_bin:
        try:
            process = await asyncio.create_subprocess_exec(maa_bin, "dir", "log",
                                                           stdout=asyncio.subprocess.PIPE,
                                                           stderr=asyncio.subprocess.DEVNULL, )

            stdout, _ = (await process.communicate())

            if (process.returncode == 0 and stdout):
                log_dir = Path(stdout.decode("utf-8", errors="replace", ).strip())

                return (log_dir / "asst.log")

        except Exception:
            pass

    # Normal maa-cli Linux fallback.
    return (
            Path.home()
            / ".local"
            / "state"
            / "maa"
            / "debug"
            / "asst.log"
    )


def initial_cursor(path: Path, ) -> LogCursor:
    """
    Begin at EOF so restarting the Telegram bot
    does not replay old MaaCore tasks.
    """

    try:
        stat = path.stat()
    except OSError:
        return LogCursor()

    return LogCursor(inode=stat.st_ino, offset=stat.st_size, )


def read_new_log_lines(path: Path, cursor: LogCursor, ) -> list[str]:
    """
    Incrementally read newly appended data from
    MaaCore's asst.log.
    """

    try:
        stat = path.stat()
    except OSError:
        return []

    # Log file was replaced, rotated, or truncated.
    if (
            cursor.inode != stat.st_ino
            or stat.st_size < cursor.offset
    ):
        cursor.inode = stat.st_ino
        cursor.offset = 0
        cursor.partial = b""

    try:
        with path.open("rb") as file:
            file.seek(cursor.offset)

            data = file.read()

            cursor.offset = (file.tell())

    except OSError:
        return []

    if not data:
        return []

    data = (cursor.partial + data)

    parts = data.split(b"\n")

    # The final piece may still be an
    # incomplete line.
    cursor.partial = (
        parts.pop()
    )

    return [part.decode("utf-8", errors="replace", ) for part in parts]


# ---------------------------------------------------------------------------
# MaaCore parsing
# ---------------------------------------------------------------------------

def parse_pid(
        line: str,
) -> int | None:
    """
    Extract:

        [Px3308182]

    -> 3308182
    """

    match = PID_RE.search(line)

    if not match:
        return None

    return int(match.group("pid"))


def parse_taskchain_callback(line: str, ) -> tuple[str, str, int,] | None:
    """
    Parse top-level MaaCore task callbacks:

        TaskChainStart
        TaskChainCompleted
        TaskChainError
        TaskChainStopped

    Internal SubTask callbacks are deliberately
    not considered task completion events.
    """

    match = (TASKCHAIN_CALLBACK_RE.search(line))

    if not match:
        return None

    try:
        payload = json.loads(match.group("payload"))
    except (json.JSONDecodeError, TypeError,):
        return None

    taskchain = str(payload.get("taskchain", "", )).strip()

    try:
        taskid = int(payload.get("taskid"))
    except (TypeError, ValueError,):
        return None

    if not taskchain:
        return None

    return (match.group("event"), taskchain, taskid,)


# ---------------------------------------------------------------------------
# Failure extraction
# ---------------------------------------------------------------------------

def extract_failure_line(
        line: str,
) -> str | None:
    """
    Return a compact failure-related line.

    Normal MaaCore debug lines return None.
    """

    line = strip_ansi(line).strip()

    if not FAILURE_LINE_RE.search(line):
        return None

    # Remove timestamp / level / PID / thread prefix.
    line = LOG_PREFIX_RE.sub(
        "",
        line,
    )

    # For MaaCore callbacks, remove another
    # unnecessary prefix:
    #
    # Assistant::append_callback | SubTaskError ...
    #
    marker = (
        "Assistant::append_callback | "
    )

    if marker in line:
        line = line.split(marker, 1, )[1]

    return line.strip()


def failure_details(task: ActiveTask, ) -> str:
    """
    Return only actual failure/error-related
    lines collected during this task.
    """

    if not task.failure_lines:
        return ""

    return "\n".join(task.failure_lines)


# ---------------------------------------------------------------------------
# Result formatting
# ---------------------------------------------------------------------------

def task_result_text(
        task: ActiveTask,
        event: str,
) -> str:
    status = EVENT_STATUS.get(event, event, )

    return (f"[{task.taskid}] " f"{task.taskchain} " f"{status}")


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
    Called immediately when MaaCore emits a
    terminal TaskChain event.
    """

    profile = get_profile(name)

    mode = normalize_log_mode(profile.log)

    lang = profile.lang

    # -------------------------------------------------------
    # OFF
    #
    # Never send automatic task results.
    # -------------------------------------------------------

    if mode == "OFF":
        return

    result = task_result_text(task, event, )

    # -------------------------------------------------------
    # ON
    #
    # Completed -> nothing
    # Stopped   -> nothing
    # Error     -> send immediately with failure details
    # -------------------------------------------------------

    if mode == "ON":
        if event != "TaskChainError":
            return

        details = failure_details(task)

        text = result

        if details:
            text += ("\n\n" f"{details}")

        await send_profile_preformatted(application, name=name, title=text_for(lang, "incomplete_log_title", name=name, ), text=text, )

        return

    # -------------------------------------------------------
    # FULL
    #
    # Completed -> short result
    # Stopped   -> short result
    # Error     -> result + failure details
    #
    # FULL means every MAA subtask is reported.
    # It does NOT dump the full MaaCore debug log.
    # -------------------------------------------------------

    if mode == "FULL":
        text = result

        if event == "TaskChainError":
            details = failure_details(task)

            if details:
                text += ("\n\n" f"{details}")

        await send_profile_preformatted(application, name=name,
                                        title=text_for(lang, "full_log_title", name=name, ), text=text, )


# ---------------------------------------------------------------------------
# Process MaaCore log lines
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
    line = strip_ansi(line)

    pid = parse_pid(line)

    if pid is None:
        return

    name = pid_to_profile.get(pid)

    # Ignore MAA processes that are not one
    # of our managed systemd profile workers.
    #
    # Therefore something manually run like:
    #
    #     maa run failtest -p yan
    #
    # will not generate Telegram messages.
    if name is None:
        return

    # -------------------------------------------------------
    # Collect ONLY failure-related lines
    # -------------------------------------------------------

    current = active_tasks.get(
        pid
    )

    failure_line = extract_failure_line(line)

    if (current is not None and failure_line is not None):
        current.failure_lines.append(failure_line)

    # -------------------------------------------------------
    # Parse top-level TaskChain event
    # -------------------------------------------------------

    callback = (
        parse_taskchain_callback(
            line
        )
    )

    if callback is None:
        return

    (event, taskchain, taskid,) = callback

    # -------------------------------------------------------
    # Task started
    # -------------------------------------------------------

    if event == "TaskChainStart":
        active_tasks[pid] = ActiveTask(taskchain=taskchain, taskid=taskid, )

        return

    # -------------------------------------------------------
    # Only top-level terminal TaskChain events
    # mean the MAA task is finished.
    # -------------------------------------------------------

    if event not in TERMINAL_EVENTS:
        return

    task = active_tasks.get(pid)

    # Bot may have restarted while MAA was
    # already executing the task.
    if (
            task is None
            or task.taskid != taskid
            or task.taskchain != taskchain
    ):
        task = ActiveTask(taskchain=taskchain, taskid=taskid, )

        # If this terminal line itself is an
        # error line, preserve it.
        if failure_line is not None:
            task.failure_lines.append(failure_line)

    try:
        await report_finished_task(application, name, task, event, )

    finally:
        active_tasks.pop(pid, None, )


# ---------------------------------------------------------------------------
# systemd PID -> profile mapping
# ---------------------------------------------------------------------------

async def refresh_profile_pids(
        pid_to_profile: dict[
            int,
            str,
        ],
) -> set[int]:
    """
    Map each profile's systemd MainPID to its
    Telegram/MAA profile name.
    """

    active_pids: set[int] = set()

    for name in AUTHORIZED_BY_NAME:
        unit = service_unit_for(name)

        try:
            value = await systemctl_value(unit, "MainPID", )

            pid = int(value or 0)

        except (Exception, TypeError, ValueError,):
            continue

        if pid <= 0:
            continue

        pid_to_profile[pid] = name

        active_pids.add(pid)

    return active_pids


def prune_stale_pids(pid_to_profile: dict[int, str,], active_tasks: dict[int, ActiveTask,], active_pids: set[int], ) -> None:
    """
    Remove mappings for worker processes that
    are no longer running.

    This prevents PID reuse from associating a
    future unrelated process with an old profile.
    """

    for pid in list(pid_to_profile):
        if pid in active_pids:
            continue

        pid_to_profile.pop(pid, None, )

        active_tasks.pop(pid, None, )


# ---------------------------------------------------------------------------
# Main realtime monitor
# ---------------------------------------------------------------------------

async def log_monitor_loop(
        application: Application,
) -> None:
    log_path = (await resolve_asst_log_path())

    cursor = initial_cursor(log_path)

    # Maa process PID -> profile
    pid_to_profile: dict[int, str,] = {}

    # Maa process PID -> currently running
    # top-level TaskChain
    active_tasks: dict[int, ActiveTask,] = {}

    try:
        while True:
            # Refresh PID mapping first.
            #
            # Existing stale mappings are NOT
            # removed until after new log lines
            # have been processed. This is
            # important because MaaCore may emit
            # its final TaskChain callback just
            # before the systemd service exits.
            active_pids = (
                await refresh_profile_pids(
                    pid_to_profile
                )
            )

            # Read only newly appended MaaCore
            # log lines.
            lines = await asyncio.to_thread(read_new_log_lines, log_path, cursor, )

            for line in lines:
                try:
                    await process_log_line(application, line, pid_to_profile, active_tasks, )

                except Exception:
                    # One malformed log line must
                    # not kill the entire monitor.
                    continue

            # Now that newly written lines have
            # been processed, old PID mappings
            # can safely be discarded.
            prune_stale_pids(
                pid_to_profile,
                active_tasks,
                active_pids,
            )

            await asyncio.sleep(0.5)

    except asyncio.CancelledError:
        return
