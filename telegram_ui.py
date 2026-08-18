from __future__ import annotations

import html
from typing import Iterable

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.error import BadRequest
from telegram.ext import Application

from i18n import (
    mode_text,
    result_text,
    text_for,
)
from maa_config import (
    AUTHORIZED_BY_NAME,
    TIMEZONE,
    service_unit_for,
)
from profile_store import (
    get_profile,
)
from systemd_utils import (
    next_run,
    service_result,
    unit_is_active,
)


def html_pre(text: str) -> str:
    return (
        f"<pre>{html.escape(text)}</pre>"
    )


def html_code(text: str) -> str:
    return (
        f"<code>{html.escape(text)}</code>"
    )


def html_code_lines(
        lines: Iterable[str],
) -> str:
    return "\n".join(
        html_code(line)
        for line in lines
    )


def split_text(
        text: str,
        max_chars: int = 3400,
) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for line in text.splitlines():
        line_len = len(line) + 1

        if (
                current
                and current_len + line_len > max_chars
        ):
            chunks.append(
                "\n".join(current)
            )
            current = []
            current_len = 0

        if line_len > max_chars:
            if current:
                chunks.append(
                    "\n".join(current)
                )
                current = []
                current_len = 0

            remaining = line

            while len(remaining) > max_chars:
                chunks.append(
                    remaining[:max_chars]
                )
                remaining = remaining[
                    max_chars:
                ]

            if remaining:
                current = [
                    remaining
                ]
                current_len = (
                        len(remaining) + 1
                )

            continue

        current.append(line)
        current_len += line_len

    if current:
        chunks.append(
            "\n".join(current)
        )

    return chunks


async def safe_edit_message(
        query,
        text: str,
        *,
        reply_markup: InlineKeyboardMarkup | None = None,
        parse_mode: str | None = None,
) -> None:
    try:
        await query.edit_message_text(
            text,
            reply_markup=reply_markup,
            parse_mode=parse_mode,
        )

    except BadRequest as exc:
        if "Message is not modified" not in str(exc):
            raise


async def control_keyboard(name: str, ) -> InlineKeyboardMarkup:

    running = await unit_is_active(
        service_unit_for(name)
    )
    profile = get_profile(name)
    lang = profile.lang

    rows: list[
        list[InlineKeyboardButton]
    ] = [
        # Row 1: status + schedule
        [
            InlineKeyboardButton(
                text_for(
                    lang,
                    "button_status",
                ),
                callback_data="maa:status",
            ),
            InlineKeyboardButton(
                text_for(
                    lang,
                    "button_schedule",
                ),
                callback_data="maa:schedule",
            ),
        ],

        # Row 2: log + task
        [
            InlineKeyboardButton(
                text_for(
                    lang,
                    "button_log",
                    mode=mode_text(
                        lang,
                        profile.log,
                    ),
                ),
                callback_data="maa:log_toggle",
            ),
            InlineKeyboardButton(
                text_for(
                    lang,
                    "button_task",
                ),
                callback_data="maa:task",
            ),
        ],
    ]

    # Row 3: run OR stop
    if running:
        rows.append(
            [
                InlineKeyboardButton(
                    text_for(
                        lang,
                        "button_stop_run",
                    ),
                    callback_data="maa:stop",
                )
            ]
        )
    else:
        rows.append(
            [
                InlineKeyboardButton(
                    text_for(
                        lang,
                        "button_run_now",
                    ),
                    callback_data="maa:run",
                )
            ]
        )

    # Row 4: schedule ON/OFF
    if profile.schedule.times:
        if profile.schedule.enabled:
            rows.append(
                [
                    InlineKeyboardButton(
                        text_for(
                            lang,
                            "button_schedule_off",
                        ),
                        callback_data="maa:schedule_off",
                    )
                ]
            )
        else:
            rows.append(
                [
                    InlineKeyboardButton(
                        text_for(
                            lang,
                            "button_schedule_on",
                        ),
                        callback_data="maa:schedule_on",
                    )
                ]
            )

    return InlineKeyboardMarkup(
        rows
    )


