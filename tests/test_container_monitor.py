"""Offline regression checks: .venv/bin/python tests/test_container_monitor.py"""

from __future__ import annotations

import asyncio
import io
import os
import sys
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def main() -> None:
    with TemporaryDirectory(prefix="maa-container-monitor-test-") as directory:
        root = Path(directory)
        config = root / "config.yaml"
        config.write_text("TOKEN: offline-test-only\n", encoding="utf-8")
        (root / "profiles.yaml").write_text("YAN:\n  chat_id: 123\n  lang: zh\n", encoding="utf-8")
        with patch.dict(os.environ, {"MAA_BOT_CONFIG": str(config)}):
            import schedule_health_checker as checker
            from systemd_utils import CmdResult

        names = ["redroid-one", "redroid-two", "redroid-three"]
        state_path = root / "state.yaml"
        ok = CmdResult(0, "", "")
        down = CmdResult(1, "", "device offline")
        bot = AsyncMock()
        bot.__aenter__.return_value = bot

        with patch.object(checker, "check_container_health", new=AsyncMock()) as health, patch.object(checker, "Bot", return_value=bot) as bot_type, patch("asyncio.create_subprocess_exec", new=AsyncMock(side_effect=AssertionError("Live subprocess"))), redirect_stdout(io.StringIO()):
            health.side_effect = [ok, ok, ok]
            assert await checker.run_container_checks("yan", names, notify=True, state_path=state_path) == 0
            assert [item.args[0].container_name for item in health.await_args_list] == names
            bot_type.assert_not_called()
            assert not state_path.exists()

            health.side_effect = [down, ok, RuntimeError("probe failed")]
            assert await checker.run_container_checks("YAN", names, notify=True, state_path=state_path) == 1
            assert bot.send_message.await_count == 2
            messages = bot.send_message.await_args_list
            assert all(item.kwargs["chat_id"] == 123 for item in messages)
            assert names[0] in messages[0].kwargs["text"] and "device offline" in messages[0].kwargs["text"]
            assert names[2] in messages[1].kwargs["text"] and "probe failed" in messages[1].kwargs["text"]
            assert set(checker.load_alert_state(state_path)) == {names[0], names[2]}

            bot_type.reset_mock()
            bot.send_message.reset_mock()
            health.side_effect = [down, ok, CmdResult(124, "", "Timed out")]
            assert await checker.run_container_checks("YAN", names, notify=True, state_path=state_path) == 1
            bot_type.assert_not_called()

            health.side_effect = [ok, ok, down]
            assert await checker.run_container_checks("YAN", names, notify=True, state_path=state_path) == 1
            assert set(checker.load_alert_state(state_path)) == {names[2]}
            bot_type.assert_not_called()

            health.side_effect = [down, ok, down]
            assert await checker.run_container_checks("YAN", names, notify=True, state_path=state_path) == 1
            bot.send_message.assert_awaited_once()
            assert names[0] in bot.send_message.await_args.kwargs["text"]

            bot_type.reset_mock()
            saved = state_path.read_bytes()
            for results, status in (([ok, ok, ok], 0), ([down, down, down], 1)):
                health.side_effect = results
                assert await checker.run_container_checks("YAN", names, notify=False, state_path=state_path) == status
                assert state_path.read_bytes() == saved
            bot_type.assert_not_called()

            retry_path = root / "retry.yaml"
            bot.send_message.side_effect = RuntimeError("Telegram unavailable")
            health.side_effect = [down, ok, ok]
            try:
                await checker.run_container_checks("YAN", names, notify=True, state_path=retry_path)
            except RuntimeError:
                pass
            else:
                raise AssertionError("Delivery error was hidden")
            assert names[0] not in checker.load_alert_state(retry_path)
            bot.send_message.side_effect = None
            health.side_effect = [down, ok, ok]
            assert await checker.run_container_checks("YAN", names, notify=True, state_path=retry_path) == 1
            assert names[0] in checker.load_alert_state(retry_path)

            health.reset_mock()
            bot_type.reset_mock()
            for recipient, targets in (("missing", names), ("YAN", ["--all"]), ("YAN", ["x;touch /tmp/unwanted"])):
                try:
                    await checker.run_container_checks(recipient, targets, notify=True, state_path=state_path)
                except ValueError:
                    pass
                else:
                    raise AssertionError("Invalid recipient or target accepted")
            health.assert_not_awaited()
            bot_type.assert_not_called()

    print("Passed: all targets, YAN routing, healthy silence, persistent deduplication, recovery, failed delivery retry and read-only dry runs.")


if __name__ == "__main__":
    asyncio.run(main())
