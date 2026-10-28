from __future__ import annotations

from telegram import BotCommand

SUPPORTED_LANGUAGES = {"en", "zh"}

# fmt: off
TEXT = {
    "en": {
        "button_status": "📊 Status",
        "button_schedule": "🕒 Schedule",
        "button_stop_run": "⏹ Stop run",
        "button_run_now": "▶️ Run now",
        "button_log": "📜 Log: {mode}",
        "button_task": "📋 Task",
        "button_schedule_off": "⏸ Schedule OFF",
        "button_schedule_on": "▶️ Schedule ON",

        "run_label": "Run",
        "schedule_label": "Schedule",
        "run_schedule_label": "Run schedule",
        "check_schedule_label": "Check schedule",
        "next_run_label": "Next run",
        "last_result_label": "Last result",
        "state_label": "State",
        "timezone_label": "Timezone",
        "commands_label": "Commands",
        "usage_label": "Usage",

        "state_on": "🟢 ON",
        "state_off": "🟠 OFF",
        "schedule_saved": "🟠 OFF ({count} schedule{plural})",

        "no_saved_schedule": "No saved schedule.",
        "no_auto_run": "This name will not run automatically.",

        "schedule_title": "🕒 {name} schedule",
        "schedule_set_enabled": "✅ {name} schedule set and enabled",
        "schedule_updated": "✅ {name} schedule updated ({state})",
        "schedule_empty": "⏸ {name} has no saved schedule now.\nIt will not run automatically.",
        "schedule_no_saved": "ℹ️ {name} has no saved schedule.",
        "schedule_no_saved_set_first": "ℹ️ {name} has no saved schedule.\nUse /schedule set first.",
        "schedule_disabled": "⏸ {name} schedule disabled.\nSaved times were kept.",
        "schedule_enabled": "▶️ {name} schedule enabled.",
        "unknown_schedule": "Unknown schedule command.",

        "task_title": "📋 {name} task sequence",
        "task_long_title": "📋 {name} task sequence - long",

        "fight_title": "⚔️ {name} Fight stages",
        "fight_added": "✅ Added Fight - {stage} at overall task position {task_index}",
        "fight_removed": "✅ Removed Fight - {stage} from task {task_index}",
        "fight_remove_index": "❌ Fight removal requires the overall numeric task index.",
        "unknown_fight": "Unknown fight command.",

        "log_mode_title": "📜 {name} log mode: {mode}",
        "log_desc_off": "automatic log messages disabled",
        "log_desc_on": "send MAA task and process errors only",
        "log_desc_full": "send every MAA task result plus process errors",

        "alert_status": "🔔 {name} game reminder\nState: {state}\nTime: {duration}",
        "alert_enabled": "🔔 {name} game reminder enabled after {duration}.",
        "alert_disabled": "🔕 {name} game reminder disabled.",
        "alert_time_set": "✅ {name} game reminder time set to {duration}.",
        "alert_invalid_time": "❌ Time must be a positive whole number of hours, e.g. /alert time 24.",
        "alert_due": "Last MAA run was over {threshold} hours. Did you forget to turn on scheduler?",
        "check_title": "🔎 {name} MAA readiness status",
        "check_enabled": "🔎 {name} repeating readiness check enabled.",
        "check_disabled": "🔎 {name} repeating readiness check disabled.",
        "check_healthy": "✅ Check result: all monitored services are ready.",
        "check_result_failed": "❌ Check result: {result}.",
        "check_result_container": "container {container_name} {container_state}",
        "check_result_container_ok": "is healthy",
        "check_result_container_down": "is not ready",
        "check_result_container_error": "status could not be checked",
        "check_result_windows": "Windows MAA {maa_state}",
        "check_result_maa_ok": "is open",
        "check_result_maa_down": "is closed",
        "check_result_maa_error": "status could not be checked",
        "check_no_schedule": "No saved schedule times. Use /schedule set first.",
        "check_not_configured": "The Windows SSH target is not configured for this profile.",
        "check_app_not_configured": "The exact Windows MAA path and interactive start task are not configured for this profile.",
        "check_timer_label": "Monitor timer",
        "check_timer_active": "🟢 ACTIVE",
        "check_timer_inactive": "🟠 INACTIVE",
        "check_container_status": "Container {container_name}: {status}",
        "check_container_ok": "✅ HEALTHY",
        "check_container_down": "❌ NOT READY",
        "check_container_error": "⚠️ CHECK ERROR",
        "check_windows_status": "Windows MAA: {status}",
        "check_windows_ok": "✅ OPEN",
        "check_windows_down": "❌ CLOSED",
        "check_windows_error": "⚠️ CHECK ERROR",
        "check_app_already_on": "ℹ️ Windows MAA is already open.",
        "check_app_already_off": "ℹ️ Windows MAA is already closed.",
        "check_app_action_on": "start",
        "check_app_action_off": "stop",
        "check_app_action_failed": "❌ Could not {action} Windows MAA.",
        "check_app_action_timeout": "❌ Windows accepted the {action} request, but MAA did not reach the expected state.",
        "check_app_turned_on": "✅ Windows MAA is open.",
        "check_app_turned_off": "✅ Windows MAA is closed.",
        "unknown_check": "Unknown winmaa command.",
        "container_not_configured": "No container is configured for this profile (schedule_check.container_name).",
        "container_restarting": "Restarting {container_name}; waiting for Android to boot…",
        "container_restarted": "✅ {container_name} restarted. Android has booted and Bluetooth is disabled.",
        "container_restart_failed": "❌ Could not finish restarting {container_name}:\n{error}",
        "container_healthy": "✅ {container_name}: running, Android booted, ADB responding.",
        "container_health_failed": "❌ {container_name} health check failed:\n{error}",
        "hour_one": "hour",
        "hour_many": "hours",

        "start_failed": "❌ Start failed:\n{error}",
        "stop_failed": "❌ Stop failed:\n{error}",

        "sudo_denied": "❌ Admin access denied. The configured admin profile and Telegram user ID must both match.",
        "sudo_not_allowed": "❌ /sudo does not allow the {command} command. Allowed: fight, schedule, winmaa, container, run, stop.",

        "help_title": "MAA {name} commands",
        "continued": "continued",

        "lang_current": "🌐 {name} language: {language}",
        "lang_changed": "🌐 Language changed to English.",
        "lang_invalid": "Supported languages: en, zh",
        "language_en": "English",
        "language_zh": "中文",

        "full_log_title": "📜 {name} full run log",
        "incomplete_log_title": "⚠️ {name} incomplete task log",
        "program_error_title": "❌ MAA {name} process failed",
        "program_error_result": "Systemd result: {result}",
        "program_error_status": "Process status: {status}",

        "unauthorized": "Unauthorized",

        "result_success": "success",
        "result_exit-code": "exit-code",
        "result_signal": "signal",
        "result_timeout": "timeout",
        "result_core-dump": "core-dump",
        "result_n/a": "n/a",

        "cmd_start": "Open control panel",
        "cmd_status": "Show current status",
        "cmd_chat_id": "Show this chat's ID",
        "cmd_schedule": "View or edit schedule",
        "cmd_task": "Show task sequence",
        "cmd_fight": "View or edit Fight stages",
        "cmd_log": "Set automatic log mode",
        "cmd_alert": "Set game inactivity reminder",
        "cmd_winmaa": "Control or run Windows MAA checks",
        "cmd_container": "Check or restart your Android container",
        "cmd_lang": "Change UI language",
        "cmd_run": "Run MAA now",
        "cmd_stop": "Stop current MAA run",
        "cmd_help": "Show command help",
    },

    "zh": {
        "button_status": "📊 当前状态",
        "button_schedule": "🕒 定时计划",
        "button_stop_run": "⏹ 停止运行",
        "button_run_now": "▶️ 立即运行",
        "button_log": "📜 日志: {mode}",
        "button_task": "📋 任务",
        "button_schedule_off": "⏸ 关闭定时",
        "button_schedule_on": "▶️ 开启定时",

        "run_label": "运行",
        "schedule_label": "定时",
        "run_schedule_label": "运行定时",
        "check_schedule_label": "检查定时",
        "next_run_label": "下次运行",
        "last_result_label": "上次结果",
        "state_label": "状态",
        "timezone_label": "时区",
        "commands_label": "命令",
        "usage_label": "用法",

        "state_on": "🟢 开启",
        "state_off": "🟠 关闭",
        "schedule_saved": "🟠 关闭（已保存 {count} 个定时）",

        "no_saved_schedule": "没有已保存的定时计划。",
        "no_auto_run": "此配置不会自动运行。",

        "schedule_title": "🕒 {name} 定时运行",
        "schedule_set_enabled": "✅ {name} 定时已设置并开启",
        "schedule_updated": "✅ {name} 定时已更新（{state}）",
        "schedule_empty": "⏸ {name} 当前没有已保存的定时时间。\n不会自动运行。",
        "schedule_no_saved": "ℹ️ {name} 没有已保存的定时时间。",
        "schedule_no_saved_set_first": "ℹ️ {name} 没有已保存的定时时间。\n请先使用 /schedule set。",
        "schedule_disabled": "⏸ {name} 定时已关闭。\n已保存的时间不会删除。",
        "schedule_enabled": "▶️ {name} 定时已开启。",
        "unknown_schedule": "未知的 schedule 子命令。",

        "task_title": "📋 {name} 任务序列",
        "task_long_title": "📋 {name} 任务序列 - 详细",

        "fight_title": "⚔️ {name} 作战关卡",
        "fight_added": "✅ 已添加作战关卡 {stage}，总任务位置 {task_index}",
        "fight_removed": "✅ 已从总任务位置 {task_index} 删除作战关卡 {stage}",
        "fight_remove_index": "❌ 删除作战任务需要填写总任务序列中的数字索引。",
        "unknown_fight": "未知的 fight 子命令。",

        "log_mode_title": "📜 {name} 日志模式: {mode}",
        "log_desc_off": "自动日志消息已关闭",
        "log_desc_on": "仅发送 MAA 任务错误和进程级错误",
        "log_desc_full": "发送所有 MAA 任务结果和进程级错误",

        "alert_status": "🔔 {name} 游戏提醒\n状态: {state}\n时限: {duration}",
        "alert_enabled": "🔔 {name} 游戏提醒已开启，时限为 {duration}。",
        "alert_disabled": "🔕 {name} 游戏提醒已关闭。",
        "alert_time_set": "✅ {name} 游戏提醒时限已设为 {duration}。",
        "alert_invalid_time": "❌ 时限必须是正整数小时，例如 /alert time 24。",
        "alert_due": "上次运行 MAA 已超过 {threshold} 小时。您是否忘记开启定时计划了？",
        "check_title": "🔎 {name} MAA 就绪状态",
        "check_enabled": "🔎 {name} 重复就绪检查已开启。",
        "check_disabled": "🔎 {name} 重复就绪检查已关闭。",
        "check_healthy": "✅ 检查结果：所有监控服务均已就绪。",
        "check_result_failed": "❌ 检查结果：{result}。",
        "check_result_container": "容器 {container_name} {container_state}",
        "check_result_container_ok": "健康",
        "check_result_container_down": "未就绪",
        "check_result_container_error": "状态无法检查",
        "check_result_windows": "Windows MAA {maa_state}",
        "check_result_maa_ok": "已打开",
        "check_result_maa_down": "已关闭",
        "check_result_maa_error": "状态无法检查",
        "check_no_schedule": "没有已保存的定时时间。请先使用 /schedule set。",
        "check_not_configured": "此配置尚未设置 Windows SSH 目标。",
        "check_app_not_configured": "此配置尚未设置 Windows MAA 的准确路径和交互式启动任务。",
        "check_timer_label": "检查定时器",
        "check_timer_active": "🟢 运行中",
        "check_timer_inactive": "🟠 未运行",
        "check_container_status": "容器 {container_name}：{status}",
        "check_container_ok": "✅ 健康",
        "check_container_down": "❌ 未就绪",
        "check_container_error": "⚠️ 检查错误",
        "check_windows_status": "Windows MAA：{status}",
        "check_windows_ok": "✅ 已打开",
        "check_windows_down": "❌ 已关闭",
        "check_windows_error": "⚠️ 检查错误",
        "check_app_already_on": "ℹ️ Windows MAA 已经打开。",
        "check_app_already_off": "ℹ️ Windows MAA 已经关闭。",
        "check_app_action_on": "启动",
        "check_app_action_off": "停止",
        "check_app_action_failed": "❌ 无法{action} Windows MAA。",
        "check_app_action_timeout": "❌ Windows 已接受{action}请求，但 MAA 未进入预期状态。",
        "check_app_turned_on": "✅ Windows MAA 已打开。",
        "check_app_turned_off": "✅ Windows MAA 已关闭。",
        "unknown_check": "未知的 winmaa 子命令。",
        "container_not_configured": "此配置尚未设置容器（schedule_check.container_name）。",
        "container_restarting": "正在重启 {container_name}，等待 Android 启动…",
        "container_restarted": "✅ {container_name} 已重启，Android 已启动，蓝牙已关闭。",
        "container_restart_failed": "❌ 未能完成 {container_name} 的重启：\n{error}",
        "container_healthy": "✅ {container_name}：容器运行中，Android 已启动，ADB 响应正常。",
        "container_health_failed": "❌ {container_name} 健康检查失败：\n{error}",
        "hour_one": "小时",
        "hour_many": "小时",

        "start_failed": "❌ 启动失败:\n{error}",
        "stop_failed": "❌ 停止失败:\n{error}",

        "sudo_denied": "❌ 管理员权限被拒绝。管理员配置和 Telegram 用户 ID 必须同时匹配。",
        "sudo_not_allowed": "❌ /sudo 不允许执行 {command} 命令。允许的命令：fight、schedule、winmaa、container、run、stop。",

        "help_title": "MAA {name} 命令",
        "continued": "继续",

        "lang_current": "🌐 {name} 当前语言: {language}",
        "lang_changed": "🌐 语言已切换为中文。",
        "lang_invalid": "支持的语言: en, zh",
        "language_en": "English",
        "language_zh": "中文",

        "full_log_title": "📜 {name} 完整运行日志",
        "incomplete_log_title": "⚠️ {name} 未完成任务日志",
        "program_error_title": "❌ MAA {name} 进程运行失败",
        "program_error_result": "Systemd 结果：{result}",
        "program_error_status": "进程状态：{status}",

        "unauthorized": "未授权",

        "result_success": "成功",
        "result_exit-code": "退出码错误",
        "result_signal": "信号终止",
        "result_timeout": "超时",
        "result_core-dump": "崩溃",
        "result_n/a": "无",

        "cmd_start": "打开控制面板",
        "cmd_status": "查看当前状态",
        "cmd_chat_id": "显示当前聊天 ID",
        "cmd_schedule": "查看或修改定时计划",
        "cmd_task": "查看任务序列",
        "cmd_fight": "查看或修改作战关卡",
        "cmd_log": "设置自动日志模式",
        "cmd_alert": "设置游戏未运行提醒",
        "cmd_winmaa": "控制或立即运行 Windows MAA 检查",
        "cmd_container": "检查或重启自己的 Android 容器",
        "cmd_lang": "切换界面语言",
        "cmd_run": "立即运行 MAA",
        "cmd_stop": "停止当前 MAA 运行",
        "cmd_help": "查看命令帮助",
    },
}
# fmt: on


