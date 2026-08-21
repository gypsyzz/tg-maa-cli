from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable
from zoneinfo import ZoneInfo

from maa_config import PERSISTENT, SYSTEMD_USER_DIR, TIMEZONE, service_unit_for, timer_file_for, timer_unit_for
from profile_store import ScheduleState, get_profile

SYSTEMD_TIMESTAMP_RE = re.compile(
    r"(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})(?:\s+(?P<zone>[+-]\d{2}(?::?\d{2})?|UTC))?"
)


@dataclass
class CmdResult:
    returncode: int
    stdout: str
    stderr: str


@dataclass(frozen=True)
class ServiceAction:
    key: str
    timestamp: datetime


async def run_cmd(*args: str, timeout: float = 20, ) -> CmdResult:
    try:
        proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.PIPE, )

        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout, )

    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()

        return CmdResult(124, "", f"Timed out: {' '.join(args)}", )

    except FileNotFoundError as exc:
        return CmdResult(127, "", str(exc), )

    return CmdResult(proc.returncode, stdout_b.decode(errors="replace").strip(),
                     stderr_b.decode(errors="replace").strip(), )


async def systemctl_value(unit: str, prop: str, ) -> str:
    result = await run_cmd("systemctl", "--user", "show", unit, f"--property={prop}", "--value", )

    if result.returncode != 0:
        return ""

    return result.stdout.strip()


async def unit_is_active(unit: str, ) -> bool:
    result = await run_cmd("systemctl", "--user", "is-active", "--quiet", unit, )

    return result.returncode == 0


async def service_result(name: str, ) -> str:
    return (await systemctl_value(service_unit_for(name), "Result", ) or "n/a")


def parse_systemd_timestamp(value: str, ) -> datetime | None:
    match = SYSTEMD_TIMESTAMP_RE.search(value)

    if match is None:
        return None

    try:
        timestamp = datetime.strptime(match.group("timestamp"), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None

    raw_zone = match.group("zone")

    if raw_zone == "UTC":
        source_zone = timezone.utc
    elif raw_zone:
        sign = (1 if raw_zone[0] == "+" else -1)
        digits = raw_zone[1:].replace(":", "")
        hours = int(digits[:2])
        minutes = (int(digits[2:]) if len(digits) > 2 else 0)
        source_zone = timezone(sign * timedelta(hours=hours, minutes=minutes))
    else:
        source_zone = ZoneInfo(TIMEZONE)

    return timestamp.replace(tzinfo=source_zone).astimezone(timezone.utc)


async def service_last_action(name: str, ) -> ServiceAction | None:
    value = await systemctl_value(service_unit_for(name), "ExecMainExitTimestamp", )
    timestamp = parse_systemd_timestamp(value)

    if timestamp is None:
        return None

    return ServiceAction(key=timestamp.isoformat(), timestamp=timestamp, )


async def next_run(name: str, schedule: ScheduleState | None = None, ) -> str:
    schedule = (schedule or get_profile(name).schedule)

    if not schedule.times:
        return "none"

    if not schedule.enabled:
        return "off"

    value = await systemctl_value(timer_unit_for(name), "NextElapseUSecRealtime", )

    if not value or value in {"0", "n/a"}:
        return "n/a"

    return value


def render_timer(name: str, times: Iterable[str], ) -> str:
    lines = ["[Unit]", f"Description=MAA {name} Schedule", "", "[Timer]", ]

    for value in times:
        lines.append(f"OnCalendar=*-*-* {value}:00 {TIMEZONE}")

    lines += [f"Persistent={'true' if PERSISTENT else 'false'}", "AccuracySec=1s", f"Unit={service_unit_for(name)}", "",
              "[Install]", "WantedBy=timers.target", "", ]

    return "\n".join(lines)


async def daemon_reload() -> None:
    result = await run_cmd("systemctl", "--user", "daemon-reload", )

    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout or "systemctl daemon-reload failed")


async def disable_timer(name: str, ) -> None:
    timer_unit = timer_unit_for(name)
    timer_file = timer_file_for(name)

    await run_cmd("systemctl", "--user", "disable", "--now", timer_unit, )

    if timer_file.exists():
        timer_file.unlink()

    await daemon_reload()


async def sync_timer(name: str, schedule: ScheduleState, ) -> None:
    SYSTEMD_USER_DIR.mkdir(parents=True, exist_ok=True, )

    if not schedule.times or not schedule.enabled:
        await disable_timer(name)
        return

    timer_file = timer_file_for(name)
    tmp = timer_file.with_suffix(timer_file.suffix + ".tmp")

    tmp.write_text(render_timer(name, schedule.times, ), encoding="utf-8", )

    tmp.replace(timer_file)

    await daemon_reload()

    result = await run_cmd("systemctl", "--user", "enable", "--now", timer_unit_for(name), )

    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout or f"Failed enabling {timer_unit_for(name)}")

    result = await run_cmd("systemctl", "--user", "restart", timer_unit_for(name), )

    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout or f"Failed restarting {timer_unit_for(name)}")


async def invocation_log(invocation_id: str, ) -> str:
    result = await run_cmd("journalctl", "--user", f"_SYSTEMD_INVOCATION_ID={invocation_id}", "--no-pager", "-o", "cat",
                           timeout=30, )

    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout or "Failed to read MAA invocation log.")

    return result.stdout or "(no output)"
