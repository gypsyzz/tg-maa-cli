from __future__ import annotations

import html
from functools import wraps

from telegram import BotCommandScopeChat, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from i18n import bot_commands, language_name, mode_text, normalize_language, text_for
from maa_config import NAME_BY_CHAT_ID, service_unit_for
from profile_store import get_log_mode, get_profile, normalize_times, set_language, set_log_mode, set_schedule
from systemd_utils import run_cmd, sync_timer, unit_is_active
from task_store import (add_fight_task, fight_sequence, load_task_json, long_task_sequence, parse_fight_add_args,
                        remove_fight_task, save_task_json, short_task_sequence, )
from telegram_ui import (control_keyboard, html_code, html_code_lines, html_pre, safe_edit_message, schedule_text,
                         split_text, status_text, )


def name_for_update(update: Update, ) -> str | None:
    chat = update.effective_chat

    if chat is None:
        return None

    return NAME_BY_CHAT_ID.get(chat.id)


def auth_required(func):
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs, ):
        name = name_for_update(update)

        if name is None:
            if update.callback_query:
                await update.callback_query.answer("Unauthorized", show_alert=True, )
            return None

        context.user_data["maa_name"] = name

        return await func(update, context, *args, **kwargs, )

    return wrapped


def current_name(context: ContextTypes.DEFAULT_TYPE, ) -> str:
    return str(context.user_data["maa_name"])


def current_lang(name: str) -> str:
    return get_profile(name).lang


async def reply_preformatted(update: Update, name: str, title: str, text: str, ) -> None:
    message = update.effective_message

    if message is None:
        return

    lang = current_lang(name)
    chunks = split_text(text)

    for i, chunk in enumerate(chunks):
        chunk_title = (title if i == 0 else (f"{title} " f"({text_for(lang, 'continued')})"))

        await message.reply_text(f"{html.escape(chunk_title)}\n\n" f"{html_pre(chunk)}", parse_mode="HTML", )


async def reply_error(update: Update, exc: Exception, ) -> None:
    await update.effective_message.reply_text(f"❌ {exc}")


@auth_required
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE, ) -> None:
    name = current_name(context)

    await update.effective_message.reply_text(await status_text(name), reply_markup=await control_keyboard(name), )


