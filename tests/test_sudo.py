from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

import handlers
from profile_store import parse_profile, resolve_profile_name


def profile(*, admin: bool, chat_id: int = 1001, lang: str = "en") -> SimpleNamespace:
    return SimpleNamespace(admin=admin, chat_id=chat_id, lang=lang)


class ProfileAdminTests(TestCase):
    def test_admin_must_be_boolean(self) -> None:
        with self.assertRaisesRegex(ValueError, "admin must be true or false"):
            parse_profile("YAN", {"chat_id": 1001, "admin": "true"})

    def test_profile_name_resolution_is_case_insensitive(self) -> None:
        with patch("profile_store.load_profiles", return_value={"YAN": profile(admin=True), "LUN": profile(admin=False)}):
            self.assertEqual(resolve_profile_name("lun"), "LUN")


class SudoCommandTests(IsolatedAsyncioTestCase):
    @staticmethod
    def update(user_id: int) -> SimpleNamespace:
        return SimpleNamespace(
            effective_user=SimpleNamespace(id=user_id),
            effective_message=SimpleNamespace(reply_text=AsyncMock()),
        )

    async def test_admin_user_id_must_match_profile_chat_id(self) -> None:
        update = self.update(1002)
        context = SimpleNamespace(user_data={"maa_name": "YAN"}, args=["lun", "fight", "add", "1-7"])

        with patch.object(handlers, "get_profile", return_value=profile(admin=True, chat_id=1001)):
            await handlers.sudo_command.__wrapped__(update, context)

        update.effective_message.reply_text.assert_awaited_once()
        self.assertIn("Admin access denied", update.effective_message.reply_text.await_args.args[0])

    async def test_non_admin_is_denied_even_when_user_id_matches(self) -> None:
        update = self.update(1001)
        context = SimpleNamespace(user_data={"maa_name": "YAN"}, args=["lun", "fight", "add", "1-7"])

        with patch.object(handlers, "get_profile", return_value=profile(admin=False, chat_id=1001)):
            await handlers.sudo_command.__wrapped__(update, context)

        update.effective_message.reply_text.assert_awaited_once()
        self.assertIn("Admin access denied", update.effective_message.reply_text.await_args.args[0])

    async def test_allowed_command_runs_as_target_and_restores_context(self) -> None:
        update = self.update(1001)
        original_args = ["lun", "fight", "add", "1-7"]
        context = SimpleNamespace(user_data={"maa_name": "YAN"}, args=original_args)
        delegated_call = AsyncMock()

        async def delegated(update_arg, context_arg) -> None:
            self.assertIs(update_arg, update)
            self.assertEqual(context_arg.user_data["maa_name"], "LUN")
            self.assertEqual(context_arg.user_data["maa_sudo_target"], "LUN")
            self.assertEqual(context_arg.args, ["add", "1-7"])
            await delegated_call()

        async def wrapped_handler(update_arg, context_arg) -> None:
            raise AssertionError("The authorization wrapper must be bypassed for delegated commands.")

        wrapped_handler.__wrapped__ = delegated

        with patch.object(handlers, "get_profile", return_value=profile(admin=True, chat_id=1001)), \
                patch.object(handlers, "resolve_profile_name", return_value="LUN"), \
                patch.object(handlers, "fight_command", wrapped_handler):
            await handlers.sudo_command.__wrapped__(update, context)

        delegated_call.assert_awaited_once_with()
        self.assertEqual(context.user_data["maa_name"], "YAN")
        self.assertNotIn("maa_sudo_target", context.user_data)
        self.assertIs(context.args, original_args)

    async def test_command_outside_allowlist_is_rejected(self) -> None:
        update = self.update(1001)
        context = SimpleNamespace(user_data={"maa_name": "YAN"}, args=["lun", "alert", "off"])

        with patch.object(handlers, "get_profile", return_value=profile(admin=True, chat_id=1001)), \
                patch.object(handlers, "resolve_profile_name", return_value="LUN"):
            await handlers.sudo_command.__wrapped__(update, context)

        update.effective_message.reply_text.assert_awaited_once()
        self.assertIn("does not allow", update.effective_message.reply_text.await_args.args[0])

    async def test_other_allowed_commands_are_delegated(self) -> None:
        for command, delegated_args, handler_name in (
                ("schedule", ["off"], "schedule_command"),
                ("winmaa", ["app", "on"], "winmaa_command"),
                ("run", [], "run_command"),
                ("stop", [], "stop_command"),
        ):
            with self.subTest(command=command):
                update = self.update(1001)
                original_args = ["lun", command, *delegated_args]
                context = SimpleNamespace(user_data={"maa_name": "YAN"}, args=original_args)
                delegated_call = AsyncMock()

                async def delegated(update_arg, context_arg) -> None:
                    self.assertIs(update_arg, update)
                    self.assertEqual(context_arg.user_data["maa_name"], "LUN")
                    self.assertEqual(context_arg.user_data["maa_sudo_target"], "LUN")
                    self.assertEqual(context_arg.args, delegated_args)
                    await delegated_call()

                async def wrapped_handler(update_arg, context_arg) -> None:
                    raise AssertionError("The authorization wrapper must be bypassed for delegated commands.")

                wrapped_handler.__wrapped__ = delegated

                with patch.object(handlers, "get_profile", return_value=profile(admin=True, chat_id=1001)), \
                        patch.object(handlers, "resolve_profile_name", return_value="LUN"), \
                        patch.object(handlers, handler_name, wrapped_handler):
                    await handlers.sudo_command.__wrapped__(update, context)

                delegated_call.assert_awaited_once_with()
                self.assertEqual(context.user_data["maa_name"], "YAN")
                self.assertNotIn("maa_sudo_target", context.user_data)
                self.assertIs(context.args, original_args)

    async def test_delegated_run_and_stop_do_not_return_profile_buttons(self) -> None:
        for handler, is_active in ((handlers.run_command, True), (handlers.stop_command, False)):
            with self.subTest(handler=handler.__name__):
                update = self.update(1001)
                context = SimpleNamespace(user_data={"maa_name": "LUN", "maa_sudo_target": "LUN"}, args=[])

                with patch.object(handlers, "get_profile", return_value=profile(admin=False, lang="zh")), \
                        patch.object(handlers, "unit_is_active", AsyncMock(return_value=is_active)), \
                        patch.object(handlers, "status_text", AsyncMock(return_value="status")), \
                        patch.object(handlers, "control_keyboard", AsyncMock()) as control_keyboard:
                    await handler.__wrapped__(update, context)

                control_keyboard.assert_not_awaited()
                self.assertIsNone(update.effective_message.reply_text.await_args.kwargs["reply_markup"])
