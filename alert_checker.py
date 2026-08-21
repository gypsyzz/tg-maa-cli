from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml
from telegram import Bot

from i18n import text_for
from maa_config import ALERT_STATE_PATH, service_unit_for
from profile_store import ProfileState, load_profiles
from systemd_utils import service_last_action, unit_is_active


def load_alert_state(path: Path | None = None, ) -> dict[str, str]:
    path = (path or ALERT_STATE_PATH)

    if not path.exists():
        return {}

    with path.open(encoding="utf-8") as file:
        raw = yaml.safe_load(file) or {}

    if not isinstance(raw, dict) or any(not isinstance(name, str) or not isinstance(action, str)
                                        for name, action in raw.items()):
        raise ValueError(f"{path} must map profile names to action timestamps.")

    return dict(raw)


def save_alert_state(state: dict[str, str], path: Path | None = None, ) -> None:
    path = (path or ALERT_STATE_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(yaml.safe_dump(state, allow_unicode=True, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


async def check_profile_alert(
        bot: Bot,
        name: str,
        profile: ProfileState,
        state: dict[str, str],
        *,
        now: datetime | None = None,
        state_path: Path | None = None,
) -> bool:
    if not profile.alert.enabled or await unit_is_active(service_unit_for(name)):
        return False

    action = await service_last_action(name)

    if action is None or state.get(name) == action.key:
        return False

    current_time = (now or datetime.now(timezone.utc))

    if current_time - action.timestamp < timedelta(hours=profile.alert.hours):
        return False

    await bot.send_message(chat_id=profile.chat_id, text=text_for(profile.lang, "alert_due", ))

    state[name] = action.key
    save_alert_state(state, state_path)

    return True


async def check_all_alerts(bot: Bot, *, now: datetime | None = None, state_path: Path | None = None, ) -> None:
    state = load_alert_state(state_path)

    for name, profile in load_profiles().items():
        try:
            await check_profile_alert(bot, name, profile, state, now=now, state_path=state_path)
        except Exception as exc:
            print(f"Alert check failed for {name}: {exc}", file=sys.stderr)
