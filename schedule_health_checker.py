#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import base64
import json
import re
import sys
from dataclasses import replace
from enum import Enum
from pathlib import Path

from telegram import Bot

from alert_checker import load_alert_state, save_alert_state
from i18n import text_for
from maa_config import CONTAINER_HEALTH_STATE_PATH, TOKEN
from profile_store import CONTAINER_NAME_RE, ProfileState, ScheduleCheckState, get_profile, resolve_profile_name
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


async def run_windows_powershell(state: ScheduleCheckState, script: str) -> CmdResult:
    identity = str(Path(state.ssh_identity).expanduser())
    target = f"{state.windows_user}@{state.windows_host}"
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")

    return await run_cmd("ssh", "-F", "/dev/null", "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes", "-o", "ConnectTimeout=5", "-i", identity, target, "powershell.exe", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded, timeout=15)


async def check_windows_maa(state: ScheduleCheckState) -> CheckStatus:
    script = f"$processes = @({_windows_process_expression(state)}); if ($processes.Count -gt 0) {{ exit 0 }} else {{ exit 1 }}"
    result = await run_windows_powershell(state, script)

    if result.returncode == 0:
        return CheckStatus.OK

    if result.returncode == 1:
        return CheckStatus.DOWN

    _log_command_error("Windows MAA check", result)
    return CheckStatus.ERROR


async def check_container(state: ScheduleCheckState) -> CheckStatus:
    result = await check_container_health(state)

    if result.returncode == 0:
        return CheckStatus.OK

    _log_command_error("Container health check", result)

    if result.returncode == 1:
        return CheckStatus.DOWN

    return CheckStatus.ERROR


async def restart_container(state: ScheduleCheckState) -> CmdResult:
    result = await run_cmd("docker", "restart", "--timeout", "20", "--", state.container_name, timeout=45)

    if result.returncode != 0:
        return result

    deadline = asyncio.get_running_loop().time() + 120

    while asyncio.get_running_loop().time() < deadline:
        result = await run_cmd("docker", "exec", state.container_name, "getprop", "sys.boot_completed", timeout=10)

        if result.returncode != 0:
            return result

        if result.stdout == "1":
            return await run_cmd("docker", "exec", state.container_name, "cmd", "bluetooth_manager", "disable", timeout=15)

        await asyncio.sleep(2)

    return CmdResult(124, "", "Container restarted, but Android did not finish booting within 120 seconds.")


async def check_container_health(state: ScheduleCheckState) -> CmdResult:
    result = await run_cmd("docker", "inspect", '--format={"running":{{json .State.Running}},"ports":{{json (index .NetworkSettings.Ports "5555/tcp")}}}', state.container_name, timeout=10)

    if result.returncode != 0:
        return result

    try:
        info = json.loads(result.stdout)
        running = info["running"]
        ports = info["ports"] or []
    except (ValueError, KeyError, TypeError):
        return CmdResult(1, "", "Could not read the container's state and published ADB port.")

    if not running:
        return CmdResult(1, "", "Container is stopped.")

    result = await run_cmd("docker", "exec", state.container_name, "getprop", "sys.boot_completed", timeout=10)

    if result.returncode != 0:
        return result

    if result.stdout != "1":
        return CmdResult(1, "", "Container is running, but Android has not finished booting.")

    if not ports:
        return CmdResult(1, "", "Android has booted, but container port 5555/tcp is not published for ADB.")

    binding = next((port for port in ports if port["HostIp"] == "127.0.0.1"), ports[0])
    host = binding["HostIp"]
    host = {"": "127.0.0.1", "0.0.0.0": "127.0.0.1", "::": "::1"}.get(host, host)
    address = f"[{host}]:{binding['HostPort']}" if ":" in host else f"{host}:{binding['HostPort']}"
    result = await run_cmd("adb", "connect", address, timeout=10)

    if result.returncode != 0:
        return result

    result = await run_cmd("adb", "-s", address, "shell", "settings", "get", "secure", "android_id", timeout=10)

    if result.returncode != 0:
        return result

    if not re.fullmatch(r"[0-9a-fA-F]{1,16}", result.stdout):
        return CmdResult(1, "", "ADB did not return a valid Android ID.")

    return CmdResult(0, "", "")


async def start_windows_maa(state: ScheduleCheckState) -> CmdResult:
    task = _powershell_literal(state.windows_start_task)
    script = f"try {{ Start-ScheduledTask -TaskName {task} -ErrorAction Stop; exit 0 }} catch {{ Write-Error $_.Exception.Message; exit 2 }}"
    return await run_windows_powershell(state, script)


