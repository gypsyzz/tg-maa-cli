from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Iterable

import yaml

from i18n import normalize_language
from maa_config import PROFILES_PATH, slug_for, validate_name

TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")
ALERT_HOURS_RE = re.compile(r"^[1-9]\d*$")
CONTAINER_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
WINDOWS_HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]*$")
WINDOWS_USER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
WINDOWS_PROCESS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
WINDOWS_EXECUTABLE_RE = re.compile(r"^[A-Za-z]:\\[^\r\n\x00]+$")
WINDOWS_TASK_RE = re.compile(r"^[^\r\n\x00]+$")
LOG_MODES = {"OFF", "ON", "FULL"}
DEFAULT_ALERT_HOURS = 24


class _QuotedTime(str):
    pass


class _ProfileDumper(yaml.SafeDumper):
    pass


def _represent_quoted_time(dumper: yaml.SafeDumper, value: _QuotedTime) -> yaml.nodes.ScalarNode:
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style='"')


_ProfileDumper.add_representer(_QuotedTime, _represent_quoted_time)


@dataclass
class ScheduleState:
    run_enabled: bool
    check_enabled: bool
    times: list[str]


@dataclass
class AlertState:
    enabled: bool
    hours: int


@dataclass
class ScheduleCheckState:
    container_name: str
    windows_host: str
    windows_user: str
    ssh_identity: str
    windows_process: str
    windows_executable: str
    windows_start_task: str


@dataclass
class ProfileState:
    chat_id: int
    admin: bool
    schedule: ScheduleState
    schedule_check: ScheduleCheckState
    alert: AlertState
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


def validate_alert_hours(value: object) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError("Alert time must be a positive whole number of hours.")

    return value


def parse_alert_hours(value: object) -> int:
    raw = str(value).strip()

    if not ALERT_HOURS_RE.fullmatch(raw):
        raise ValueError("Alert time must be a positive whole number of hours.")

    return validate_alert_hours(int(raw))


def _validated_schedule_check_value(
        raw: object,
        *,
        name: str,
        field: str,
        pattern: re.Pattern[str] | None = None,
) -> str:
    value = str(raw or "").strip()

    if not value:
        raise ValueError(f"{PROFILES_PATH}: {name}.schedule_check.{field} is required when enabled.")

    if pattern is not None and not pattern.fullmatch(value):
        raise ValueError(f"{PROFILES_PATH}: {name}.schedule_check.{field} has an invalid value.")

    return value


