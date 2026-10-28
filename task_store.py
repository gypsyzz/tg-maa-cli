from __future__ import annotations

import copy
import json
import unicodedata
from collections.abc import Iterable
from difflib import get_close_matches
from pathlib import Path

from maa_config import task_file_for


FIGHT_TEMPLATE_PATH = Path(__file__).with_name("templates") / "fight.json"
DASH_EQUIVALENTS = frozenset({"\u2212"})
DEFAULT_STAGE_RESOURCE_ROOTS = (Path.home() / ".local/share/maa/resource", Path.home() / ".local/share/maa/MaaResource/resource")


def load_task_json(name: str) -> tuple[Path, dict]:
    path = task_file_for(name)

    if not path.is_file():
        raise FileNotFoundError(f"Task file not found: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object.")

    if not isinstance(data.get("tasks"), list):
        raise ValueError(f"{path} must contain a 'tasks' list.")

    return path, data


def save_task_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")

    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    tmp.replace(path)


def task_type(task: object) -> str:
    if not isinstance(task, dict):
        return "Unknown"

    value = task.get("type")

    return "Unknown" if value is None else str(value)


def fight_stage(task: object) -> str:
    if not isinstance(task, dict):
        return "Unknown"

    params = task.get("params")

    if not isinstance(params, dict):
        return "Unknown"

    value = params.get("stage")

    if value in (None, ""):
        return "Unknown"

    return str(value)


def short_task_sequence(data: dict) -> str:
    lines: list[str] = []

    for index, task in enumerate(data["tasks"], start=1):
        kind = task_type(task)

        if kind == "Fight":
            lines.append(f"{index}. Fight - {fight_stage(task)}")
        else:
            lines.append(f"{index}. {kind}")

    return "\n".join(lines)


def long_task_sequence(data: dict) -> str:
    lines: list[str] = []

    for index, task in enumerate(data["tasks"], start=1):
        if not isinstance(task, dict):
            lines.append(f"{index}. Unknown\n   params: {{}}")
            continue

        kind = task_type(task)
        name = task.get("name")

        header = f"{index}. {kind}"

        if name:
            header += f" [{name}]"

        params = task.get("params") or {}

        params_text = json.dumps(params, ensure_ascii=False, separators=(",", ":"))

        lines.append(f"{header}\n   params: {params_text}")

    return "\n".join(lines)


def fight_sequence(data: dict) -> str:
    lines: list[str] = []

    for index, task in enumerate(data["tasks"], start=1):
        if task_type(task) == "Fight":
            lines.append(f"{index}. {fight_stage(task)}")

    return "\n".join(lines) if lines else "No Fight tasks configured."


def fight_entries(data: dict) -> list[tuple[int, dict]]:
    return [(index, task) for index, task in enumerate(data["tasks"]) if isinstance(task, dict) and task_type(task) == "Fight"]


def load_fight_template() -> dict:
    try:
        template = json.loads(FIGHT_TEMPLATE_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"Fight template not found: {FIGHT_TEMPLATE_PATH}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid Fight template in {FIGHT_TEMPLATE_PATH}: {exc}") from exc

    if not isinstance(template, dict) or task_type(template) != "Fight":
        raise ValueError(f"{FIGHT_TEMPLATE_PATH} must contain a Fight task object.")

    if not isinstance(template.get("params"), dict):
        raise ValueError(f"The Fight template in {FIGHT_TEMPLATE_PATH} has no valid params object.")

    return template


def automatic_fight_insert_index(data: dict) -> int:
    tasks = data["tasks"]

    for index in range(len(tasks) - 1, -1, -1):
        if task_type(tasks[index]) == "StartUp":
            return index + 1

    raise ValueError("No StartUp task is available for automatic Fight placement. Specify an overall task position.")


