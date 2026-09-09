import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from task_store import canonicalize_stage_case, normalize_fight_stage, parse_fight_add_args


class FightStageCanonicalizationTests(TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.resource_root = Path(self.temporary_directory.name)
        navigation_dir = self.resource_root / "tasks/Stages"
        navigation_dir.mkdir(parents=True)
        (self.resource_root / "stages.json").write_text(
            json.dumps([{"code": "1-7"}, {"code": "AT-8"}]),
            encoding="utf-8",
        )
        (navigation_dir / "test.json").write_text(
            json.dumps({
                "AT-8": {},
                "SSReopen-AT": {},
                "Case-Alias": {},
                "CASE-ALIAS": {},
                "AT-8@Internal": {},
            }),
            encoding="utf-8",
        )

    def canonicalize(self, stage: str, *, strict: bool = True) -> str:
        return canonicalize_stage_case(stage, (self.resource_root, ), strict=strict)

    def test_unique_case_insensitive_match_uses_canonical_name(self) -> None:
        self.assertEqual(self.canonicalize("at-8"), "AT-8")
        self.assertEqual(self.canonicalize("ssreopen-at"), "SSReopen-AT")

    def test_exact_mixed_case_match_is_preserved(self) -> None:
        self.assertEqual(self.canonicalize("SSReopen-AT"), "SSReopen-AT")

    def test_ambiguous_name_lists_exact_choices(self) -> None:
        with self.assertRaisesRegex(ValueError, "CASE-ALIAS.*Case-Alias"):
            self.canonicalize("case-alias")

        self.assertEqual(self.canonicalize("Case-Alias"), "Case-Alias")

    def test_unknown_name_suggests_close_canonical_name(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown Fight stage 'AT8'.*AT-8"):
            self.canonicalize("AT8")

    def test_unknown_name_is_preserved_only_for_existing_stored_tasks(self) -> None:
        self.assertEqual(self.canonicalize("Unknown-1", strict=False), "Unknown-1")

    def test_missing_resource_table_does_not_reject_input(self) -> None:
        empty_root = self.resource_root / "empty"
        empty_root.mkdir()
        self.assertEqual(canonicalize_stage_case("Unknown-1", (empty_root, )), "Unknown-1")

    def test_installed_resources_correct_at_8(self) -> None:
        self.assertEqual(normalize_fight_stage("at-8"), "AT-8")

    def test_dash_normalization_happens_before_case_lookup(self) -> None:
        self.assertEqual(normalize_fight_stage("at–8"), "AT-8")

    def test_fight_add_parser_returns_canonical_stage(self) -> None:
        self.assertEqual(parse_fight_add_args(["at-8", "6"]), ("AT-8", 6))

    def test_fight_add_parser_rejects_unknown_stage(self) -> None:
        with self.assertRaisesRegex(ValueError, "Unknown Fight stage 'AT8'.*AT-8"):
            parse_fight_add_args(["AT8"])