async def status_text(
        name: str,
) -> str:
    running = await unit_is_active(
        service_unit_for(name)
    )
    profile = get_profile(name)
    schedule = profile.schedule
    lang = profile.lang

    run_state = (
        text_for(lang, "state_on")
        if running
        else text_for(lang, "state_off")
    )

    if not schedule.times:
        schedule_state = text_for(
            lang,
            "state_off",
        )
        next_line = ""

    elif schedule.enabled:
        schedule_state = text_for(
            lang,
            "state_on",
        )
        next_line = (
                "\n"
                + text_for(lang, "next_run_label")
                + ": "
                + await next_run(name, schedule)
        )

    else:
        count = len(
            schedule.times
        )

        if lang == "zh":
            schedule_state = text_for(
                lang,
                "schedule_saved",
                count=count,
                plural="",
            )
        else:
            schedule_state = text_for(
                lang,
                "schedule_saved",
                count=count,
                plural=(
                    "s"
                    if count != 1
                    else ""
                ),
            )

        next_line = ""

    last_result = result_text(
        lang,
        await service_result(name),
    )

    return (
        f"🤖 MAA {name}\n\n"
        f"{text_for(lang, 'run_label')}: {run_state}\n"
        f"{text_for(lang, 'schedule_label')}: "
        f"{schedule_state}"
        f"{next_line}\n"
        f"{text_for(lang, 'last_result_label')}: "
        f"{last_result}"
    )


async def schedule_text(
        name: str,
) -> str:
    profile = get_profile(name)
    schedule = profile.schedule
    lang = profile.lang

    if schedule.times:
        rows = "\n".join(
            f"• {value}"
            for value in schedule.times
        )

        if schedule.enabled:
            body = (
                f"{text_for(lang, 'state_label')}: "
                f"{text_for(lang, 'state_on')}\n"
                f"{text_for(lang, 'timezone_label')}: "
                f"{TIMEZONE}\n\n"
                f"{rows}\n\n"
                f"{text_for(lang, 'next_run_label')}: "
                f"{await next_run(name, schedule)}"
            )
        else:
            body = (
                f"{text_for(lang, 'state_label')}: "
                f"{text_for(lang, 'state_off')}\n"
                f"{text_for(lang, 'timezone_label')}: "
                f"{TIMEZONE}\n\n"
                f"{rows}"
            )

    else:
        body = (
            f"{text_for(lang, 'state_label')}: "
            f"{text_for(lang, 'state_off')}\n"
            f"{text_for(lang, 'timezone_label')}: "
            f"{TIMEZONE}\n\n"
            f"{text_for(lang, 'no_saved_schedule')}\n"
            f"{text_for(lang, 'no_auto_run')}"
        )

    commands = html_code_lines(
        [
            "/schedule set 00:33 06:33 14:33 17:33",
            "/schedule add 12:00",
            "/schedule remove 12:00",
            "/schedule on",
            "/schedule off",
        ]
    )

    return (
        f"{text_for(lang, 'schedule_title', name=name)}\n\n"
        f"{body}\n\n"
        f"{text_for(lang, 'commands_label')}:\n"
        f"{commands}"
    )


async def send_preformatted(
        application: Application,
        *,
        chat_id: int,
        title: str,
        text: str,
        continued_word: str = "continued",
) -> None:
    chunks = split_text(
        text
    )

    for i, chunk in enumerate(
            chunks
    ):
        chunk_title = (
            title
            if i == 0
            else f"{title} ({continued_word})"
        )

        await application.bot.send_message(
            chat_id=chat_id,
            text=(
                f"{html.escape(chunk_title)}\n\n"
                f"{html_pre(chunk)}"
            ),
            parse_mode="HTML",
        )


async def send_profile_preformatted(
        application: Application,
        *,
        name: str,
        title: str,
        text: str,
) -> None:
    chat_id = AUTHORIZED_BY_NAME.get(
        name
    )

    if chat_id is None:
        return

    lang = get_profile(name).lang

    await send_preformatted(
        application,
        chat_id=chat_id,
        title=title,
        text=text,
        continued_word=text_for(
            lang,
            "continued",
        ),
    )
