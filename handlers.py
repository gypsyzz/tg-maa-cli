from __future__ import annotations

from functools import wraps

from telegram import BotCommandScopeChat, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes

from i18n import bot_commands, hours_text, language_name, mode_text, normalize_language, text_for
from maa_config import service_unit_for
from profile_store import ScheduleState, get_log_mode, get_profile, get_profile_by_chat_id, normalize_times, parse_alert_hours, resolve_profile_name, set_alert_enabled, set_alert_hours, set_language, set_log_mode, set_schedule, validate_schedule_check, validate_windows_app_control
from schedule_health_checker import CheckStatus, check_container, check_container_health, check_windows_maa, collect_failure_message, restart_container, start_windows_maa, stop_windows_maa, wait_for_windows_maa
from systemd_utils import run_cmd, sync_timer, unit_is_active
from task_store import add_fight_task, fight_sequence, load_task_json, long_task_sequence, parse_fight_add_args, remove_fight_task, save_task_json, short_task_sequence
from telegram_ui import check_timer_text, container_status_text, control_keyboard, html_code_lines, preformatted_messages, safe_edit_message, schedule_text, status_text, windows_status_text


def name_for_update(update: Update) -> str | None:
    chat = update.effective_chat

    if chat is None:
        return None

    match = get_profile_by_chat_id(chat.id)

    if match is None:
        return None

    return match[0]


def auth_required(func):
    @wraps(func)
    async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        name = name_for_update(update)

        if name is None:
            if update.callback_query:
                await update.callback_query.answer("Unauthorized", show_alert=True)
            return None

        context.user_data["maa_name"] = name

        return await func(update, context, *args, **kwargs)

    return wrapped


def current_name(context: ContextTypes.DEFAULT_TYPE) -> str:
    return str(context.user_data["maa_name"])


def current_lang(name: str) -> str:
    return get_profile(name).lang


async def reply_error(update: Update, exc: Exception) -> None:
    await update.effective_message.reply_text(f"❌ {exc}")


async def reply_usage(update: Update, lang: str, lines: list[str]) -> None:
    await update.effective_message.reply_text(f"{text_for(lang, 'usage_label')}:\n{html_code_lines(lines)}", parse_mode="HTML")


async def reply_commands(update: Update, lang: str, intro: str, lines: list[str]) -> None:
    await update.effective_message.reply_text(f"{intro}\n\n{text_for(lang, 'commands_label')}:\n{html_code_lines(lines)}", parse_mode="HTML")


async def reply_preformatted(update: Update, name: str, title: str, text: str) -> None:
    message = update.effective_message

    if message is None:
        return

    for body in preformatted_messages(title, text, text_for(current_lang(name), "continued")):
        await message.reply_text(body, parse_mode="HTML")


async def refresh_panel(query, name: str) -> None:
    await safe_edit_message(query, await status_text(name), reply_markup=await control_keyboard(name))


async def apply_schedule(update: Update, name: str, **changes) -> ScheduleState | None:
    """Save a schedule change and sync its timers. On failure the error is sent as the reply and None is returned."""
    try:
        schedule = set_schedule(name, **changes)
        await sync_timer(name, schedule)
    except (ValueError, RuntimeError) as exc:
        await reply_error(update, exc)
        return None

    return schedule


def schedule_times_text(lang: str, key: str, name: str, schedule: ScheduleState) -> str:
    state = text_for(lang, "state_on" if schedule.run_enabled else "state_off")
    return text_for(lang, key, name=name, state=state) + "\n" + "\n".join(f"• {value}" for value in schedule.times)


async def set_service_running(name: str, lang: str, running: bool) -> str | None:
    """Start or stop the profile's MAA service. Returns the localized error text when systemctl fails, otherwise None."""
    unit = service_unit_for(name)

    if await unit_is_active(unit) == running:
        return None

    result = await run_cmd("systemctl", "--user", "start" if running else "stop", unit)

    if result.returncode == 0:
        return None

    return text_for(lang, "start_failed" if running else "stop_failed", error=(result.stderr or result.stdout))


async def chat_id_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat
    message = update.effective_message

    if chat is None or message is None:
        return

    await message.reply_text(f"chat_id: {chat.id}")


@auth_required
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = current_name(context)

    await update.effective_message.reply_text(await status_text(name), reply_markup=await control_keyboard(name))