def canonical_stage_names(resource_roots: Iterable[Path] | None = None) -> set[str]:
    names: set[str] = set()
    roots = DEFAULT_STAGE_RESOURCE_ROOTS if resource_roots is None else tuple(resource_roots)

    for root in roots:
        stages_path = root / "stages.json"

        try:
            stages = json.loads(stages_path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            stages = []

        if isinstance(stages, list):
            for entry in stages:
                if isinstance(entry, dict) and isinstance(entry.get("code"), str) and entry["code"]:
                    names.add(entry["code"])

        navigation_dir = root / "tasks/Stages"

        if not navigation_dir.is_dir():
            continue

        for path in navigation_dir.rglob("*.json"):
            try:
                navigation = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue

            if not isinstance(navigation, dict):
                continue

            names.update(name for name in navigation if isinstance(name, str) and name and "@" not in name)

    return names


def canonicalize_stage_case(stage: str, resource_roots: Iterable[Path] | None = None, *, strict: bool = True) -> str:
    names = canonical_stage_names(resource_roots)

    if not names:
        return stage

    if stage in names:
        return stage

    matches = {name for name in names if name.casefold() == stage.casefold()}

    if len(matches) == 1:
        return next(iter(matches))

    if not strict:
        return stage

    if matches:
        choices = ", ".join(repr(name) for name in sorted(matches))
        raise ValueError(f"Fight stage {stage!r} is ambiguous; use the exact case of one of: {choices}.")

    folded_names: dict[str, set[str]] = {}

    for name in names:
        folded_names.setdefault(name.casefold(), set()).add(name)

    close_folded = get_close_matches(stage.casefold(), sorted(folded_names), n=5, cutoff=0.6)
    suggestions = [name for folded in close_folded for name in sorted(folded_names[folded])]
    suggestion_text = f" Did you mean: {', '.join(repr(name) for name in suggestions)}?" if suggestions else ""

    raise ValueError(f"Unknown Fight stage {stage!r}.{suggestion_text}")


def normalize_fight_stage(stage: str, *, strict: bool = True) -> str:
    normalized = unicodedata.normalize("NFKC", stage.strip())
    normalized = "".join("-" if unicodedata.category(character) == "Pd" or character in DASH_EQUIVALENTS else character for character in normalized)

    if "-" not in normalized and normalized.casefold().startswith("anni"):
        return "Annihilation"

    return canonicalize_stage_case(normalized, strict=strict)


def parse_fight_add_args(values: list[str]) -> tuple[str, int | None]:
    if not values:
        raise ValueError("Usage: /fight add STAGE [POSITION]")

    position: int | None = None
    stage_tokens = values

    if len(values) >= 2:
        try:
            position = int(values[-1])
        except ValueError:
            position = None
        else:
            stage_tokens = values[:-1]

    stage = normalize_fight_stage(" ".join(stage_tokens))

    if not stage:
        raise ValueError("Stage name cannot be empty.")

    if position is not None and position < 1:
        raise ValueError("Overall task position must be 1 or greater.")

    return stage, position


def add_fight_task(data: dict, stage: str, position: int | None) -> int:
    """
    Position is an optional 1-based overall task index:

      1       -> insert as the first overall task
      5       -> insert as the fifth overall task
      omitted -> immediately after the final StartUp task
    """
    fights = fight_entries(data)

    for _, task in fights:
        if normalize_fight_stage(fight_stage(task), strict=False) == stage:
            raise ValueError(f"Fight stage {stage!r} already exists.")

    if position is not None and position > len(data["tasks"]) + 1:
        raise ValueError(f"Overall task position {position} is out of range. Valid positions are 1 to {len(data['tasks']) + 1}.")

    template = copy.deepcopy(fights[-1][1]) if fights else load_fight_template()

    params = template.get("params")

    if not isinstance(params, dict):
        raise ValueError("The Fight template has no valid params object.")

    params["stage"] = stage
    template["name"] = stage

    if position is not None:
        insert_at = position - 1
    else:
        insert_at = automatic_fight_insert_index(data)

    data["tasks"].insert(insert_at, template)

    return insert_at + 1


def remove_fight_task(data: dict, task_index: int) -> str:
    if task_index < 1:
        raise ValueError("Task index must be 1 or greater.")

    tasks = data["tasks"]

    if task_index > len(tasks):
        raise ValueError(f"Task index {task_index} is out of range. There are {len(tasks)} tasks.")

    task = tasks[task_index - 1]
    kind = task_type(task)

    if kind != "Fight":
        raise ValueError(f"Task {task_index} is {kind}, not Fight.")

    stage = fight_stage(task)

    del tasks[task_index - 1]

    return stage
