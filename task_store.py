from __future__ import annotations

import copy
import json
from pathlib import Path

from maa_config import task_file_for


def load_task_json(name: str, ) -> tuple[Path, dict]:
    path = task_file_for(name)

    if not path.is_file():
        raise FileNotFoundError(f"Task file not found: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object.")

    if not isinstance(data.get("tasks"), list, ):
        raise ValueError(f"{path} must contain a 'tasks' list.")

    return path, data


def save_task_json(path: Path, data: dict, ) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")

    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2, ) + "\n", encoding="utf-8", )

    tmp.replace(path)


def task_type(task: object) -> str:
    if not isinstance(task, dict):
        return "Unknown"

    value = task.get("type")

    return ("Unknown" if value is None else str(value))


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


def short_task_sequence(data: dict, ) -> str:
    lines: list[str] = []

    for index, task in enumerate(data["tasks"], start=1, ):
        kind = task_type(task)

        if kind == "Fight":
            lines.append(f"{index}. Fight - {fight_stage(task)}")
        else:
            lines.append(f"{index}. {kind}")

    return "\n".join(lines)


def long_task_sequence(data: dict, ) -> str:
    lines: list[str] = []

    for index, task in enumerate(data["tasks"], start=1, ):
        if not isinstance(task, dict):
            lines.append(f"{index}. Unknown\n" "   params: {}")
            continue

        kind = task_type(task)
        name = task.get("name")

        header = f"{index}. {kind}"

        if name:
            header += f" [{name}]"

        params = task.get("params") or {}

        params_text = json.dumps(params, ensure_ascii=False, separators=(",", ":"), )

        lines.append(f"{header}\n" f"   params: {params_text}")

    return "\n".join(lines)


def fight_sequence(data: dict, ) -> str:
    lines: list[str] = []

    for index, task in enumerate(data["tasks"], start=1, ):
        if task_type(task) == "Fight":
            lines.append(f"{index}. {fight_stage(task)}")

    return ("\n".join(lines) if lines else "No Fight tasks configured.")


def fight_entries(data: dict, ) -> list[tuple[int, dict]]:
    entries: list[tuple[int, dict]] = []

    for index, task in enumerate(data["tasks"]):
        if (isinstance(task, dict) and task_type(task) == "Fight"):
            entries.append((index, task))

    return entries


def parse_fight_add_args(values: list[str], ) -> tuple[str, int | None]:
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

    stage = " ".join(stage_tokens).strip()

    if not stage:
        raise ValueError("Stage name cannot be empty.")

    if (position is not None and position < 0):
        raise ValueError("Fight position cannot be negative.")

    return stage, position


def add_fight_task(data: dict, stage: str, position: int | None, ) -> tuple[int, int]:
    """
    Position is Fight-relative:

      0       -> before all existing Fight tasks
      1       -> after the first Fight
      2       -> after the second Fight
      omitted -> after the last Fight
    """
    fights = fight_entries(data)

    if not fights:
        raise ValueError("No existing Fight task is available " "to use as the template.")

    for _, task in fights:
        if fight_stage(task) == stage:
            raise ValueError(f"Fight stage {stage!r} already exists.")

    fight_count = len(fights)

    if position is None:
        position = fight_count

    if position > fight_count:
        raise ValueError(f"Fight position {position} is out of range. " f"Valid positions are 0 to {fight_count}.")

    template = copy.deepcopy(fights[-1][1])

    params = template.get("params")

    if not isinstance(params, dict):
        raise ValueError("The Fight template has no valid params object.")

    params["stage"] = stage
    template["name"] = stage

    if position == fight_count:
        insert_at = (fights[-1][0] + 1)
    else:
        insert_at = fights[position][0]

    data["tasks"].insert(insert_at, template, )

    return insert_at + 1, position


def remove_fight_task(data: dict, task_index: int, ) -> str:
    if task_index < 1:
        raise ValueError("Task index must be 1 or greater.")

    tasks = data["tasks"]

    if task_index > len(tasks):
        raise ValueError(f"Task index {task_index} is out of range. " f"There are {len(tasks)} tasks.")

    task = tasks[task_index - 1]
    kind = task_type(task)

    if kind != "Fight":
        raise ValueError(f"Task {task_index} is {kind}, not Fight.")

    stage = fight_stage(task)

    del tasks[task_index - 1]

    return stage