@auth_required
async def schedule_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = current_name(context)
    lang = current_lang(name)

    if not context.args:
        await update.effective_message.reply_text(await schedule_text(name), parse_mode="HTML")
        return

    action = context.args[0].lower()
    values = context.args[1:]

    if action == "set":
        if not values:
            await reply_usage(update, lang, ["/schedule set 00:33 17:33"])
            return

        schedule = await apply_schedule(update, name, times=values, run_enabled=True)

        if schedule is not None:
            await update.effective_message.reply_text(schedule_times_text(lang, "schedule_set_enabled", name, schedule))
        return

    if action == "add":
        if not values:
            await reply_usage(update, lang, ["/schedule add 12:00"])
            return

        try:
            current = get_profile(name).schedule
            times = normalize_times([*current.times, *values])
        except ValueError as exc:
            await reply_error(update, exc)
            return

        # The first saved time turns the run schedule on; later additions keep the current switches.
        run_enabled = current.run_enabled if current.times else True
        check_enabled = current.check_enabled if current.times else False
        schedule = await apply_schedule(update, name, times=times, run_enabled=run_enabled, check_enabled=check_enabled)

        if schedule is not None:
            await update.effective_message.reply_text(schedule_times_text(lang, "schedule_updated", name, schedule))
        return

    if action == "remove":
        if not values:
            await reply_usage(update, lang, ["/schedule remove 12:00"])
            return

        try:
            current = get_profile(name).schedule
            removed = set(normalize_times(values))
        except ValueError as exc:
            await reply_error(update, exc)
            return

        times = [value for value in current.times if value not in removed]
        schedule = await apply_schedule(update, name, times=times, run_enabled=current.run_enabled if times else False, check_enabled=current.check_enabled if times else False)

        if schedule is None:
            return

        if schedule.times:
            await update.effective_message.reply_text(schedule_times_text(lang, "schedule_updated", name, schedule))
        else:
            await update.effective_message.reply_text(text_for(lang, "schedule_empty", name=name))
        return

    if action in {"on", "off"}:
        if values:
            await reply_usage(update, lang, [f"/schedule {action}"])
            return

        enable = action == "on"

        if not get_profile(name).schedule.times:
            await update.effective_message.reply_text(text_for(lang, "schedule_no_saved_set_first" if enable else "schedule_no_saved", name=name))
            return

        if await apply_schedule(update, name, run_enabled=enable) is not None:
            await update.effective_message.reply_text(text_for(lang, "schedule_enabled" if enable else "schedule_disabled", name=name))
        return

    await reply_commands(update, lang, text_for(lang, "unknown_schedule"), ["/schedule", "/schedule set 00:33 17:33", "/schedule add 12:00", "/schedule remove 12:00", "/schedule on", "/schedule off"])


@auth_required
async def winmaa_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = current_name(context)
    profile = get_profile(name)
    lang = profile.lang

    if not context.args:
        lines = [text_for(lang, "check_title", name=name), await check_timer_text(name, lang)]

        try:
            state = validate_schedule_check(name, profile.schedule_check)

            if state.container_name:
                lines.append(container_status_text(lang, state.container_name, await check_container(state)))

            lines.append(windows_status_text(lang, await check_windows_maa(state)))
        except ValueError:
            lines.append(text_for(lang, "check_not_configured"))

        await update.effective_message.reply_text("\n".join(lines))
        return

    action = context.args[0].casefold()
    option = context.args[1].casefold() if len(context.args) == 2 else None

    if action == "check" and len(context.args) == 1:
        try:
            validate_schedule_check(name, profile.schedule_check)
            failure = await collect_failure_message(profile)
        except ValueError:
            await update.effective_message.reply_text(text_for(lang, "check_not_configured"))
            return

        await update.effective_message.reply_text(failure or text_for(lang, "check_healthy", name=name))
        return

    if action == "monitor" and len(context.args) == 1:
        await update.effective_message.reply_text(await check_timer_text(name, lang))
        return

    if action == "monitor" and option in {"on", "off"}:
        enable = option == "on"

        if enable and not profile.schedule.times:
            await update.effective_message.reply_text(text_for(lang, "check_no_schedule"))
            return

        if await apply_schedule(update, name, check_enabled=enable) is not None:
            await update.effective_message.reply_text(text_for(lang, "check_enabled" if enable else "check_disabled", name=name))
        return

    if action == "app" and len(context.args) == 1:
        try:
            state = validate_schedule_check(name, profile.schedule_check)
        except ValueError:
            await update.effective_message.reply_text(text_for(lang, "check_not_configured"))
            return

        await update.effective_message.reply_text(windows_status_text(lang, await check_windows_maa(state)))
        return

    if action == "app" and option in {"on", "off"}:
        try:
            state = validate_windows_app_control(name, profile.schedule_check)
        except ValueError:
            await update.effective_message.reply_text(text_for(lang, "check_app_not_configured"))
            return

        expected = CheckStatus.OK if option == "on" else CheckStatus.DOWN

        if await wait_for_windows_maa(state, expected, attempts=1, delay=0) is expected:
            await update.effective_message.reply_text(text_for(lang, "check_app_already_on" if option == "on" else "check_app_already_off"))
            return

        result = await start_windows_maa(state) if option == "on" else await stop_windows_maa(state)
        action_text = text_for(lang, f"check_app_action_{option}")

        if result.returncode != 0:
            await update.effective_message.reply_text(text_for(lang, "check_app_action_failed", action=action_text))
            return

        if await wait_for_windows_maa(state, expected, attempts=8, delay=1) is not expected:
            await update.effective_message.reply_text(text_for(lang, "check_app_action_timeout", action=action_text))
            return

        await update.effective_message.reply_text(text_for(lang, "check_app_turned_on" if option == "on" else "check_app_turned_off"))
        return

    await reply_commands(update, lang, text_for(lang, "unknown_check"), ["/winmaa", "/winmaa check", "/winmaa monitor", "/winmaa monitor on", "/winmaa monitor off", "/winmaa app", "/winmaa app on", "/winmaa app off"])


