from __future__ import annotations

from telegram import BotCommand

SUPPORTED_LANGUAGES = {"en", "zh"}

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
        "fight_added": "✅ Added Fight - {stage} at task {task_index} (Fight position {fight_position})",
        "fight_removed": "✅ Removed Fight - {stage} from task {task_index}",
        "fight_remove_index": "❌ Fight removal requires the overall numeric task index.",
        "unknown_fight": "Unknown fight command.",

        "log_mode_title": "📜 {name} log mode: {mode}",
        "log_desc_off": "automatic log messages disabled",
        "log_desc_on": "send only explicitly non-Completed MAA subtask summaries",
        "log_desc_full": "send log after each MAA subtask finishes",

        "start_failed": "❌ Start failed:\n{error}",
        "stop_failed": "❌ Stop failed:\n{error}",

        "help_title": "MAA {name} commands",
        "continued": "continued",

        "lang_current": "🌐 {name} language: {language}",
        "lang_changed": "🌐 Language changed to English.",
        "lang_invalid": "Supported languages: en, zh",
        "language_en": "English",
        "language_zh": "中文",

        "full_log_title": "📜 {name} full run log",
        "incomplete_log_title": "⚠️ {name} incomplete task log",

        "unauthorized": "Unauthorized",

        "result_success": "success",
        "result_exit-code": "exit-code",
        "result_signal": "signal",
        "result_timeout": "timeout",
        "result_core-dump": "core-dump",
        "result_n/a": "n/a",

        "cmd_start": "Open control panel",
        "cmd_status": "Show current status",
        "cmd_schedule": "View or edit schedule",
        "cmd_task": "Show task sequence",
        "cmd_fight": "View or edit Fight stages",
        "cmd_log": "Set automatic log mode",
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
        "fight_added": "✅ 已添加作战关卡 {stage}，总任务位置 {task_index}（作战位置 {fight_position}）",
        "fight_removed": "✅ 已从总任务位置 {task_index} 删除作战关卡 {stage}",
        "fight_remove_index": "❌ 删除作战任务需要填写总任务序列中的数字索引。",
        "unknown_fight": "未知的 fight 子命令。",

        "log_mode_title": "📜 {name} 日志模式: {mode}",
        "log_desc_off": "自动日志消息已关闭",
        "log_desc_on": "仅当 MAA 明确报告子任务状态不是 Completed 时发送",
        "log_desc_full": "每个 MAA 子任务结束后发送运行结果",

        "start_failed": "❌ 启动失败:\n{error}",
        "stop_failed": "❌ 停止失败:\n{error}",

        "help_title": "MAA {name} 命令",
        "continued": "继续",

        "lang_current": "🌐 {name} 当前语言: {language}",
        "lang_changed": "🌐 语言已切换为中文。",
        "lang_invalid": "支持的语言: en, zh",
        "language_en": "English",
        "language_zh": "中文",

        "full_log_title": "📜 {name} 完整运行日志",
        "incomplete_log_title": "⚠️ {name} 未完成任务日志",

        "unauthorized": "未授权",

        "result_success": "成功",
        "result_exit-code": "退出码错误",
        "result_signal": "信号终止",
        "result_timeout": "超时",
        "result_core-dump": "崩溃",
        "result_n/a": "无",

        "cmd_start": "打开控制面板",
        "cmd_status": "查看当前状态",
        "cmd_schedule": "查看或修改定时计划",
        "cmd_task": "查看任务序列",
        "cmd_fight": "查看或修改作战关卡",
        "cmd_log": "设置自动日志模式",
        "cmd_lang": "切换界面语言",
        "cmd_run": "立即运行 MAA",
        "cmd_stop": "停止当前 MAA 运行",
        "cmd_help": "查看命令帮助",
    },
}


def normalize_language(value: object) -> str:
    raw = str(value or "en").strip().lower()

    aliases = {"en": "en", "english": "en", "zh": "zh", "zh-cn": "zh", "cn": "zh", "chinese": "zh", "中文": "zh", }

    if raw not in aliases:
        raise ValueError("Supported languages: en, zh")

    return aliases[raw]


def text_for(language: str, key: str, **kwargs, ) -> str:
    language = normalize_language(language)
    template = TEXT[language].get(key, TEXT["en"].get(key, key), )
    return template.format(**kwargs)


def mode_text(language: str, mode: str, ) -> str:
    mode = mode.upper()

    if language == "zh":
        return {"OFF": "关闭", "ON": "开启", "FULL": "完整", }.get(mode, mode)

    return mode


def result_text(language: str, result: str, ) -> str:
    key = f"result_{result}"
    return TEXT[normalize_language(language)].get(key, result, )


def language_name(language: str, ) -> str:
    language = normalize_language(language)
    return TEXT[language][f"language_{language}"]


def bot_commands(language: str, ) -> list[BotCommand]:
    language = normalize_language(language)

    return [
        BotCommand("start", text_for(language, "cmd_start")),
        BotCommand("status", text_for(language, "cmd_status")),
        BotCommand("schedule", text_for(language, "cmd_schedule")),
        BotCommand("task", text_for(language, "cmd_task")),
        BotCommand("fight", text_for(language, "cmd_fight")),
        BotCommand("log", text_for(language, "cmd_log")),
        BotCommand("lang", text_for(language, "cmd_lang")),
        BotCommand("run", text_for(language, "cmd_run")),
        BotCommand("stop", text_for(language, "cmd_stop")),
        BotCommand("help", text_for(language, "cmd_help")),
    ]
