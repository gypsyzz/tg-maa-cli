from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

NAME_RE = re.compile(r"^[A-Za-z0-9_-]+$")

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = Path(
    os.environ.get(
        "MAA_BOT_CONFIG",
        BASE_DIR / "telegram_config.yaml",
    )
).expanduser()

with CONFIG_PATH.open(encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f) or {}

TOKEN = str(CONFIG["TOKEN"])
TIMEZONE = str(CONFIG.get("TIMEZONE", "Asia/Singapore"))
PERSISTENT = bool(CONFIG.get("PERSISTENT", True))

SYSTEMD_USER_DIR = Path.home() / ".config" / "systemd" / "user"


def config_relative_path(key: str, default: str) -> Path:
    path = Path(CONFIG.get(key, default)).expanduser()

    if not path.is_absolute():
        path = CONFIG_PATH.parent / path

    return path


AUTHORIZED_CHATS_PATH = config_relative_path(
    "AUTHORIZED_CHATS_FILE",
    "authorized_chats.yaml",
)
PROFILES_PATH = config_relative_path(
    "PROFILES_FILE",
    "profiles.yaml",
)
MAA_TASKS_DIR = config_relative_path(
    "MAA_TASKS_DIR",
    "~/.config/maa/tasks",
)


def validate_name(name: object) -> str:
    value = str(name).strip()

    if not value or not NAME_RE.fullmatch(value):
        raise ValueError(
            f"Invalid name {value!r}; "
            "use only letters, digits, '_' and '-'."
        )

    return value


def slug_for(name: str) -> str:
    return validate_name(name).lower()


def task_for(name: str) -> str:
    return slug_for(name)


def task_file_for(name: str) -> Path:
    return MAA_TASKS_DIR / f"{task_for(name)}.json"


def service_unit_for(name: str) -> str:
    return f"maa-{slug_for(name)}.service"


def timer_unit_for(name: str) -> str:
    return f"maa-{slug_for(name)}.timer"


def timer_file_for(name: str) -> Path:
    return SYSTEMD_USER_DIR / timer_unit_for(name)


def load_authorized_chats(
    path: Path = AUTHORIZED_CHATS_PATH,
) -> tuple[dict[str, int], dict[int, str]]:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    if not isinstance(data, dict):
        raise ValueError(
            f"{path} must map names to Telegram chat IDs."
        )

    by_name: dict[str, int] = {}
    by_chat: dict[int, str] = {}
    seen_slugs: set[str] = set()

    for raw_name, raw_chat_id in data.items():
        # Allow placeholders such as:
        # profile_b:
        if raw_chat_id is None:
            continue

        name = validate_name(raw_name)
        slug = slug_for(name)

        if slug in seen_slugs:
            raise ValueError(
                f"Duplicate name after case-normalization: {name!r}"
            )

        seen_slugs.add(slug)

        try:
            chat_id = int(raw_chat_id)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                f"Invalid Telegram chat ID for {name}: "
                f"{raw_chat_id!r}"
            ) from exc

        if chat_id in by_chat:
            raise ValueError(
                f"Telegram chat ID {chat_id} is assigned to both "
                f"{by_chat[chat_id]} and {name}."
            )

        by_name[name] = chat_id
        by_chat[chat_id] = name

    if not by_name:
        raise ValueError(
            f"{path} does not contain any authorized chat IDs."
        )

    return by_name, by_chat


AUTHORIZED_BY_NAME, NAME_BY_CHAT_ID = load_authorized_chats()
