from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable
import re

import yaml

from i18n import normalize_language
from maa_config import AUTHORIZED_BY_NAME, PROFILES_PATH, validate_name

TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
LOG_MODES = {"OFF", "ON", "FULL"}


@dataclass
class ScheduleState:
    enabled: bool
    times: list[str]


@dataclass
class ProfileState:
    schedule: ScheduleState
    log: str
    lang: str


def normalize_times(values: Iterable[object], ) -> list[str]:
    times: list[str] = []

    for raw in values:
        value = str(raw).strip()

        if not TIME_RE.fullmatch(value):
            raise ValueError(f"Invalid time {value!r}; " "use HH:MM, e.g. 06:33.")

        if value not in times:
            times.append(value)

    return sorted(times, key=lambda value: tuple(map(int, value.split(":"))), )


def default_profile() -> ProfileState:
    return ProfileState(schedule=ScheduleState(enabled=False, times=[], ), log="OFF", lang="en", )


def parse_profile(name: str, raw: object, ) -> ProfileState:
    if raw is None:
        return default_profile()

    if not isinstance(raw, dict):
        raise ValueError(f"{PROFILES_PATH}: {name} must be a mapping.")

    raw_schedule = raw.get("schedule")

    if raw_schedule is None:
        schedule = ScheduleState(enabled=False, times=[], )

    elif isinstance(raw_schedule, dict):
        if ("enable" in raw_schedule and "enabled" not in raw_schedule):
            raise ValueError(f"{PROFILES_PATH}: {name}.schedule uses 'enable'; " "use 'enabled' instead.")

        raw_times = raw_schedule.get("times") or []

        if not isinstance(raw_times, list):
            raise ValueError(f"{PROFILES_PATH}: " f"{name}.schedule.times must be a list.")

        times = normalize_times(raw_times)
        enabled = (bool(raw_schedule.get("enabled", False)) if times else False)

        schedule = ScheduleState(enabled=enabled, times=times, )

    else:
        raise ValueError(f"{PROFILES_PATH}: " f"{name}.schedule must be a mapping.")

    raw_log = raw.get("log", "OFF")

    # PyYAML YAML 1.1 may parse unquoted ON/OFF as booleans.
    if isinstance(raw_log, bool):
        log_mode = "ON" if raw_log else "OFF"
    else:
        log_mode = str(raw_log).upper()

    if log_mode not in LOG_MODES:
        raise ValueError(f"{PROFILES_PATH}: {name}.log must be " "OFF, ON, or FULL.")

    language = normalize_language(raw.get("lang", "en"))

    return ProfileState(schedule=schedule, log=log_mode, lang=language, )


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

    profiles: dict[str, ProfileState] = {}

    for raw_name, raw_profile in data.items():
        name = validate_name(raw_name)
        profiles[name] = parse_profile(name, raw_profile, )

    for name in AUTHORIZED_BY_NAME:
        profiles.setdefault(name, default_profile(), )

    return profiles


def save_profiles(profiles: dict[str, ProfileState], ) -> None:
    data: dict[str, dict] = {}

    for name, profile in profiles.items():
        validate_name(name)

        times = normalize_times(profile.schedule.times)

        data[name] = {"schedule": {"enabled": (bool(profile.schedule.enabled) if times else False), "times": times, },
                      "log": profile.log.upper(), "lang": normalize_language(profile.lang), }

    PROFILES_PATH.parent.mkdir(parents=True, exist_ok=True, )

    tmp = PROFILES_PATH.with_suffix(PROFILES_PATH.suffix + ".tmp")

    tmp.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False, ), encoding="utf-8", )

    tmp.replace(PROFILES_PATH)


def ensure_profiles_file() -> None:
    save_profiles(load_profiles())


def get_profile(name: str) -> ProfileState:
    return load_profiles().get(name, default_profile(), )


def set_schedule(name: str, *, times: Iterable[object] | None = None, enabled: bool | None = None, ) -> ScheduleState:
    profiles = load_profiles()
    profile = profiles.get(name, default_profile(), )

    new_times = (profile.schedule.times if times is None else normalize_times(times))

    if not new_times:
        new_enabled = False
    elif enabled is None:
        new_enabled = profile.schedule.enabled
    else:
        new_enabled = bool(enabled)

    profile.schedule = ScheduleState(enabled=new_enabled, times=new_times, )

    profiles[name] = profile
    save_profiles(profiles)

    return profile.schedule


def get_log_mode(name: str) -> str:
    return get_profile(name).log


def set_log_mode(name: str, mode: str, ) -> str:
    mode = mode.upper()

    if mode not in LOG_MODES:
        raise ValueError("Log mode must be OFF, ON, or FULL.")

    profiles = load_profiles()
    profile = profiles.get(name, default_profile(), )

    profile.log = mode
    profiles[name] = profile
    save_profiles(profiles)

    return mode


def get_language(name: str) -> str:
    return get_profile(name).lang


def set_language(name: str, language: str, ) -> str:
    language = normalize_language(language)

    profiles = load_profiles()
    profile = profiles.get(name, default_profile(), )

    profile.lang = language
    profiles[name] = profile
    save_profiles(profiles)

    return language
