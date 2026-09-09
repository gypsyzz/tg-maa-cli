from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

import schedule_health_checker
import handlers
from profile_store import parse_profile
from schedule_health_checker import CheckStatus, failure_message
from systemd_utils import CmdResult, render_schedule_check_timer


def checked_profile(lang: str = "en", container_name: str = "redroid-lun"):
    return parse_profile(
        "LUN",
        {
            "chat_id": 1001,
            "lang": lang,
            "schedule": {"run_enabled": False, "check_enabled": True, "times": ["02:00", "16:10"]},
            "schedule_check": {
                "container_name": container_name,
                "windows_host": "192.168.1.125",
                "windows_user": "gypsyzz",
                "ssh_identity": "~/.ssh/id_win125",
                "windows_process": "MAA",
                "windows_executable": r"C:\Users\gypsyzz\Documents\MAA - Lun\MAA.exe",
                "windows_start_task": "MAA Telegram LUN",
            },
        },
    )


class ScheduleCheckProfileTests(TestCase):
    def test_schedule_check_defaults_to_disabled(self) -> None:
        profile = parse_profile("YAN", {"chat_id": 1001})

        self.assertFalse(profile.schedule.check_enabled)
        self.assertEqual(profile.schedule_check.container_name, "")
        self.assertEqual(profile.schedule_check.windows_process, "MAA")

    def test_enabled_schedule_check_requires_windows_target(self) -> None:
        with self.assertRaisesRegex(ValueError, "windows_host is required"):
            parse_profile(
                "LUN",
                {
                    "chat_id": 1001,
                    "schedule": {"run_enabled": False, "check_enabled": True, "times": ["02:00"]},
                },
            )

    def test_run_and_check_modes_are_mutually_exclusive(self) -> None:
        with self.assertRaisesRegex(ValueError, "cannot both be true"):
            parse_profile(
                "LUN",
                {
                    "chat_id": 1001,
                    "schedule": {"run_enabled": True, "check_enabled": True, "times": ["02:00"]},
                },
            )

    def test_health_timer_reuses_saved_times_when_run_schedule_is_off(self) -> None:
        timer = render_schedule_check_timer("LUN", ["02:00", "16:10"])

        self.assertIn("OnCalendar=*-*-* 02:00:00", timer)
        self.assertIn("OnCalendar=*-*-* 16:10:00", timer)
        self.assertIn("Unit=maa-lun-schedule-check.service", timer)


class ScheduleHealthCheckerTests(IsolatedAsyncioTestCase):
    async def test_windows_failure_sends_one_message(self) -> None:
        profile = checked_profile()
        bot = SimpleNamespace(send_message=AsyncMock())

        with patch.object(schedule_health_checker, "check_container", AsyncMock(return_value=CheckStatus.OK)), \
                patch.object(schedule_health_checker, "check_windows_maa", AsyncMock(return_value=CheckStatus.DOWN)):
            sent = await schedule_health_checker.check_and_notify(bot, "LUN", profile)

        self.assertTrue(sent)
        bot.send_message.assert_awaited_once()
        message = bot.send_message.await_args.kwargs["text"]
        self.assertEqual(message, "❌ Check result: Windows MAA is closed.")

    async def test_healthy_check_sends_no_message(self) -> None:
        profile = checked_profile()
        bot = SimpleNamespace(send_message=AsyncMock())

        with patch.object(schedule_health_checker, "check_container", AsyncMock(return_value=CheckStatus.OK)), \
                patch.object(schedule_health_checker, "check_windows_maa", AsyncMock(return_value=CheckStatus.OK)):
            sent = await schedule_health_checker.check_and_notify(bot, "LUN", profile)

        self.assertFalse(sent)
        bot.send_message.assert_not_awaited()

    def test_chinese_failure_message(self) -> None:
        profile = checked_profile(lang="zh")
        message = failure_message("LUN", profile, CheckStatus.DOWN)

        self.assertEqual(message, "❌ 检查结果：Windows MAA 已关闭。")

    def test_windows_check_error_is_reported(self) -> None:
        profile = checked_profile()

        self.assertEqual(
            failure_message("LUN", profile, CheckStatus.ERROR),
            "❌ Check result: Windows MAA status could not be checked.",
        )

    def test_stopped_container_is_reported(self) -> None:
        profile = checked_profile()

        self.assertEqual(
            failure_message("LUN", profile, CheckStatus.OK, CheckStatus.DOWN),
            "❌ Check result: container redroid-lun is stopped.",
        )

    async def test_container_running_check(self) -> None:
        profile = checked_profile()

        with patch.object(schedule_health_checker, "run_cmd", AsyncMock(return_value=CmdResult(0, "true", ""))):
            status = await schedule_health_checker.check_container(profile.schedule_check)

        self.assertIs(status, CheckStatus.OK)