@auth_required
async def schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE, ) -> None:
    name = current_name(context)
    lang = current_lang(name)

    if not context.args:
        await update.effective_message.reply_text(await schedule_text(name), parse_mode="HTML", )
        return

    action = context.args[0].lower()
    values = context.args[1:]

    if action == "set":
        if not values:
            await update.effective_message.reply_text(
                f"{text_for(lang, 'usage_label')}:\n" + html_code("/schedule set 00:33 17:33"), parse_mode="HTML", )
            return

        try:
            schedule = set_schedule(name, times=values, enabled=True, )
            await sync_timer(name, schedule)
        except (ValueError, RuntimeError) as exc:
            await reply_error(update, exc)
            return

        await update.effective_message.reply_text(
            text_for(lang, "schedule_set_enabled", name=name, ) + "\n" + "\n".join(
                f"• {value}" for value in schedule.times))
        return

    if action == "add":
        if not values:
            await update.effective_message.reply_text(
                f"{text_for(lang, 'usage_label')}:\n" + html_code("/schedule add 12:00"), parse_mode="HTML", )
            return

        try:
            current = get_profile(name).schedule
            times = normalize_times([*current.times, *values, ])

            enabled = (current.enabled if current.times else True)

            schedule = set_schedule(name, times=times, enabled=enabled, )
            await sync_timer(name, schedule)
        except (ValueError, RuntimeError) as exc:
            await reply_error(update, exc)
            return

        state = (text_for(lang, "state_on") if schedule.enabled else text_for(lang, "state_off"))

        await update.effective_message.reply_text(
            text_for(lang, "schedule_updated", name=name, state=state, ) + "\n" + "\n".join(
                f"• {value}" for value in schedule.times))
        return

    if action == "remove":
        if not values:
            await update.effective_message.reply_text(
                f"{text_for(lang, 'usage_label')}:\n" + html_code("/schedule remove 12:00"), parse_mode="HTML", )
            return

        try:
            current = get_profile(name).schedule
            remove = set(normalize_times(values))
            times = [value for value in current.times if value not in remove]

            schedule = set_schedule(name, times=times, enabled=(current.enabled if times else False), )
            await sync_timer(name, schedule)
        except (ValueError, RuntimeError) as exc:
            await reply_error(update, exc)
            return

        if schedule.times:
            state = (text_for(lang, "state_on") if schedule.enabled else text_for(lang, "state_off"))
            message = (text_for(lang, "schedule_updated", name=name, state=state, ) + "\n" + "\n".join(
                f"• {value}" for value in schedule.times))
        else:
            message = text_for(lang, "schedule_empty", name=name, )

        await update.effective_message.reply_text(message)
        return

    if action == "off":
        if values:
            await update.effective_message.reply_text(
                f"{text_for(lang, 'usage_label')}:\n" + html_code("/schedule off"), parse_mode="HTML", )
            return

        current = get_profile(name).schedule

        if not current.times:
            await update.effective_message.reply_text(text_for(lang, "schedule_no_saved", name=name, ))
            return

        try:
            schedule = set_schedule(name, enabled=False, )
            await sync_timer(name, schedule)
        except RuntimeError as exc:
            await reply_error(update, exc)
            return

        await update.effective_message.reply_text(text_for(lang, "schedule_disabled", name=name, ))
        return

    if action == "on":
        if values:
            await update.effective_message.reply_text(f"{text_for(lang, 'usage_label')}:\n" +
                                                      html_code("/schedule on"), parse_mode="HTML", )
            return

        current = get_profile(name).schedule

        if not current.times:
            await update.effective_message.reply_text(text_for(lang, "schedule_no_saved_set_first", name=name, ))
            return

        try:
            schedule = set_schedule(name, enabled=True, )
            await sync_timer(name, schedule)
        except RuntimeError as exc:
            await reply_error(update, exc)
            return

        await update.effective_message.reply_text(text_for(lang, "schedule_enabled", name=name, ))
        return

    await update.effective_message.reply_text(
        text_for(
            lang,
            "unknown_schedule",
        )
        + "\n\n"
        + f"{text_for(lang, 'commands_label')}:\n"
        + html_code_lines(
            [
                "/schedule",
                "/schedule set 00:33 17:33",
                "/schedule add 12:00",
                "/schedule remove 12:00",
                "/schedule on",
                "/schedule off",
            ]
        ),
        parse_mode="HTML",
    )


@auth_required
async def task_command(update: Update, context: ContextTypes.DEFAULT_TYPE, ) -> None:
    name = current_name(context)
    lang = current_lang(name)

    try:
        _, data = load_task_json(name)
    except (FileNotFoundError, ValueError) as exc:
        await reply_error(update, exc)
        return

    mode = ("short" if not context.args else context.args[0].lower())

    if mode == "short":
        await reply_preformatted(update, name, text_for(lang, "task_title", name=name, ),
                                 short_task_sequence(data), )
        return

    if mode == "long":
        await reply_preformatted(update, name, text_for(lang, "task_long_title", name=name, ),
                                 long_task_sequence(data), )
        return

    await update.effective_message.reply_text(
        f"{text_for(lang, 'usage_label')}:\n" + html_code_lines(["/task", "/task long", ]), parse_mode="HTML", )


@auth_required
async def fight_command(update: Update, context: ContextTypes.DEFAULT_TYPE, ) -> None:
    name = current_name(context)
    lang = current_lang(name)

    try:
        path, data = load_task_json(name)
    except (FileNotFoundError, ValueError) as exc:
        await reply_error(update, exc)
        return

    if not context.args:
        await reply_preformatted(update, name, text_for(lang, "fight_title", name=name, ), fight_sequence(data), )
        return

    action = context.args[0].lower()
    values = context.args[1:]

    if action == "add":
        try:
            stage, position = parse_fight_add_args(values)
            overall_index, fight_position = (add_fight_task(data, stage, position, ))
            save_task_json(path, data)
        except (ValueError, OSError) as exc:
            await reply_error(update, exc)
            return

        await reply_preformatted(update, name, text_for(lang, "fight_added", stage=stage, task_index=overall_index,
                                                        fight_position=fight_position, ), short_task_sequence(data), )
        return

    if action == "remove":
        if len(values) != 1:
            await update.effective_message.reply_text(
                f"{text_for(lang, 'usage_label')}:\n" + html_code("/fight remove 5"), parse_mode="HTML", )
            return

        try:
            task_index = int(values[0])
        except ValueError:
            await update.effective_message.reply_text(text_for(lang, "fight_remove_index", ))
            return

        try:
            stage = remove_fight_task(data, task_index, )
            save_task_json(path, data)
        except (ValueError, OSError) as exc:
            await reply_error(update, exc)
            return

        await reply_preformatted(update, name, text_for(lang, "fight_removed", stage=stage, task_index=task_index, ),
                                 short_task_sequence(data), )
        return

    await update.effective_message.reply_text(
        text_for(lang, "unknown_fight", ) + "\n\n" + f"{text_for(lang, 'commands_label')}:\n" +
        html_code_lines(["/fight", "/fight add 1-7", "/fight add 1-7 0", "/fight remove 5", ]), parse_mode="HTML", )


