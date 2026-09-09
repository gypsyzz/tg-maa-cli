#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import base64
import sys
from enum import Enum
from pathlib import Path

from telegram import Bot

from i18n import text_for
from maa_config import TOKEN
from profile_store import ProfileState, ScheduleCheckState, get_profile, resolve_profile_name
from systemd_utils import CmdResult, run_cmd


class CheckStatus(Enum):
    OK = "ok"
    DOWN = "down"
    ERROR = "error"


def _powershell_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _windows_process_expression(state: ScheduleCheckState) -> str:
    process = _powershell_literal(state.windows_process)
    expression = f"Get-Process -Name {process} -ErrorAction SilentlyContinue"

    if state.windows_executable:
        executable = _powershell_literal(state.windows_executable)
        expression += f" | Where-Object {{ $_.Path -ieq {executable} }}"

    return expression


async def run_windows_powershell(state: ScheduleCheckState, script: str, ) -> CmdResult:
    identity = str(Path(state.ssh_identity).expanduser())
    target = f"{state.windows_user}@{state.windows_host}"
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")

    return await run_cmd(
        "ssh",
        "-F",
        "/dev/null",
        "-o",
        "BatchMode=yes",
        "-o",
        "IdentitiesOnly=yes",
        "-o",
        "ConnectTimeout=5",
        "-i",
        identity,
        target,
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-EncodedCommand",
        encoded,
        timeout=15,
    )


async def check_windows_maa(state: ScheduleCheckState, ) -> CheckStatus:
    script = (
        f"$processes = @({_windows_process_expression(state)}); "
        "if ($processes.Count -gt 0) { exit 0 } else { exit 1 }"
    )
    result = await run_windows_powershell(state, script)

    if result.returncode == 0:
        return CheckStatus.OK

    if result.returncode == 1:
        return CheckStatus.DOWN

    _log_command_error("Windows MAA check", result)
    return CheckStatus.ERROR


async def check_container(state: ScheduleCheckState, ) -> CheckStatus:
    result = await run_cmd("docker", "inspect", "--format={{.State.Running}}", state.container_name, timeout=10, )

    if result.returncode != 0:
        _log_command_error("Container check", result)
        return CheckStatus.ERROR

    if result.stdout == "true":
        return CheckStatus.OK

    if result.stdout == "false":
        return CheckStatus.DOWN

    _log_command_error("Container check", result)
    return CheckStatus.ERROR


async def start_windows_maa(state: ScheduleCheckState, ) -> CmdResult:
    task = _powershell_literal(state.windows_start_task)
    script = (
        "try { "
        f"Start-ScheduledTask -TaskName {task} -ErrorAction Stop; "
        "exit 0 "
        "} catch { Write-Error $_.Exception.Message; exit 2 }"
    )
    return await run_windows_powershell(state, script)


async def stop_windows_maa(state: ScheduleCheckState, ) -> CmdResult:
    script = (
        "try { "
        f"$processes = @({_windows_process_expression(state)}); "
        "if ($processes.Count -gt 0) { $processes | Stop-Process -Force -ErrorAction Stop }; "
        "exit 0 "
        "} catch { Write-Error $_.Exception.Message; exit 2 }"
    )
    return await run_windows_powershell(state, script)


async def wait_for_windows_maa(
        state: ScheduleCheckState,
        expected: CheckStatus,
        *,
        attempts: int = 10,
        delay: float = 1,
) -> CheckStatus:
    status = CheckStatus.ERROR

    for attempt in range(attempts):
        status = await check_windows_maa(state)

        if status is expected:
            return status

        if attempt + 1 < attempts:
            await asyncio.sleep(delay)

    return status


def _log_command_error(label: str, result: CmdResult, ) -> None:
    detail = result.stderr or result.stdout or f"exit status {result.returncode}"
    print(f"{label} failed: {detail}", file=sys.stderr, )


def failure_message(
        name: str,
        profile: ProfileState,
        windows_status: CheckStatus,
        container_status: CheckStatus | None = None,
) -> str | None:
    failures = []

    if container_status is not None and container_status is not CheckStatus.OK:
        failures.append(
            text_for(
                profile.lang,
                "check_result_container",
                container_name=profile.schedule_check.container_name,
                container_state=text_for(profile.lang, f"check_result_container_{container_status.value}", ),
            )
        )

    if windows_status is not CheckStatus.OK:
        failures.append(
            text_for(
                profile.lang,
                "check_result_windows",
                maa_state=text_for(profile.lang, f"check_result_maa_{windows_status.value}", ),
            )
        )

    if not failures:
        return None

    return text_for(
        profile.lang,
        "check_result_failed",
        result="; ".join(failures),
    )


async def collect_failure_message(name: str, profile: ProfileState, ) -> str | None:
    state = profile.schedule_check

    if state.container_name:
        container_status, windows_status = await asyncio.gather(check_container(state), check_windows_maa(state))
    else:
        container_status = None
        windows_status = await check_windows_maa(state)

    return failure_message(name, profile, windows_status, container_status)


async def check_and_notify(bot: Bot, name: str, profile: ProfileState, ) -> bool:
    message = await collect_failure_message(name, profile)

    if message is None:
        return False

    await bot.send_message(chat_id=profile.chat_id, text=message, )
    return True


async def run(profile_name: str, *, notify: bool, ) -> int:
    name = resolve_profile_name(profile_name)
    profile = get_profile(name)

    if not profile.schedule.check_enabled:
        print(f"Schedule check is disabled for {name}.")
        return 0

    if notify:
        async with Bot(TOKEN) as bot:
            sent = await check_and_notify(bot, name, profile)

        print(f"Schedule check for {name}: {'alert sent' if sent else 'healthy'}.")
        return 0

    message = await collect_failure_message(name, profile)

    if message is None:
        print(f"Schedule check for {name}: healthy.")
        return 0

    print(message)
    return 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Check a scheduled MAA profile's container and Windows GUI.")
    parser.add_argument("--profile", required=True, help="Telegram/MAA profile name.")
    parser.add_argument("--no-notify", action="store_true", help="Print the result without sending Telegram messages.")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(run(args.profile, notify=not args.no_notify, )))


if __name__ == "__main__":
    main()
