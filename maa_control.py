#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio

from telegram import (
    BotCommandScopeChat,
)
from telegram.ext import (
    Application,
    ApplicationBuilder,
)

from handlers import (
    register_handlers,
)
from i18n import (
    bot_commands,
)
from log_monitor import (
    log_monitor_loop,
)
from maa_config import (
    AUTHORIZED_BY_NAME,
    TOKEN,
)
from profile_store import (
    ensure_profiles_file,
    get_profile,
)
from systemd_utils import (
    sync_timer,
)


async def sync_all_timers() -> None:
    for name in AUTHORIZED_BY_NAME:
        await sync_timer(
            name,
            get_profile(name).schedule,
        )


async def set_command_menus(
    application: Application,
) -> None:
    # English fallback for any client that does not match a
    # per-chat scope.
    await application.bot.set_my_commands(
        bot_commands("en")
    )

    # Each authorized profile/chat gets its own localized menu.
    for name, chat_id in AUTHORIZED_BY_NAME.items():
        lang = get_profile(name).lang

        await application.bot.set_my_commands(
            bot_commands(lang),
            scope=BotCommandScopeChat(
                chat_id
            ),
        )


async def post_init(
    application: Application,
) -> None:
    ensure_profiles_file()
    await sync_all_timers()
    await set_command_menus(
        application
    )

    application.bot_data[
        "log_monitor_task"
    ] = asyncio.create_task(
        log_monitor_loop(
            application
        )
    )


async def post_stop(
    application: Application,
) -> None:
    task = application.bot_data.get(
        "log_monitor_task"
    )

    if task is None:
        return

    task.cancel()

    try:
        await task
    except asyncio.CancelledError:
        pass


def build_application() -> Application:
    application = (
        ApplicationBuilder()
        .token(TOKEN)
        .post_init(post_init)
        .post_stop(post_stop)
        .build()
    )

    register_handlers(
        application
    )

    return application


async def cli_sync_profiles() -> None:
    ensure_profiles_file()
    await sync_all_timers()

    for name in AUTHORIZED_BY_NAME:
        profile = get_profile(name)
        schedule = profile.schedule

        if not schedule.times:
            schedule_text = "no schedule"
        elif schedule.enabled:
            schedule_text = (
                "schedule ON: "
                + ", ".join(
                    schedule.times
                )
            )
        else:
            schedule_text = (
                "schedule OFF: "
                + ", ".join(
                    schedule.times
                )
            )

        print(
            f"{name}: {schedule_text}; "
            f"log={profile.log}; "
            f"lang={profile.lang}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Telegram controller for "
            "per-chat MAA profiles"
        )
    )

    parser.add_argument(
        "--sync-profiles",
        action="store_true",
        help=(
            "sync profiles.yaml schedules "
            "into user systemd timers and exit"
        ),
    )

    args = parser.parse_args()

    if args.sync_profiles:
        asyncio.run(
            cli_sync_profiles()
        )
        return

    build_application().run_polling(
        drop_pending_updates=False
    )


if __name__ == "__main__":
    main()
