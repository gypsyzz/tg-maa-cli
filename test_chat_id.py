"""Offline regression checks: .venv/bin/python test_chat_id.py"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from telegram.ext import CommandHandler


async def main() -> None:
    with TemporaryDirectory(prefix="maa-chat-id-test-") as directory:
        config = Path(directory) / "config.yaml"
        config.write_text("TOKEN: offline-test-only\n", encoding="utf-8")
        with patch.dict(os.environ, {"MAA_BOT_CONFIG": str(config)}):
            import handlers

        application = SimpleNamespace(add_handler=Mock())
        handlers.register_handlers(application)
        commands = {command: call.args[0].callback for call in application.add_handler.call_args_list if isinstance(call.args[0], CommandHandler) for command in call.args[0].commands}
        assert commands["chat_id"] is handlers.chat_id_command
        assert commands["start"] is commands["status"] is handlers.start_command
        for language in ("en", "zh"):
            assert "chat_id" in {command.command for command in handlers.bot_commands(language)}

        context = SimpleNamespace(user_data={})
        message = SimpleNamespace(reply_text=AsyncMock())
        update = SimpleNamespace(effective_chat=None, effective_message=message, effective_user=SimpleNamespace(id=999), callback_query=None)
        with (
            patch.object(handlers, "get_profile_by_chat_id", side_effect=AssertionError("Unexpected profile lookup")),
            patch.object(handlers, "get_profile", side_effect=AssertionError("Unexpected profile lookup")),
            patch.object(handlers, "status_text", new=AsyncMock(side_effect=AssertionError("Unexpected status lookup"))),
            patch.object(handlers, "control_keyboard", new=AsyncMock(side_effect=AssertionError("Unexpected control panel"))),
        ):
            for chat_id in (123456789, -1001234567890):
                update.effective_chat = SimpleNamespace(id=chat_id)
                message.reply_text.reset_mock()
                await commands["chat_id"](update, context)
                message.reply_text.assert_awaited_once_with(f"chat_id: {chat_id}")
                assert context.user_data == {}

            for chat, effective_message in ((None, message), (SimpleNamespace(id=123), None), (None, None)):
                update.effective_chat = chat
                update.effective_message = effective_message
                message.reply_text.reset_mock()
                await commands["chat_id"](update, context)
                message.reply_text.assert_not_awaited()

        update.effective_chat = SimpleNamespace(id=123456789)
        update.effective_message = message
        keyboard = object()
        with patch.object(handlers, "get_profile_by_chat_id") as profile_lookup, patch.object(handlers, "status_text", new=AsyncMock(return_value="Existing panel")), patch.object(handlers, "control_keyboard", new=AsyncMock(return_value=keyboard)):
            for command in ("start", "status"):
                profile_lookup.return_value = None
                message.reply_text.reset_mock()
                await commands[command](update, context)
                message.reply_text.assert_not_awaited()

                profile_lookup.return_value = ("TEST", None)
                await commands[command](update, context)
                message.reply_text.assert_awaited_once_with("Existing panel", reply_markup=keyboard)

    print("Passed: public chat IDs, group IDs, missing updates, menus, and unchanged authorized start/status panels.")


if __name__ == "__main__":
    asyncio.run(main())
