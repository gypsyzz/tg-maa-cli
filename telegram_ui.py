from __future__ import annotations

import html
from typing import Iterable

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import Application

from i18n import mode_text, text_for
from maa_config import TIMEZONE, service_unit_for
from profile_store import get_profile
from systemd_utils import next_run, unit_is_active

PREFORMATTED_TEXT_LIMIT = 3400


def html_pre(text: str) -> str:
    return f"<pre>{html.escape(text)}</pre>"


def html_code(text: str) -> str:
    return f"<code>{html.escape(text)}</code>"


def html_code_lines(lines: Iterable[str], ) -> str:
    return "\n".join(html_code(line) for line in lines)


def split_text(text: str, max_chars: int = PREFORMATTED_TEXT_LIMIT, ) -> list[str]:
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for line in text.splitlines():
        line_len = len(line) + 1

        if (current and current_len + line_len > max_chars):
            chunks.append("\n".join(current))
            current = []
            current_len = 0

        if line_len > max_chars:
            if current:
                chunks.append("\n".join(current))
                current = []
                current_len = 0

            remaining = line

            while len(remaining) > max_chars:
                chunks.append(remaining[:max_chars])
                remaining = remaining[max_chars:]

            if remaining:
                current = [remaining]
                current_len = (len(remaining) + 1)

            continue

        current.append(line)
        current_len += line_len

    if current:
        chunks.append("\n".join(current))

    return chunks


async def safe_edit_message(query, text: str, *, reply_markup: InlineKeyboardMarkup | None = None, parse_mode: str | None = None, ) -> None:
    try:
        await query.edit_message_text(text, reply_markup=reply_markup, parse_mode=parse_mode, )

    except BadRequest as exc:
        if "Message is not modified" not in str(exc):
            raise


async def control_keyboard(name: str, ) -> InlineKeyboardMarkup:
    running = await unit_is_active(service_unit_for(name))
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
        rows.append([InlineKeyboardButton(text_for(lang, "button_stop_run", ), callback_data="maa:stop", )])
    else:
        rows.append([InlineKeyboardButton(text_for(lang, "button_run_now", ), callback_data="maa:run", )])

    # Row 4: schedule ON/OFF
    if profile.schedule.times:
        if profile.schedule.run_enabled:
            rows.append([InlineKeyboardButton(text_for(lang, "button_schedule_off", ), callback_data="maa:schedule_off", )])
        else:
            rows.append([InlineKeyboardButton(text_for(lang, "button_schedule_on", ), callback_data="maa:schedule_on", )])

    return InlineKeyboardMarkup(rows)


async def status_text(name: str, ) -> str:
    profile = get_profile(name)
    schedule = profile.schedule
    lang = profile.lang

    run_schedule_state = text_for(lang, "state_on" if schedule.run_enabled else "state_off", )
    check_schedule_state = text_for(lang, "state_on" if schedule.check_enabled else "state_off", )

    return (f"🤖 MAA {name}\n\n" f"{text_for(lang, 'run_schedule_label')}: {run_schedule_state}\n" f"{text_for(lang, 'check_schedule_label')}: {check_schedule_state}")


async def schedule_text(name: str, ) -> str:
    profile = get_profile(name)
    schedule = profile.schedule
    lang = profile.lang

    if schedule.times:
        rows = "\n".join(f"• {value}" for value in schedule.times)

        if schedule.run_enabled:
            body = (f"{text_for(lang, 'state_label')}: " f"{text_for(lang, 'state_on')}\n" f"{text_for(lang, 'timezone_label')}: " f"{TIMEZONE}\n\n" f"{rows}\n\n" f"{text_for(lang, 'next_run_label')}: " f"{await next_run(name, schedule)}")
        else:
            body = (f"{text_for(lang, 'state_label')}: " f"{text_for(lang, 'state_off')}\n" f"{text_for(lang, 'timezone_label')}: " f"{TIMEZONE}\n\n" f"{rows}")

    else:
        body = (f"{text_for(lang, 'state_label')}: " f"{text_for(lang, 'state_off')}\n" f"{text_for(lang, 'timezone_label')}: " f"{TIMEZONE}\n\n" f"{text_for(lang, 'no_saved_schedule')}\n" f"{text_for(lang, 'no_auto_run')}")

    commands = html_code_lines(["/schedule set 00:33 06:33 14:33 17:33", "/schedule add 12:00", "/schedule remove 12:00", "/schedule on", "/schedule off", ])

    return (f"{text_for(lang, 'schedule_title', name=name)}\n\n" f"{body}\n\n" f"{text_for(lang, 'commands_label')}:\n" f"{commands}")


async def send_preformatted(application: Application, *, chat_id: int, title: str, text: str, continued_word: str = "continued", ) -> None:
    chunks = split_text(text)

    for i, chunk in enumerate(chunks):
        chunk_title = (title if i == 0 else f"{title} ({continued_word})")

        await application.bot.send_message(chat_id=chat_id, text=(f"{html.escape(chunk_title)}\n\n" f"{html_pre(chunk)}"), parse_mode="HTML", )


async def send_profile_preformatted(application: Application, *, name: str, title: str, text: str, ) -> None:
    profile = get_profile(name)

    await send_preformatted(
        application,
        chat_id=profile.chat_id,
        title=title,
        text=text,
        continued_word=text_for(profile.lang, "continued", ),
    )
