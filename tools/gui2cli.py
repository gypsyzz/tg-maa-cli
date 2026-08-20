#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

SERVER_MAP = {"Official": "CN", "Bilibili": "CN", "txwy": "CN", "YoStarEN": "US", "YoStarJP": "JP", "YoStarKR": "KR", }

INFRast_MODE_MAP = {"Default": 0, "Custom": 10000, "Rotation": 20000, }

# WPF stores several credit-store item names using English canonical labels,
# while the CN MaaCore task parameters use the in-game Chinese names.
ITEM_NAME_MAP = {
    "Recruitment Permit": "招聘许可",
    "Furniture Part": "家具零件",
    "Expedited Plan": "加急许可",
    "Carbon": "碳",
}


def split_list(value):
    return [x.strip() for x in (value or "").split(";") if x.strip()]


def convert(src):
    current = src["Current"]
    cfg = src["Configurations"][current]
    runtime = cfg["Gui"]["RuntimeSettings"]

    client_type = runtime.get("ClientType", "Official")
    server = SERVER_MAP.get(client_type, "CN")

    result = []
    warnings = []

    for task in cfg["TaskQueue"]:
        if not task.get("IsEnable", True):
            continue

        task_type = task["TaskType"]
        name = task.get("Name") or None

        if task_type == "StartUp":
            params = {"client_type": client_type, "start_game_enabled": bool(runtime.get("StartGame", False)), }
            if task.get("AccountSwitchEnabled") and task.get("AccountName"):
                params["account_name"] = task["AccountName"]

            converted = {"type": "StartUp", "params": params}

        elif task_type == "Award":
            converted = {"type": "Award", "params": {"award": task.get("Award", True), "mail": task.get("Mail", False),
                                                     "recruit": task.get("FreeGacha", False),
                                                     "orundum": task.get("Orundum", False),
                                                     "mining": task.get("Mining", False),
                                                     "specialaccess": task.get("SpecialAccess", False), }, }

        elif task_type == "Fight":
            stages = task.get("StagePlan") or []
            if len(stages) > 1:
                raise ValueError(
                    f"Fight task {name!r} has multiple StagePlan entries {stages}; " "that WPF behavior is not safe to flatten automatically.")

            params = {
                "stage": stages[0] if stages else "",
                "medicine": task.get("MedicineCount", 0)
                if task.get("UseMedicine")
                else 0,
                "medicine_expire_days": task.get("MedicineExpireDays", 0)
                if task.get("UseExpiringMedicine")
                else 0,
                "stone": task.get("StoneCount", 0)
                if task.get("UseStone")
                else 0,
                "series": task.get("Series", 0),
                "report_to_penguin": runtime.get("ReportToPenguin", False),
                "penguin_id": runtime.get("PenguinId", ""),
                "report_to_yituliu": runtime.get("ReportToYituliu", False),
                "server": server,
                "client_type": client_type,
                "DrGrandet": task.get("IsDrGrandet", False),
            }

            if task.get("EnableTimesLimit"):
                params["times"] = task.get("TimesLimit", 2147483647)

            if task.get("EnableTargetDrop") and task.get("DropId"):
                if task.get("IsInventoryTarget"):
                    raise ValueError("Inventory-target Fight mode has no direct mapping in this converter.")
                params["drops"] = {task["DropId"]: task.get("DropCount", 0)}

            converted = {"type": "Fight", "params": params}

        elif task_type == "Infrast":
            mode = INFRast_MODE_MAP.get(task.get("Mode"), 0)
            params = {
                "mode": mode,
                "facility": [
                    room["Room"]
                    for room in task.get("RoomList", [])
                    if room.get("IsEnabled", True)
                ],
                "drones": task.get("UsesOfDrones", "_NotUse"),
                "threshold": task.get("DormThreshold", 30) / 100,
                "replenish": task.get(
                    "OriginiumShardAutoReplenishment", False
                ),
                "dorm_notstationed_enabled": task.get(
                    "DormFilterNotStationed", False
                ),
                "dorm_trust_enabled": task.get("DormTrustEnabled", False),
                "reception_message_board": task.get(
                    "ReceptionMessageBoard", True
                ),
                "reception_clue_exchange": task.get(
                    "ReceptionClueExchange", True
                ),
                "reception_send_clue": task.get("SendClue", True),
            }

            if mode == 10000:
                params["filename"] = task.get("Filename", "")
                params["plan_index"] = task.get("PlanSelect", 0)

            if task.get("ContinueTraining"):
                warnings.append("Infrast ContinueTraining=true has no documented " "direct MaaCore Infrast parameter.")

            converted = {"type": "Infrast", "params": params}

        elif task_type == "Recruit":
            confirm = [level for level in (3, 4, 5, 6) if task.get(f"Level{level}Choose", False)]

            # WPF-style normal selection: pick 4/5-star tag combinations;
            # 3-star tags are only selected when preferred-tag behavior is enabled.
            select = [5, 4]
            if task.get("PreferTagEnabled") and task.get("Level3PreferTags"):
                select.append(3)
            if task.get("Level6Choose"):
                select.insert(0, 6)

            params = {
                "refresh": task.get("RefreshLevel3", False),
                "select": select,
                "confirm": confirm,
                "first_tags": (
                    task.get("Level3PreferTags", [])
                    if task.get("PreferTagEnabled")
                    else []
                ),
                "extra_tags_mode": task.get("ExtraTagMode", 0),
                "times": task.get("MaxTimes", 0),
                "preserve_tags": (
                    task.get("PreserveTagList", [])
                    if task.get("PreserveTagEnabled")
                    else []
                ),
                "recruitment_time": {
                    "3": task.get("Level3Time", 540),
                    "4": task.get("Level4Time", 540),
                },
                "report_to_penguin": runtime.get(
                    "ReportToPenguin", False
                ),
                "penguin_id": runtime.get("PenguinId", ""),
                "report_to_yituliu": runtime.get(
                    "ReportToYituliu", False
                ),
                "server": server,
            }

            if task.get("ForceRefresh"):
                warnings.append(
                    "Recruit ForceRefresh=true is WPF-specific; " "MaaCore CLI exposes refresh but no ForceRefresh parameter.")

            converted = {"type": "Recruit", "params": params}

        elif task_type == "Mall":
            buy_first = [ITEM_NAME_MAP.get(x, x) for x in split_list(task.get("FirstList"))]
            blacklist = [ITEM_NAME_MAP.get(x, x) for x in split_list(task.get("BlackList"))]

            converted = {
                "type": "Mall",
                "params": {
                    "visit_friends": task.get("VisitFriends", True),
                    "shopping": task.get("Shopping", True),
                    "buy_first": buy_first,
                    "blacklist": blacklist,
                    "force_shopping_if_credit_full": task.get(
                        "ShoppingIgnoreBlackListWhenFull", False
                    ),
                    "only_buy_discount": task.get(
                        "OnlyBuyDiscount", False
                    ),
                    "reserve_max_credit": task.get(
                        "ReserveMaxCredit", False
                    ),
                    "credit_fight": task.get("CreditFight", False),
                    "formation_index": task.get(
                        "CreditFightFormation", 0
                    ),
                },
            }

        elif task_type == "UserDataUpdate":
            if task.get("UpdateOperBox"):
                result.append({"type": "OperBox", "params": {"enable": True}})
            if task.get("UpdateDepot"):
                result.append({"type": "Depot", "params": {"enable": True}})
            continue

        else:
            raise ValueError(f"Unsupported enabled WPF task type: {task_type}")

        if name:
            converted["name"] = name

        result.append(converted)

    return current, {"tasks": result}, warnings


def main():
    parser = argparse.ArgumentParser(description="Convert MAA WPF gui.new.json to a maa-cli custom task.")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    src = json.loads(args.input.read_text(encoding="utf-8"))
    profile, converted, warnings = convert(src)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(converted, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", )

    print(f"Converted WPF profile {profile!r} -> {args.output}")
    for warning in warnings:
        print(f"WARNING: {warning}", file=sys.stderr)


if __name__ == "__main__":
    main()