@auth_required
async def log_command(update: Update, context: ContextTypes.DEFAULT_TYPE, ) -> None:
    name = current_name(context)
    lang = current_lang(name)

    if not context.args:
        mode = get_log_mode(name)

        await update.effective_message.reply_text(text_for(lang, "log_mode_title", name=name,
            mode=mode_text(lang, mode), ) + "\n\n" + f"{text_for(lang, 'commands_label')}:\n" +
            html_code_lines(["/log ON", "/log OFF", "/log FULL", ]), parse_mode="HTML", )
        return

    if len(context.args) != 1:
        await update.effective_message.reply_text(
            f"{text_for(lang, 'usage_label')}:\n" + html_code_lines(["/log", "/log ON", "/log OFF", "/log FULL", ]),
            parse_mode="HTML", )
        return

    requested = context.args[0].upper()

    if requested not in {"OFF", "ON", "FULL"}:
        await update.effective_message.reply_text(
            "❌ " + ("日志模式必须是 OFF、ON 或 FULL。" if lang == "zh" else "Log mode must be OFF, ON, or FULL."))
        return

    mode = set_log_mode(name, requested, )

    description_key = {"OFF": "log_desc_off", "ON": "log_desc_on", "FULL": "log_desc_full", }[mode]

    await update.effective_message.reply_text(
        text_for(lang, "log_mode_title", name=name, mode=mode_text(lang, mode), ) + "\n" + text_for(lang,
                                                                                                    description_key, ))


@auth_required
async def lang_command(update: Update, context: ContextTypes.DEFAULT_TYPE, ) -> None:
    name = current_name(context)
    old_lang = current_lang(name)

    if not context.args:
        await update.effective_message.reply_text(text_for(old_lang, "lang_current", name=name,
            language=language_name(old_lang), ) + "\n\n" + f"{text_for(old_lang, 'commands_label')}:\n" +
            html_code_lines(["/lang en", "/lang zh", ]), parse_mode="HTML", )
        return

    if len(context.args) != 1:
        await update.effective_message.reply_text(text_for(old_lang, "lang_invalid", ))
        return

    try:
        new_lang = normalize_language(context.args[0])
    except ValueError:
        await update.effective_message.reply_text(text_for(old_lang, "lang_invalid", ))
        return

    set_language(name, new_lang, )

    chat = update.effective_chat
    if chat is not None:
        await context.application.bot.set_my_commands(bot_commands(new_lang), scope=BotCommandScopeChat(chat.id), )

    await update.effective_message.reply_text(text_for(new_lang, "lang_changed", ),
                                              reply_markup=await control_keyboard(name), )


@auth_required
async def run_command(update: Update, context: ContextTypes.DEFAULT_TYPE, ) -> None:
    name = current_name(context)
    lang = current_lang(name)
    unit = service_unit_for(name)

    if not await unit_is_active(unit):
        result = await run_cmd("systemctl", "--user", "start", unit, )

        if result.returncode != 0:
            await update.effective_message.reply_text(
                text_for(lang, "start_failed", error=(result.stderr or result.stdout), ))
            return

    await update.effective_message.reply_text(await status_text(name), reply_markup=await control_keyboard(name), )


@auth_required
async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE, ) -> None:
    name = current_name(context)
    lang = current_lang(name)
    unit = service_unit_for(name)

    if await unit_is_active(unit):
        result = await run_cmd("systemctl", "--user", "stop", unit, )

        if result.returncode != 0:
            await update.effective_message.reply_text(
                text_for(lang, "stop_failed", error=(result.stderr or result.stdout), ))
            return

    await update.effective_message.reply_text(await status_text(name), reply_markup=await control_keyboard(name), )


