from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

import yaml

from i18n import normalize_language
from maa_config import PROFILES_PATH, slug_for, validate_name

TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
LOG_MODES = {"OFF", "ON", "FULL"}


@dataclass
class ScheduleState:
    enabled: bool
    times: list[str]


@dataclass
class ProfileState:
    chat_id: int
    schedule: ScheduleState
    log: str
    lang: str


def normalize_times(values: Iterable[object]) -> list[str]:
    times: list[str] = []

    for raw in values:
        value = str(raw).strip()

        if not TIME_RE.fullmatch(value):
            raise ValueError(f"Invalid time {value!r}; use HH:MM, e.g. 06:33.")

        if value not in times:
            times.append(value)

    return sorted(times, key=lambda value: tuple(map(int, value.split(":"))))


def normalize_chat_id(value: object, *, name: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{PROFILES_PATH}: {name}.chat_id must be an integer.")

    if value == 0:
        raise ValueError(f"{PROFILES_PATH}: {name}.chat_id cannot be 0.")

    return value


def ensure_unique_slugs(names: Iterable[object]) -> None:
    seen: dict[str, str] = {}

    for raw_name in names:
        name = validate_name(raw_name)
        slug = slug_for(name)
        existing_name = seen.get(slug)

        if existing_name is not None:
            raise ValueError(
                f"{PROFILES_PATH}: profile names {existing_name!r} and {name!r} "
                f"produce the same slug {slug!r}."
            )

        seen[slug] = name


def parse_profile(name: str, raw: object) -> ProfileState:
    if not isinstance(raw, dict):
        raise ValueError(f"{PROFILES_PATH}: {name} must be a mapping.")

    if "chat_id" not in raw:
        raise ValueError(f"{PROFILES_PATH}: {name}.chat_id is required.")

    chat_id = normalize_chat_id(raw["chat_id"], name=name)

    raw_schedule = raw.get("schedule")

    if raw_schedule is None:
        schedule = ScheduleState(enabled=False, times=[])

    elif isinstance(raw_schedule, dict):
        if "enable" in raw_schedule and "enabled" not in raw_schedule:
            raise ValueError(f"{PROFILES_PATH}: {name}.schedule uses 'enable'; use 'enabled' instead.")

        raw_times = raw_schedule.get("times") or []

        if not isinstance(raw_times, list):
            raise ValueError(f"{PROFILES_PATH}: {name}.schedule.times must be a list.")

        times = normalize_times(raw_times)
        enabled = bool(raw_schedule.get("enabled", False)) if times else False
        schedule = ScheduleState(enabled=enabled, times=times)

    else:
        raise ValueError(f"{PROFILES_PATH}: {name}.schedule must be a mapping.")

    raw_log = raw.get("log", "OFF")

    # PyYAML YAML 1.1 may parse unquoted ON/OFF as booleans.
    if isinstance(raw_log, bool):
        log_mode = "ON" if raw_log else "OFF"
    else:
        log_mode = str(raw_log).strip().upper()

    if log_mode not in LOG_MODES:
        raise ValueError(f"{PROFILES_PATH}: {name}.log must be OFF, ON, or FULL.")

    language = normalize_language(raw.get("lang", "en"))

    return ProfileState(
        chat_id=chat_id,
        schedule=schedule,
        log=log_mode,
        lang=language,
    )


def load_profiles() -> dict[str, ProfileState]:
    if PROFILES_PATH.exists():
        with PROFILES_PATH.open(encoding="utf-8") as f:
            data = yaml.safe_load(f)
    else:
        data = {}

    if data is None:
        data = {}

    if not isinstance(data, dict):
        raise ValueError(f"{PROFILES_PATH} must map names to profile settings.")

    ensure_unique_slugs(data)

    profiles: dict[str, ProfileState] = {}
    chat_ids: dict[int, str] = {}

    for raw_name, raw_profile in data.items():
        name = validate_name(raw_name)
        profile = parse_profile(name, raw_profile)

        existing_name = chat_ids.get(profile.chat_id)

        if existing_name is not None:
            raise ValueError(
                f"{PROFILES_PATH}: duplicate chat_id {profile.chat_id} used by {existing_name!r} and {name!r}."
            )

        chat_ids[profile.chat_id] = name
        profiles[name] = profile

    return profiles


def save_profiles(profiles: dict[str, ProfileState]) -> None:
    ensure_unique_slugs(profiles)

    data: dict[str, dict] = {}
    chat_ids: dict[int, str] = {}

    for name, profile in profiles.items():
        validate_name(name)

        chat_id = normalize_chat_id(profile.chat_id, name=name)
        existing_name = chat_ids.get(chat_id)

        if existing_name is not None:
            raise ValueError(
                f"{PROFILES_PATH}: duplicate chat_id {chat_id} used by {existing_name!r} and {name!r}."
            )

        chat_ids[chat_id] = name
        times = normalize_times(profile.schedule.times)

        data[name] = {
            "chat_id": chat_id,
            "schedule": {
                "enabled": bool(profile.schedule.enabled) if times else False,
                "times": times,
            },
            "log": profile.log.upper(),
            "lang": normalize_language(profile.lang),
        }

    PROFILES_PATH.parent.mkdir(parents=True, exist_ok=True)

    tmp = PROFILES_PATH.with_suffix(PROFILES_PATH.suffix + ".tmp")
    tmp.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    tmp.replace(PROFILES_PATH)


def ensure_profiles_file() -> None:
    save_profiles(load_profiles())


def get_profile(name: str) -> ProfileState:
    name = validate_name(name)
    profiles = load_profiles()

    if name not in profiles:
        raise ValueError(f"Unknown profile: {name}")

    return profiles[name]


def get_profile_by_chat_id(chat_id: int) -> tuple[str, ProfileState] | None:
    for name, profile in load_profiles().items():
        if profile.chat_id == chat_id:
            return name, profile

    return None


def set_schedule(
        name: str,
        *,
        times: Iterable[object] | None = None,
        enabled: bool | None = None,
) -> ScheduleState:
    name = validate_name(name)
    profiles = load_profiles()

    if name not in profiles:
        raise ValueError(f"Unknown profile: {name}")

    profile = profiles[name]
    new_times = profile.schedule.times if times is None else normalize_times(times)

    if not new_times:
        new_enabled = False
    elif enabled is None:
        new_enabled = profile.schedule.enabled
    else:
        new_enabled = bool(enabled)

    profile.schedule = ScheduleState(enabled=new_enabled, times=new_times)
    profiles[name] = profile
    save_profiles(profiles)

    return profile.schedule


def get_log_mode(name: str) -> str:
    return get_profile(name).log


def set_log_mode(name: str, mode: str) -> str:
    name = validate_name(name)
    mode = mode.upper()

    if mode not in LOG_MODES:
        raise ValueError("Log mode must be OFF, ON, or FULL.")

    profiles = load_profiles()

    if name not in profiles:
        raise ValueError(f"Unknown profile: {name}")

    profiles[name].log = mode
    save_profiles(profiles)

    return mode


def get_language(name: str) -> str:
    return get_profile(name).lang


def set_language(name: str, language: str) -> str:
    name = validate_name(name)
    language = normalize_language(language)
    profiles = load_profiles()

    if name not in profiles:
        raise ValueError(f"Unknown profile: {name}")

    profiles[name].lang = language
    save_profiles(profiles)

    return language
