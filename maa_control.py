#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio

from telegram import Bot, BotCommandScopeChat
from telegram.ext import Application, ApplicationBuilder

from alert_checker import check_all_alerts
from handlers import register_handlers
from i18n import bot_commands
from log_monitor import log_monitor_loop
from maa_config import TOKEN
from profile_store import ensure_profiles_file, load_profiles
from systemd_utils import sync_timer


async def sync_all_timers() -> None:
    for name, profile in load_profiles().items():
        await sync_timer(name, profile.schedule, )


async def set_command_menus(application: Application, ) -> None:
    # English fallback for any client that does not match a
    # per-chat scope.
    await application.bot.set_my_commands(
        bot_commands("en")
    )

    # Each authorized profile/chat gets its own localized menu.
    for profile in load_profiles().values():
        await application.bot.set_my_commands(
            bot_commands(profile.lang),
            scope=BotCommandScopeChat(profile.chat_id),
        )


async def post_init(application: Application, ) -> None:
    ensure_profiles_file()
    await sync_all_timers()
    await set_command_menus(application)

    application.bot_data["log_monitor_task"] = asyncio.create_task(log_monitor_loop(application))


async def post_stop(application: Application, ) -> None:
    task = application.bot_data.get("log_monitor_task")

    if task is None:
        return

    task.cancel()

    try:
        await task
    except asyncio.CancelledError:
        pass


def build_application() -> Application:
    application = (ApplicationBuilder().token(TOKEN).post_init(post_init).post_stop(post_stop).build())

    register_handlers(application)

    return application


async def cli_sync_profiles() -> None:
    ensure_profiles_file()
    await sync_all_timers()

    for name, profile in load_profiles().items():
        schedule = profile.schedule

        if not schedule.times:
            schedule_text = "no schedule"
        elif schedule.enabled:
            schedule_text = ("schedule ON: " + ", ".join(schedule.times))
        else:
            schedule_text = ("schedule OFF: " + ", ".join(schedule.times))

        alert_text = (("ON" if profile.alert.enabled else "OFF") + f"/{profile.alert.hours}h")

        print(f"{name}: {schedule_text}; " f"alert={alert_text}; " f"log={profile.log}; " f"lang={profile.lang}")


async def cli_check_alerts() -> None:
    async with Bot(TOKEN) as bot:
        await check_all_alerts(bot)


def main() -> None:
    parser = argparse.ArgumentParser(description=("Telegram controller for " "per-chat MAA profiles"))

    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--sync-profiles", action="store_true",
                         help=("sync profiles.yaml schedules " "into user systemd timers and exit"), )
    actions.add_argument("--check-alerts", action="store_true",
                         help="check enabled inactivity alerts once and exit", )

    args = parser.parse_args()

    if args.sync_profiles:
        asyncio.run(cli_sync_profiles())
        return

    if args.check_alerts:
        asyncio.run(cli_check_alerts())
        return

    build_application().run_polling(drop_pending_updates=False)


if __name__ == "__main__":
    main()