def parse_schedule_check(name: str, raw: object, *, enabled: bool, ) -> ScheduleCheckState:
    if raw is None:
        raw = {}

    if not isinstance(raw, dict):
        raise ValueError(f"{PROFILES_PATH}: {name}.schedule_check must be a mapping.")

    container_name = str(raw.get("container_name", "") or "").strip()
    windows_host = str(raw.get("windows_host", "") or "").strip()
    windows_user = str(raw.get("windows_user", "") or "").strip()
    ssh_identity = str(raw.get("ssh_identity", "") or "").strip()
    windows_process = str(raw.get("windows_process", "MAA") or "").strip()
    windows_executable = str(raw.get("windows_executable", "") or "").strip()
    windows_start_task = str(raw.get("windows_start_task", "") or "").strip()

    if container_name and not CONTAINER_NAME_RE.fullmatch(container_name):
        raise ValueError(f"{PROFILES_PATH}: {name}.schedule_check.container_name has an invalid value.")

    if enabled:
        windows_host = _validated_schedule_check_value(
            windows_host,
            name=name,
            field="windows_host",
            pattern=WINDOWS_HOST_RE,
        )
        windows_user = _validated_schedule_check_value(
            windows_user,
            name=name,
            field="windows_user",
            pattern=WINDOWS_USER_RE,
        )
        ssh_identity = _validated_schedule_check_value(
            ssh_identity,
            name=name,
            field="ssh_identity",
        )
        windows_process = _validated_schedule_check_value(
            windows_process,
            name=name,
            field="windows_process",
            pattern=WINDOWS_PROCESS_RE,
        )

    if windows_executable and not WINDOWS_EXECUTABLE_RE.fullmatch(windows_executable):
        raise ValueError(f"{PROFILES_PATH}: {name}.schedule_check.windows_executable must be an absolute Windows path.")

    if windows_start_task and not WINDOWS_TASK_RE.fullmatch(windows_start_task):
        raise ValueError(f"{PROFILES_PATH}: {name}.schedule_check.windows_start_task has an invalid value.")

    return ScheduleCheckState(
        container_name=container_name,
        windows_host=windows_host,
        windows_user=windows_user,
        ssh_identity=ssh_identity,
        windows_process=windows_process,
        windows_executable=windows_executable,
        windows_start_task=windows_start_task,
    )


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

    raw_admin = raw.get("admin", False)

    if type(raw_admin) is not bool:
        raise ValueError(f"{PROFILES_PATH}: {name}.admin must be true or false.")

    raw_schedule = raw.get("schedule")

    if raw_schedule is None:
        schedule = ScheduleState(run_enabled=False, check_enabled=False, times=[])

    elif isinstance(raw_schedule, dict):
        if "enable" in raw_schedule:
            raise ValueError(f"{PROFILES_PATH}: {name}.schedule uses 'enable'; use 'run_enabled' instead.")

        if "enabled" in raw_schedule and ("run_enabled" in raw_schedule or "check_enabled" in raw_schedule):
            raise ValueError(
                f"{PROFILES_PATH}: {name}.schedule cannot mix legacy 'enabled' with "
                "'run_enabled' or 'check_enabled'."
            )

        raw_times = raw_schedule.get("times") or []

        if not isinstance(raw_times, list):
            raise ValueError(f"{PROFILES_PATH}: {name}.schedule.times must be a list.")

        times = normalize_times(raw_times)

        if "enabled" in raw_schedule:
            raw_run_enabled = raw_schedule.get("enabled", False)
            raw_check_enabled = False
        else:
            raw_run_enabled = raw_schedule.get("run_enabled", False)
            raw_check_enabled = raw_schedule.get("check_enabled", False)

        if type(raw_run_enabled) is not bool:
            raise ValueError(f"{PROFILES_PATH}: {name}.schedule.run_enabled must be true or false.")

        if type(raw_check_enabled) is not bool:
            raise ValueError(f"{PROFILES_PATH}: {name}.schedule.check_enabled must be true or false.")

        run_enabled = raw_run_enabled if times else False
        check_enabled = raw_check_enabled if times else False

        if run_enabled and check_enabled:
            raise ValueError(
                f"{PROFILES_PATH}: {name}.schedule.run_enabled and check_enabled cannot both be true."
            )

        schedule = ScheduleState(run_enabled=run_enabled, check_enabled=check_enabled, times=times)

    else:
        raise ValueError(f"{PROFILES_PATH}: {name}.schedule must be a mapping.")

    raw_alert = raw.get("alert")

    if raw_alert is None:
        alert = AlertState(enabled=False, hours=DEFAULT_ALERT_HOURS, )

    elif isinstance(raw_alert, dict):
        raw_enabled = raw_alert.get("enabled", False)

        if type(raw_enabled) is not bool:
            raise ValueError(f"{PROFILES_PATH}: {name}.alert.enabled must be true or false.")

        alert = AlertState(
            enabled=raw_enabled,
            hours=validate_alert_hours(raw_alert.get("hours", DEFAULT_ALERT_HOURS)),
        )

    else:
        raise ValueError(f"{PROFILES_PATH}: {name}.alert must be a mapping.")

    raw_log = raw.get("log", "OFF")

    # PyYAML YAML 1.1 may parse unquoted ON/OFF as booleans.
    if isinstance(raw_log, bool):
        log_mode = "ON" if raw_log else "OFF"
    else:
        log_mode = str(raw_log).strip().upper()

    if log_mode not in LOG_MODES:
        raise ValueError(f"{PROFILES_PATH}: {name}.log must be OFF, ON, or FULL.")

    language = normalize_language(raw.get("lang", "en"))
    schedule_check = parse_schedule_check(name, raw.get("schedule_check"), enabled=schedule.check_enabled, )

    return ProfileState(
        chat_id=chat_id,
        admin=raw_admin,
        schedule=schedule,
        schedule_check=schedule_check,
        alert=alert,
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
            "admin": bool(profile.admin),
            "schedule": {
                "run_enabled": bool(profile.schedule.run_enabled) if times else False,
                "check_enabled": bool(profile.schedule.check_enabled) if times else False,
                "times": [_QuotedTime(value) for value in times],
            },
            "schedule_check": asdict(profile.schedule_check),
            "alert": {
                "enabled": bool(profile.alert.enabled),
                "hours": validate_alert_hours(profile.alert.hours),
            },
            "log": profile.log.upper(),
            "lang": normalize_language(profile.lang),
        }

    PROFILES_PATH.parent.mkdir(parents=True, exist_ok=True)

    tmp = PROFILES_PATH.with_suffix(PROFILES_PATH.suffix + ".tmp")
    tmp.write_text(yaml.dump(data, Dumper=_ProfileDumper, allow_unicode=True, sort_keys=False), encoding="utf-8")
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