class WinMaaCommandTests(IsolatedAsyncioTestCase):
    @staticmethod
    def update():
        return SimpleNamespace(effective_message=SimpleNamespace(reply_text=AsyncMock()))

    async def test_bare_command_reports_full_status(self) -> None:
        profile = checked_profile()
        update = self.update()
        context = SimpleNamespace(user_data={"maa_name": "LUN"}, args=[])

        with patch.object(handlers, "get_profile", return_value=profile), \
                patch.object(handlers, "unit_is_active", AsyncMock(return_value=True)), \
                patch.object(handlers, "validate_schedule_check", return_value=profile.schedule_check), \
                patch.object(handlers, "check_container", AsyncMock(return_value=CheckStatus.OK)), \
                patch.object(handlers, "check_windows_maa", AsyncMock(return_value=CheckStatus.OK)):
            await handlers.winmaa_command.__wrapped__(update, context)

        reply = update.effective_message.reply_text.await_args.args[0]
        self.assertEqual(
            reply,
            "🔎 LUN MAA readiness status\n"
            "Monitor timer: 🟢 ACTIVE\n"
            "Container redroid-lun: ✅ RUNNING\n"
            "Windows MAA: ✅ OPEN",
        )
        self.assertNotIn("192.168.1.125", reply)

    async def test_check_subcommand_runs_immediate_check(self) -> None:
        profile = checked_profile()
        update = self.update()
        context = SimpleNamespace(user_data={"maa_name": "LUN"}, args=["check"])

        with patch.object(handlers, "get_profile", return_value=profile), \
                patch.object(handlers, "validate_schedule_check"), \
                patch.object(handlers, "collect_failure_message", AsyncMock(return_value=None)):
            await handlers.winmaa_command.__wrapped__(update, context)

        reply = update.effective_message.reply_text.await_args.args[0]
        self.assertEqual(reply, "✅ Check result: all monitored services are ready.")

    async def test_monitor_on_controls_only_repeating_checker(self) -> None:
        profile = checked_profile()
        profile.schedule.check_enabled = False
        update = self.update()
        context = SimpleNamespace(user_data={"maa_name": "LUN"}, args=["monitor", "on"])

        with patch.object(handlers, "get_profile", return_value=profile), \
                patch.object(handlers, "set_schedule", return_value=profile.schedule) as set_schedule, \
                patch.object(handlers, "sync_timer", AsyncMock()) as sync_timer:
            await handlers.winmaa_command.__wrapped__(update, context)

        set_schedule.assert_called_once_with("LUN", check_enabled=True)
        sync_timer.assert_awaited_once_with("LUN", profile.schedule)

    async def test_monitor_without_action_reports_timer_status(self) -> None:
        profile = checked_profile()
        update = self.update()
        context = SimpleNamespace(user_data={"maa_name": "LUN"}, args=["monitor"])

        with patch.object(handlers, "get_profile", return_value=profile), \
                patch.object(handlers, "unit_is_active", AsyncMock(return_value=False)):
            await handlers.winmaa_command.__wrapped__(update, context)

        reply = update.effective_message.reply_text.await_args.args[0]
        self.assertEqual(reply, "Monitor timer: 🟠 INACTIVE")

    async def test_app_without_action_reports_current_status(self) -> None:
        profile = checked_profile()
        update = self.update()
        context = SimpleNamespace(user_data={"maa_name": "LUN"}, args=["app"])

        with patch.object(handlers, "get_profile", return_value=profile), \
                patch.object(handlers, "validate_schedule_check", return_value=profile.schedule_check), \
                patch.object(handlers, "check_windows_maa", AsyncMock(return_value=CheckStatus.DOWN)):
            await handlers.winmaa_command.__wrapped__(update, context)

        reply = update.effective_message.reply_text.await_args.args[0]
        self.assertEqual(reply, "Windows MAA: ❌ CLOSED")
        self.assertNotIn("192.168.1.125", reply)

    async def test_app_on_uses_windows_task_without_container_control(self) -> None:
        profile = checked_profile()
        update = self.update()
        context = SimpleNamespace(user_data={"maa_name": "LUN"}, args=["app", "on"])

        with patch.object(handlers, "get_profile", return_value=profile), \
                patch.object(handlers, "validate_windows_app_control", return_value=profile.schedule_check), \
                patch.object(handlers, "wait_for_windows_maa", AsyncMock(side_effect=[CheckStatus.DOWN, CheckStatus.OK])), \
                patch.object(handlers, "start_windows_maa", AsyncMock(return_value=CmdResult(0, "", ""))) as start_app:
            await handlers.winmaa_command.__wrapped__(update, context)

        start_app.assert_awaited_once_with(profile.schedule_check)
        reply = update.effective_message.reply_text.await_args.args[0]
        self.assertEqual(reply, "✅ Windows MAA is open.")
        self.assertNotIn("192.168.1.125", reply)

    async def test_app_closed_status_does_not_show_host(self) -> None:
        profile = checked_profile()
        update = self.update()
        context = SimpleNamespace(user_data={"maa_name": "LUN"}, args=["app", "off"])

        with patch.object(handlers, "get_profile", return_value=profile), \
                patch.object(handlers, "validate_windows_app_control", return_value=profile.schedule_check), \
                patch.object(handlers, "wait_for_windows_maa", AsyncMock(return_value=CheckStatus.DOWN)):
            await handlers.winmaa_command.__wrapped__(update, context)

        reply = update.effective_message.reply_text.await_args.args[0]
        self.assertEqual(reply, "ℹ️ Windows MAA is already closed.")
        self.assertNotIn("192.168.1.125", reply)

    async def test_container_control_subcommand_is_not_available(self) -> None:
        profile = checked_profile()
        update = self.update()
        context = SimpleNamespace(user_data={"maa_name": "LUN"}, args=["container", "off"])

        with patch.object(handlers, "get_profile", return_value=profile):
            await handlers.winmaa_command.__wrapped__(update, context)

        reply = update.effective_message.reply_text.await_args.args[0]
        self.assertIn("Unknown winmaa command", reply)
        self.assertNotIn("/winmaa container", reply)
        self.assertNotIn("/winmaa all", reply)