@auth_required
async def container_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    profile = get_profile(current_name(context))
    lang = profile.lang

    if len(context.args) != 1 or context.args[0].casefold() not in {"restart", "health"}:
        await reply_usage(update, lang, ["/container health", "/container restart"])
        return

    action = context.args[0].casefold()
    state = profile.schedule_check

    if not state.container_name:
        await update.effective_message.reply_text(text_for(lang, "container_not_configured"))
        return

    if action == "restart":
        await update.effective_message.reply_text(text_for(lang, "container_restarting", container_name=state.container_name))
        result = await restart_container(state)
    else:
        result = await check_container_health(state)

    if result.returncode != 0:
        await update.effective_message.reply_text(text_for(lang, f"container_{action}_failed", container_name=state.container_name, error=(result.stderr or result.stdout or f"exit status {result.returncode}")[:2500]))
        return

    await update.effective_message.reply_text(text_for(lang, "container_restarted" if action == "restart" else "container_healthy", container_name=state.container_name))


@auth_required
async def task_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = current_name(context)
    lang = current_lang(name)

    try:
        _, data = load_task_json(name)
    except (FileNotFoundError, ValueError) as exc:
        await reply_error(update, exc)
        return

    mode = "short" if not context.args else context.args[0].lower()

    if mode == "short":
        await reply_preformatted(update, name, text_for(lang, "task_title", name=name), short_task_sequence(data))
        return

    if mode == "long":
        await reply_preformatted(update, name, text_for(lang, "task_long_title", name=name), long_task_sequence(data))
        return

    await reply_usage(update, lang, ["/task", "/task long"])


@auth_required
async def fight_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = current_name(context)
    lang = current_lang(name)

    try:
        path, data = load_task_json(name)
    except (FileNotFoundError, ValueError) as exc:
        await reply_error(update, exc)
        return

    if not context.args:
        await reply_preformatted(update, name, text_for(lang, "fight_title", name=name), fight_sequence(data))
        return

    action = context.args[0].lower()
    values = context.args[1:]

    if action == "add":
        try:
            stage, position = parse_fight_add_args(values)
            overall_index = add_fight_task(data, stage, position)
            save_task_json(path, data)
        except (ValueError, OSError) as exc:
            await reply_error(update, exc)
            return

        await reply_preformatted(update, name, text_for(lang, "fight_added", stage=stage, task_index=overall_index), short_task_sequence(data))
        return

    if action == "remove":
        if len(values) != 1:
            await reply_usage(update, lang, ["/fight remove 5"])
            return

        try:
            task_index = int(values[0])
        except ValueError:
            await update.effective_message.reply_text(text_for(lang, "fight_remove_index"))
            return

        try:
            stage = remove_fight_task(data, task_index)
            save_task_json(path, data)
        except (ValueError, OSError) as exc:
            await reply_error(update, exc)
            return

        await reply_preformatted(update, name, text_for(lang, "fight_removed", stage=stage, task_index=task_index), short_task_sequence(data))
        return

    await reply_commands(update, lang, text_for(lang, "unknown_fight"), ["/fight", "/fight add 1-7", "/fight add 1-7 5", "/fight remove 5"])