def normalize_language(value: object) -> str:
    raw = str(value or "en").strip().lower()

    aliases = {"en": "en", "english": "en", "zh": "zh", "zh-cn": "zh", "cn": "zh", "chinese": "zh", "中文": "zh"}

    if raw not in aliases:
        raise ValueError("Supported languages: en, zh")

    return aliases[raw]


def text_for(language: str, key: str, **kwargs) -> str:
    language = normalize_language(language)
    template = TEXT[language].get(key, TEXT["en"].get(key, key))
    return template.format(**kwargs)


def mode_text(language: str, mode: str) -> str:
    mode = mode.upper()

    if language == "zh":
        return {"OFF": "关闭", "ON": "开启", "FULL": "完整"}.get(mode, mode)

    return mode


def hours_text(language: str, hours: int) -> str:
    key = "hour_one" if hours == 1 else "hour_many"
    return f"{hours} {text_for(language, key)}"


def result_text(language: str, result: str) -> str:
    key = f"result_{result}"
    return TEXT[normalize_language(language)].get(key, result)


def language_name(language: str) -> str:
    language = normalize_language(language)
    return TEXT[language][f"language_{language}"]


def bot_commands(language: str) -> list[BotCommand]:
    language = normalize_language(language)

    return [
        BotCommand("start", text_for(language, "cmd_start")),
        BotCommand("status", text_for(language, "cmd_status")),
        BotCommand("chat_id", text_for(language, "cmd_chat_id")),
        BotCommand("schedule", text_for(language, "cmd_schedule")),
        BotCommand("task", text_for(language, "cmd_task")),
        BotCommand("fight", text_for(language, "cmd_fight")),
        BotCommand("log", text_for(language, "cmd_log")),
        BotCommand("alert", text_for(language, "cmd_alert")),
        BotCommand("winmaa", text_for(language, "cmd_winmaa")),
        BotCommand("container", text_for(language, "cmd_container")),
        BotCommand("lang", text_for(language, "cmd_lang")),
        BotCommand("run", text_for(language, "cmd_run")),
        BotCommand("stop", text_for(language, "cmd_stop")),
        BotCommand("help", text_for(language, "cmd_help")),
    ]
