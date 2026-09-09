from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

import telegram_ui


class OverallStatusTests(IsolatedAsyncioTestCase):
    async def test_status_contains_only_run_and_check_schedules(self) -> None:
        profile = SimpleNamespace(
            lang="en",
            schedule=SimpleNamespace(run_enabled=False, check_enabled=True, times=["00:33", "06:33"]),
        )

        with patch.object(telegram_ui, "get_profile", return_value=profile):
            message = await telegram_ui.status_text("YAN")

        self.assertEqual(
            message,
            "🤖 MAA YAN\n\n"
            "Run schedule: 🟠 OFF\n"
            "Check schedule: 🟢 ON",
        )

    async def test_chinese_status_uses_schedule_labels(self) -> None:
        profile = SimpleNamespace(
            lang="zh",
            schedule=SimpleNamespace(run_enabled=True, check_enabled=False, times=["00:33"]),
        )

        with patch.object(telegram_ui, "get_profile", return_value=profile):
            message = await telegram_ui.status_text("LUN")

        self.assertEqual(
            message,
            "🤖 MAA LUN\n\n"
            "运行定时: 🟢 开启\n"
            "检查定时: 🟠 关闭",
        )