@auth_required
async def log_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = current_name(context)
    lang = current_lang(name)

    if not context.args:
        await reply_commands(update, lang, text_for(lang, "log_mode_title", name=name, mode=mode_text(lang, get_log_mode(name))), ["/log ON", "/log OFF", "/log FULL"])
        return

    if len(context.args) != 1:
        await reply_usage(update, lang, ["/log", "/log ON", "/log OFF", "/log FULL"])
        return

    try:
        mode = set_log_mode(name, context.args[0])
    except ValueError:
        await update.effective_message.reply_text(text_for(lang, "log_mode_invalid"))
        return

    await update.effective_message.reply_text(text_for(lang, "log_mode_title", name=name, mode=mode_text(lang, mode)) + "\n" + text_for(lang, f"log_desc_{mode.lower()}"))


@auth_required
async def alert_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = current_name(context)
    profile = get_profile(name)
    lang = profile.lang

    if not context.args:
        state = text_for(lang, "state_on" if profile.alert.enabled else "state_off")
        await reply_commands(update, lang, text_for(lang, "alert_status", name=name, state=state, duration=hours_text(lang, profile.alert.hours)), ["/alert on", "/alert off", "/alert time 24"])
        return

    action = context.args[0].lower()

    if action in {"on", "off"} and len(context.args) == 1:
        alert = set_alert_enabled(name, action == "on")
        await update.effective_message.reply_text(text_for(lang, "alert_enabled" if alert.enabled else "alert_disabled", name=name, duration=hours_text(lang, alert.hours)))
        return

    if action == "time" and len(context.args) == 2:
        try:
            hours = parse_alert_hours(context.args[1])
        except ValueError:
            await update.effective_message.reply_text(text_for(lang, "alert_invalid_time"))
            return

        alert = set_alert_hours(name, hours)
        await update.effective_message.reply_text(text_for(lang, "alert_time_set", name=name, duration=hours_text(lang, alert.hours)))
        return

    await reply_usage(update, lang, ["/alert", "/alert on", "/alert off", "/alert time 24"])


@auth_required
async def lang_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = current_name(context)
    old_lang = current_lang(name)

    if not context.args:
        await reply_commands(update, old_lang, text_for(old_lang, "lang_current", name=name, language=language_name(old_lang)), ["/lang en", "/lang zh"])
        return

    if len(context.args) != 1:
        await update.effective_message.reply_text(text_for(old_lang, "lang_invalid"))
        return

    try:
        new_lang = normalize_language(context.args[0])
    except ValueError:
        await update.effective_message.reply_text(text_for(old_lang, "lang_invalid"))
        return

    set_language(name, new_lang)

    chat = update.effective_chat
    if chat is not None:
        await context.application.bot.set_my_commands(bot_commands(new_lang), scope=BotCommandScopeChat(chat.id))

    await update.effective_message.reply_text(text_for(new_lang, "lang_changed"))
    await update.effective_message.reply_text(await status_text(name), reply_markup=await control_keyboard(name))


async def toggle_service_command(update: Update, context: ContextTypes.DEFAULT_TYPE, *, running: bool) -> None:
    name = current_name(context)
    error = await set_service_running(name, current_lang(name), running)

    if error is not None:
        await update.effective_message.reply_text(error)
        return

    # A delegated /sudo run or stop replies with plain status text instead of the target's control panel.
    reply_markup = None if context.user_data.get("maa_sudo_target") else await control_keyboard(name)
    await update.effective_message.reply_text(await status_text(name), reply_markup=reply_markup)


@auth_required
async def run_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await toggle_service_command(update, context, running=True)


@auth_required
async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await toggle_service_command(update, context, running=False)