async def stop_windows_maa(state: ScheduleCheckState) -> CmdResult:
    script = f"try {{ $processes = @({_windows_process_expression(state)}); if ($processes.Count -gt 0) {{ $processes | Stop-Process -Force -ErrorAction Stop }}; exit 0 }} catch {{ Write-Error $_.Exception.Message; exit 2 }}"
    return await run_windows_powershell(state, script)


async def wait_for_windows_maa(state: ScheduleCheckState, expected: CheckStatus, *, attempts: int = 10, delay: float = 1) -> CheckStatus:
    status = CheckStatus.ERROR

    for attempt in range(attempts):
        status = await check_windows_maa(state)

        if status is expected:
            return status

        if attempt + 1 < attempts:
            await asyncio.sleep(delay)

    return status


def _log_command_error(label: str, result: CmdResult) -> None:
    detail = result.stderr or result.stdout or f"exit status {result.returncode}"
    print(f"{label} failed: {detail}", file=sys.stderr)


def failure_message(name: str, profile: ProfileState, windows_status: CheckStatus, container_status: CheckStatus | None = None) -> str | None:
    failures = []

    if container_status is not None and container_status is not CheckStatus.OK:
        failures.append(text_for(profile.lang, "check_result_container", container_name=profile.schedule_check.container_name, container_state=text_for(profile.lang, f"check_result_container_{container_status.value}")))

    if windows_status is not CheckStatus.OK:
        failures.append(text_for(profile.lang, "check_result_windows", maa_state=text_for(profile.lang, f"check_result_maa_{windows_status.value}")))

    if not failures:
        return None

    return text_for(profile.lang, "check_result_failed", result="; ".join(failures))


async def collect_failure_message(name: str, profile: ProfileState) -> str | None:
    state = profile.schedule_check

    if state.container_name:
        container_status, windows_status = await asyncio.gather(check_container(state), check_windows_maa(state))
    else:
        container_status = None
        windows_status = await check_windows_maa(state)

    return failure_message(name, profile, windows_status, container_status)


async def check_and_notify(bot: Bot, name: str, profile: ProfileState) -> bool:
    message = await collect_failure_message(name, profile)

    if message is None:
        return False

    await bot.send_message(chat_id=profile.chat_id, text=message)
    return True


async def run(profile_name: str, *, notify: bool) -> int:
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


async def run_container_checks(profile_name: str, container_names: list[str], *, notify: bool, state_path: Path | None = None) -> int:
    profile = get_profile(resolve_profile_name(profile_name))

    if any(not CONTAINER_NAME_RE.fullmatch(name) for name in container_names):
        raise ValueError("Invalid container name.")

    state_path = state_path or CONTAINER_HEALTH_STATE_PATH
    state = load_alert_state(state_path) if notify else {}
    previous_state = dict(state)
    failures = []

    for name in dict.fromkeys(container_names):
        try:
            result = await check_container_health(replace(profile.schedule_check, container_name=name))
        except Exception as exc:
            result = CmdResult(1, "", str(exc))

        if result.returncode == 0:
            print(f"Container {name}: healthy.")
            state.pop(name, None)
            continue

        message = text_for(profile.lang, "container_health_failed", container_name=name, error=(result.stderr or result.stdout or f"exit status {result.returncode}")[:2500])
        print(message)
        failures.append((name, message))

    if notify and state != previous_state:
        save_alert_state(state, state_path)

    pending = [(name, message) for name, message in failures if name not in state]

    if pending and notify:
        async with Bot(TOKEN) as bot:
            for name, message in pending:
                await bot.send_message(chat_id=profile.chat_id, text=message)
                state[name] = "notified"
                save_alert_state(state, state_path)

    return 1 if failures else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Check a scheduled MAA profile's container and Windows GUI.")
    parser.add_argument("--profile", required=True, help="Telegram/MAA profile name.")
    parser.add_argument("--containers", nargs="+", help="Check only these Android containers; send failures to --profile, independent of its schedule.")
    parser.add_argument("--no-notify", action="store_true", help="Print the result without sending Telegram messages.")
    args = parser.parse_args()

    if args.containers:
        raise SystemExit(asyncio.run(run_container_checks(args.profile, args.containers, notify=not args.no_notify)))

    raise SystemExit(asyncio.run(run(args.profile, notify=not args.no_notify)))


if __name__ == "__main__":
    main()
