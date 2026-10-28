"""Offline regression checks: .venv/bin/python tests/test_container.py"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call, patch

from telegram.ext import CommandHandler

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def main() -> None:
    with TemporaryDirectory(prefix="maa-container-test-") as directory:
        config = Path(directory) / "config.yaml"
        config.write_text("TOKEN: offline-test-only\n", encoding="utf-8")
        (Path(directory) / "profiles.yaml").write_text(
            "ALPHA:\n  chat_id: 1\n  admin: true\n  schedule_check:\n    container_name: redroid-alpha\nBETA:\n  chat_id: 2\n  schedule_check:\n    container_name: redroid-beta\nEMPTY:\n  chat_id: 3\nGROUP:\n  chat_id: -4\n  admin: true\n", encoding="utf-8"
        )
        with patch.dict(os.environ, {"MAA_BOT_CONFIG": str(config)}):
            import handlers
            import schedule_health_checker as checker
            import telegram_ui
            from profile_store import get_profile, parse_schedule_check
            from systemd_utils import CmdResult

        ok = CmdResult(0, "", "")
        booted = CmdResult(0, "1", "")
        failure = CmdResult(1, "", "device offline")
        state = get_profile("ALPHA").schedule_check

        with patch("asyncio.create_subprocess_exec", new=AsyncMock(side_effect=AssertionError("Live subprocess"))), patch.object(checker, "run_cmd", new=AsyncMock()) as run, patch.object(checker.asyncio, "sleep", new=AsyncMock()):
            run.side_effect = [ok, CmdResult(0, "0", ""), booted, ok]
            assert (await checker.restart_container(state)).returncode == 0
            assert run.await_args_list == [
                call("docker", "restart", "--timeout", "20", "--", "redroid-alpha", timeout=45),
                call("docker", "exec", "redroid-alpha", "getprop", "sys.boot_completed", timeout=10),
                call("docker", "exec", "redroid-alpha", "getprop", "sys.boot_completed", timeout=10),
                call("docker", "exec", "redroid-alpha", "cmd", "bluetooth_manager", "disable", timeout=15),
            ]
            for responses in ([failure], [ok, failure], [ok, booted, failure]):
                run.reset_mock()
                run.side_effect = responses
                assert await checker.restart_container(state) is failure
                assert run.await_count == len(responses)

            run.reset_mock()
            run.side_effect = [ok, CmdResult(0, "0", "")]
            with patch.object(checker.asyncio, "get_running_loop", return_value=SimpleNamespace(time=Mock(side_effect=[0, 0, 121]))):
                result = await checker.restart_container(state)
            assert result.returncode == 124 and "Android" in result.stderr
            assert run.await_count == 2

            binding = {"HostIp": "127.0.0.1", "HostPort": "5556"}
            inspect = CmdResult(0, json.dumps({"running": True, "ports": [binding]}), "")
            identifier = CmdResult(0, "0123456789abcdef", "")
            for host, address in (("127.0.0.1", "127.0.0.1:5556"), ("0.0.0.0", "127.0.0.1:5556"), ("::", "[::1]:5556")):
                run.reset_mock()
                run.side_effect = [CmdResult(0, json.dumps({"running": True, "ports": [{**binding, "HostIp": host}]}), ""), booted, ok, identifier]
                result = await checker.check_container_health(state)
                assert result.returncode == 0 and identifier.stdout not in result.stdout
                assert run.await_args_list[-2:] == [call("adb", "connect", address, timeout=10), call("adb", "-s", address, "shell", "settings", "get", "secure", "android_id", timeout=10)]

            cases = [
                ([failure], "device offline"),
                ([CmdResult(0, "invalid-json", "")], "Could not read"),
                ([CmdResult(0, '{"running":false,"ports":null}', "")], "stopped"),
                ([inspect, failure], "device offline"),
                ([inspect, CmdResult(0, "0", "")], "not finished booting"),
                ([CmdResult(0, '{"running":true,"ports":null}', ""), booted], "not published"),
                ([inspect, booted, CmdResult(1, "", "Connection refused")], "Connection refused"),
                ([inspect, booted, CmdResult(124, "", "Timed out")], "Timed out"),
                ([inspect, booted, ok, failure], "device offline"),
                ([inspect, booted, CmdResult(0, "failed to connect", ""), CmdResult(1, "", "device '127.0.0.1:5556' not found")], "not found"),
                ([inspect, booted, ok, CmdResult(0, "null", "")], "valid Android ID"),
            ]
            for responses, error in cases:
                run.reset_mock()
                run.side_effect = responses
                result = await checker.check_container_health(state)
                assert result.returncode != 0 and error in result.stderr
                assert run.await_count == len(responses)
                assert all(not {"restart", "disconnect", "reconnect", "kill-server"}.intersection(item.args) for item in run.await_args_list)

        for invalid_name in ("--all", "one two", "x;touch /tmp/unwanted"):
            try:
                parse_schedule_check("TEST", {"container_name": invalid_name}, enabled=False)
            except ValueError:
                pass
            else:
                raise AssertionError("Invalid container name accepted")

        application = SimpleNamespace(add_handler=Mock())
        handlers.register_handlers(application)
        commands = {command: item.args[0].callback for item in application.add_handler.call_args_list if isinstance(item.args[0], CommandHandler) for command in item.args[0].commands}
        assert commands["container"] is handlers.container_command
        for language in ("en", "zh"):
            assert "container" in {command.command for command in handlers.bot_commands(language)}

        message = SimpleNamespace(reply_text=AsyncMock())
        update = SimpleNamespace(effective_chat=SimpleNamespace(id=1), effective_user=SimpleNamespace(id=1), effective_message=message, callback_query=None)
        context = SimpleNamespace(user_data={}, args=[])
        with patch.object(handlers, "restart_container", new=AsyncMock(return_value=ok)) as restart, patch.object(handlers, "check_container_health", new=AsyncMock(return_value=ok)) as health:
            await handlers.help_command(update, context)
            assert "/container health" in message.reply_text.call_args.args[0]
            assert "/container restart" in message.reply_text.call_args.args[0]

            for action, operation in (("restart", restart), ("health", health)):
                context.args = [action.upper()]
                await commands["container"](update, context)
                assert operation.await_args.args[0].container_name == "redroid-alpha"

                operation.reset_mock()
                context.args = ["beta", "container", action]
                original_args = context.args
                await commands["sudo"](update, context)
                operation.assert_awaited_once()
                assert operation.await_args.args[0].container_name == "redroid-beta"
                assert context.args is original_args and context.user_data == {"maa_name": "ALPHA"}

                operation.reset_mock()
                for chat_id, user_id in ((99, 99), (2, 2), (1, 999), (-4, 1)):
                    update.effective_chat.id, update.effective_user.id = chat_id, user_id
                    await commands["sudo"](update, context)
                operation.assert_not_awaited()

                for chat_id, args in ((99, [action]), (1, []), (1, [action, "redroid-beta"]), (1, ["check"]), (1, ["delete"]), (3, [action])):
                    update.effective_chat.id, update.effective_user.id = chat_id, chat_id
                    context.args = args
                    await commands["container"](update, context)
                operation.assert_not_awaited()

                update.effective_chat.id = update.effective_user.id = 1
                context.args = [action]
                operation.return_value = CmdResult(124, "", "Timed out: " + "x" * 5000)
                await commands["container"](update, context)
                reply = message.reply_text.call_args.args[0]
                assert reply.startswith("❌") and "Timed out" in reply and len(reply) < 4096
                operation.return_value = ok

        with patch.object(checker, "check_container_health", new=AsyncMock(return_value=failure)) as health, patch.object(checker, "check_windows_maa", new=AsyncMock(return_value=checker.CheckStatus.OK)), patch.object(checker, "_log_command_error"):
            summary = await telegram_ui.status_text("ALPHA")
            assert "redroid-alpha" in summary and "NOT READY" in summary
            summary = await checker.collect_failure_message(get_profile("ALPHA"))
            assert "redroid-alpha" in summary and "not ready" in summary
            health.return_value = ok
            assert "HEALTHY" in await telegram_ui.status_text("ALPHA")
            assert await checker.collect_failure_message(get_profile("ALPHA")) is None
            health.return_value = CmdResult(124, "", "Timed out")
            assert "CHECK ERROR" in await telegram_ui.status_text("ALPHA")
            health.reset_mock()
            assert "Container" not in await telegram_ui.status_text("EMPTY")
            health.assert_not_awaited()

    print("Passed: restart/timeouts, ADB health, validation, menus/help, authorization, admin delegation, status and scheduled health checks.")


if __name__ == "__main__":
    asyncio.run(main())