@auth_required
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE, ) -> None:
    name = current_name(context)
    lang = current_lang(name)

    await update.effective_message.reply_text(
        text_for(
            lang,
            "help_title",
            name=name,
        )
        + "\n\n"
        + html_code_lines(
            [
                "/start",
                "/status",
                "/schedule",
                "/schedule set HH:MM ...",
                "/schedule add HH:MM ...",
                "/schedule remove HH:MM ...",
                "/schedule on",
                "/schedule off",
                "/task",
                "/task long",
                "/fight",
                "/fight add STAGE [POSITION]",
                "/fight remove TASK_INDEX",
                "/log",
                "/log ON",
                "/log OFF",
                "/log FULL",
                "/lang",
                "/lang en",
                "/lang zh",
                "/run",
                "/stop",
                "/help",
            ]
        ),
        parse_mode="HTML",
    )


@auth_required
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, ) -> None:
    query = update.callback_query

    if query is None:
        return

    await query.answer()

    name = current_name(context)
    lang = current_lang(name)
    action = query.data.removeprefix("maa:")

    if action == "status":
        await safe_edit_message(query, await status_text(name), reply_markup=await control_keyboard(name), )
        return

    if action == "schedule":
        await query.message.reply_text(await schedule_text(name), parse_mode="HTML", )
        return

    if action == "log_toggle":
        current = get_log_mode(name)
        new_mode = ("ON" if current == "OFF" else "OFF")

        set_log_mode(name, new_mode, )

        await safe_edit_message(query, await status_text(name), reply_markup=await control_keyboard(name), )
        return

    if action == "task":
        try:
            _, data = load_task_json(name)
        except (FileNotFoundError, ValueError,) as exc:
            await reply_error(update, exc, )
            return

        await reply_preformatted(update, name, text_for(lang, "task_title", name=name, ), short_task_sequence(data), )
        return

    if action == "run":
        unit = service_unit_for(name)

        if not await unit_is_active(unit):
            result = await run_cmd("systemctl", "--user", "start", unit, )

            if result.returncode != 0:
                await query.message.reply_text(text_for(lang, "start_failed", error=(result.stderr or result.stdout), ))
                return

        await safe_edit_message(query, await status_text(name), reply_markup=await control_keyboard(name), )
        return

    if action == "stop":
        unit = service_unit_for(name)

        if await unit_is_active(unit):
            result = await run_cmd("systemctl", "--user", "stop", unit, )

            if result.returncode != 0:
                await query.message.reply_text(text_for(lang, "stop_failed", error=(result.stderr or result.stdout), ))
                return

        await safe_edit_message(query, await status_text(name), reply_markup=await control_keyboard(name), )
        return

    if action == "schedule_off":
        current = get_profile(name).schedule

        if current.times:
            try:
                schedule = set_schedule(name, enabled=False, )
                await sync_timer(name, schedule, )
            except RuntimeError as exc:
                await reply_error(update, exc, )
                return

        await safe_edit_message(query, await status_text(name), reply_markup=await control_keyboard(name), )
        return

    if action == "schedule_on":
        current = get_profile(name).schedule

        if not current.times:
            await query.message.reply_text(text_for(lang, "schedule_no_saved", name=name, ))
            return

        try:
            schedule = set_schedule(name, enabled=True, )
            await sync_timer(name, schedule, )
        except RuntimeError as exc:
            await reply_error(update, exc, )
            return

        await safe_edit_message(query, await status_text(name), reply_markup=await control_keyboard(name), )


def register_handlers(application: Application, ) -> None:
    application.add_handler(CommandHandler(["start", "status"], start_command, ))
    application.add_handler(CommandHandler("schedule", schedule_command, ))
    application.add_handler(CommandHandler("task", task_command, ))
    application.add_handler(CommandHandler("fight", fight_command, ))
    application.add_handler(CommandHandler("log", log_command, ))
    application.add_handler(CommandHandler("lang", lang_command, ))
    application.add_handler(CommandHandler("run", run_command, ))
    application.add_handler(CommandHandler("stop", stop_command, ))
    application.add_handler(CommandHandler("help", help_command, ))
    application.add_handler(CallbackQueryHandler(button_callback, pattern=r"^maa:", ))