def resolve_profile_name(value: object) -> str:
    requested_slug = slug_for(validate_name(value))

    for name in load_profiles():
        if slug_for(name) == requested_slug:
            return name

    raise ValueError(f"Unknown profile: {value}")


def set_schedule(
        name: str,
        *,
        times: Iterable[object] | None = None,
        run_enabled: bool | None = None,
        check_enabled: bool | None = None,
) -> ScheduleState:
    name = validate_name(name)
    profiles = load_profiles()

    if name not in profiles:
        raise ValueError(f"Unknown profile: {name}")

    profile = profiles[name]
    new_times = profile.schedule.times if times is None else normalize_times(times)

    if not new_times:
        new_run_enabled = False
        new_check_enabled = False
    else:
        new_run_enabled = profile.schedule.run_enabled if run_enabled is None else bool(run_enabled)
        new_check_enabled = profile.schedule.check_enabled if check_enabled is None else bool(check_enabled)

    if new_run_enabled and new_check_enabled:
        raise ValueError(f"{name} run schedule and repeating check cannot both be enabled.")

    if new_check_enabled:
        parse_schedule_check(name, asdict(profile.schedule_check), enabled=True)

    profile.schedule = ScheduleState(
        run_enabled=new_run_enabled,
        check_enabled=new_check_enabled,
        times=new_times,
    )
    profiles[name] = profile
    save_profiles(profiles)

    return profile.schedule


def set_schedule_check(name: str, state: ScheduleCheckState) -> ScheduleCheckState:
    name = validate_name(name)
    profiles = load_profiles()

    if name not in profiles:
        raise ValueError(f"Unknown profile: {name}")

    validated = parse_schedule_check(name, asdict(state), enabled=profiles[name].schedule.check_enabled)
    profiles[name].schedule_check = validated
    save_profiles(profiles)

    return validated


def validate_schedule_check(name: str, state: ScheduleCheckState) -> ScheduleCheckState:
    return parse_schedule_check(validate_name(name), asdict(state), enabled=True)


def validate_windows_app_control(name: str, state: ScheduleCheckState) -> ScheduleCheckState:
    validated = validate_schedule_check(name, state)

    if not validated.windows_executable:
        raise ValueError(f"{PROFILES_PATH}: {name}.schedule_check.windows_executable is required for app control.")

    if not validated.windows_start_task:
        raise ValueError(f"{PROFILES_PATH}: {name}.schedule_check.windows_start_task is required for app control.")

    return validated


def set_alert_enabled(name: str, enabled: bool) -> AlertState:
    name = validate_name(name)
    profiles = load_profiles()

    if name not in profiles:
        raise ValueError(f"Unknown profile: {name}")

    profiles[name].alert.enabled = bool(enabled)
    save_profiles(profiles)

    return profiles[name].alert


def set_alert_hours(name: str, hours: int) -> AlertState:
    name = validate_name(name)
    hours = validate_alert_hours(hours)
    profiles = load_profiles()

    if name not in profiles:
        raise ValueError(f"Unknown profile: {name}")

    profiles[name].alert.hours = hours
    save_profiles(profiles)

    return profiles[name].alert


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