@auth_required
async def sudo_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    caller_name = current_name(context)
    caller_profile = get_profile(caller_name)
    caller_lang = caller_profile.lang
    user = update.effective_user

    if not caller_profile.admin or user is None or user.id != caller_profile.chat_id:
        await update.effective_message.reply_text(text_for(caller_lang, "sudo_denied"))
        return

    if len(context.args) < 2:
        await reply_usage(update, caller_lang, ["/sudo PROFILE COMMAND [ARGS ...]"])
        return

    try:
        target_name = resolve_profile_name(context.args[0])
    except ValueError as exc:
        await reply_error(update, exc)
        return

    command = context.args[1].casefold()
    delegated_handlers = {"fight": fight_command, "schedule": schedule_command, "winmaa": winmaa_command, "container": container_command, "run": run_command, "stop": stop_command}
    handler = delegated_handlers.get(command)

    if handler is None:
        await update.effective_message.reply_text(text_for(caller_lang, "sudo_not_allowed", command=command))
        return

    original_name = context.user_data.get("maa_name")
    original_args = context.args
    had_sudo_target = "maa_sudo_target" in context.user_data
    original_sudo_target = context.user_data.get("maa_sudo_target")

    try:
        context.user_data["maa_name"] = target_name
        context.user_data["maa_sudo_target"] = target_name
        context.args = context.args[2:]
        await handler.__wrapped__(update, context)
    finally:
        context.args = original_args

        if original_name is None:
            context.user_data.pop("maa_name", None)
        else:
            context.user_data["maa_name"] = original_name

        if had_sudo_target:
            context.user_data["maa_sudo_target"] = original_sudo_target
        else:
            context.user_data.pop("maa_sudo_target", None)


@auth_required
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    name = current_name(context)
    lang = current_lang(name)

    await update.effective_message.reply_text(
        text_for(lang, "help_title", name=name)
        + "\n\n"
        + html_code_lines(
            [
                "/start",
                "/status",
                "/chat_id",
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
                "/alert",
                "/alert on",
                "/alert off",
                "/alert time 24",
                "/winmaa",
                "/winmaa check",
                "/winmaa monitor",
                "/winmaa monitor on",
                "/winmaa monitor off",
                "/winmaa app",
                "/winmaa app on",
                "/winmaa app off",
                "/container restart",
                "/container health",
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
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query

    if query is None:
        return

    await query.answer()

    name = current_name(context)
    lang = current_lang(name)
    action = query.data.removeprefix("maa:")

    if action == "status":
        await refresh_panel(query, name)
        return

    if action == "schedule":
        await query.message.reply_text(await schedule_text(name), parse_mode="HTML")
        return

    if action == "log_toggle":
        set_log_mode(name, "ON" if get_log_mode(name) == "OFF" else "OFF")
        await refresh_panel(query, name)
        return

    if action == "task":
        try:
            _, data = load_task_json(name)
        except (FileNotFoundError, ValueError) as exc:
            await reply_error(update, exc)
            return

        await reply_preformatted(update, name, text_for(lang, "task_title", name=name), short_task_sequence(data))
        return

    if action in {"run", "stop"}:
        error = await set_service_running(name, lang, action == "run")

        if error is not None:
            await query.message.reply_text(error)
            return

        await refresh_panel(query, name)
        return

    if action in {"schedule_on", "schedule_off"}:
        enable = action == "schedule_on"
        has_times = bool(get_profile(name).schedule.times)

        if enable and not has_times:
            await query.message.reply_text(text_for(lang, "schedule_no_saved", name=name))
            return

        # Turning the schedule off without saved times is a no-op; the panel is still refreshed.
        if has_times and await apply_schedule(update, name, run_enabled=enable) is None:
            return

        await refresh_panel(query, name)


def register_handlers(application: Application) -> None:
    application.add_handler(CommandHandler(["start", "status"], start_command))
    application.add_handler(CommandHandler("chat_id", chat_id_command))
    application.add_handler(CommandHandler("schedule", schedule_command))
    application.add_handler(CommandHandler("task", task_command))
    application.add_handler(CommandHandler("fight", fight_command))
    application.add_handler(CommandHandler("log", log_command))
    application.add_handler(CommandHandler("alert", alert_command))
    application.add_handler(CommandHandler("winmaa", winmaa_command))
    application.add_handler(CommandHandler("container", container_command))
    application.add_handler(CommandHandler("lang", lang_command))
    application.add_handler(CommandHandler("run", run_command))
    application.add_handler(CommandHandler("stop", stop_command))
    application.add_handler(CommandHandler("sudo", sudo_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CallbackQueryHandler(button_callback, pattern=r"^maa:"))
