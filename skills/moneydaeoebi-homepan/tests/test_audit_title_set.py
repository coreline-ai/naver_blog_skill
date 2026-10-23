from __future__ import annotations

import argparse
import importlib.util
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).parents[1] / "scripts" / "audit_title_set.py"
SPEC = importlib.util.spec_from_file_location("audit_title_set", SCRIPT)
assert SPEC and SPEC.loader
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)


def make_args(*, track: str = "feed", sensitive: bool = False) -> argparse.Namespace:
    return argparse.Namespace(
        r9=True,
        feed=False,
        track=track,
        sensitive=sensitive,
        expected_count=None,
        prefix_chars=6,
        max_prefix_repeat=1,
        strict=True,
    )


def make_titles(*, sensitive: bool = False, repeated_search_prefix: bool = False) -> list[str]:
    titles: list[str] = []
    for group in range(10):
        if group < 5:
            n_labels = ("N6", "N7", "N1")
        else:
            n_labels = ("N2", "N3", "N4")

        for slot in range(5):
            number = group * 5 + slot + 1
            emotional = group == 9 and not sensitive
            replacement = " [민감대체]" if group == 9 and sensitive else ""
            if slot < 2:
                if repeated_search_prefix:
                    starter = f"청년지원금 조건{number:02d}"
                else:
                    starter = f"질문{number:02d}"
                if emotional:
                    starter += " 충격"
                title = f"“{starter}?” 대상{number:02d} [독자 반응]{replacement}"
            else:
                prefix = "청년지원금" if repeated_search_prefix else f"후보{number:02d}"
                emotion_text = " 충격" if emotional else ""
                n_label = n_labels[slot - 2]
                title = (
                    f"{prefix} 조건{number:02d}{emotion_text} 대상{number:02d} "
                    f"[무따옴표-{n_label}]{replacement}"
                )
            titles.append(title)
    return titles


def make_manifest(titles: list[str]) -> dict[str, object]:
    starters = {f"S{index:02d}": f"원형후보{index:02d} 주제{index:02d}" for index in range(1, 31)}
    top_numbers = [1, 6, 11, 16, 46]
    top5 = [
        {"number": number, "title": AUDIT.title_body(titles[number - 1])}
        for number in top_numbers
    ]
    return {
        "topics": [
            {
                "topic": "검증 주제",
                "title_numbers": list(range(1, 51)),
                "starters": starters,
            }
        ],
        "top5": top5,
        "final": {"number": 11, "title": AUDIT.title_body(titles[10])},
    }


class AuditTitleSetTests(unittest.TestCase):
    def test_cli_accepts_valid_r9_files(self) -> None:
        titles = make_titles()
        manifest = make_manifest(titles)
        with tempfile.TemporaryDirectory() as directory:
            title_path = Path(directory) / "titles.txt"
            manifest_path = Path(directory) / "manifest.json"
            title_path.write_text("\n".join(titles), encoding="utf-8")
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
            )
            argv = [
                "audit_title_set.py",
                str(title_path),
                "--r9",
                "--track",
                "feed",
                "--manifest",
                str(manifest_path),
                "--strict",
            ]
            output = io.StringIO()
            with patch("sys.argv", argv), redirect_stdout(output):
                exit_code = AUDIT.main()
        self.assertEqual(0, exit_code, output.getvalue())
        self.assertIn("OK", output.getvalue())

    def test_valid_feed_matrix_and_manifest_pass(self) -> None:
        titles = make_titles()
        result = AUDIT.audit(titles, make_args())
        self.assertTrue(result["ok"], result)
        self.assertEqual([], AUDIT.audit_manifest(make_manifest(titles), titles))

    def test_missing_starter_label_fails(self) -> None:
        titles = make_titles()
        titles[0] = titles[0].replace(" [독자 반응]", "")
        result = AUDIT.audit(titles, make_args())
        self.assertFalse(result["ok"])
        self.assertTrue(any("exactly one starter label" in error for error in result["errors"]))

    def test_quoted_title_cannot_fake_n6_coverage(self) -> None:
        titles = make_titles()
        titles[0] = titles[0].replace("[독자 반응]", "[무따옴표-N6]")
        result = AUDIT.audit(titles, make_args())
        self.assertFalse(result["ok"])
        self.assertTrue(any("quoted title 1" in error for error in result["errors"]))

    def test_grounded_emotional_group_is_not_a_strict_warning(self) -> None:
        result = AUDIT.audit(make_titles(), make_args())
        self.assertTrue(result["ok"], result)
        self.assertEqual(5, result["metrics"]["conditional_emotional_title_count"])

    def test_forbidden_hook_fails(self) -> None:
        titles = make_titles()
        titles[2] = titles[2].replace("조건03", "무조건 조건03")
        result = AUDIT.audit(titles, make_args())
        self.assertFalse(result["ok"])
        self.assertTrue(any("forbidden hook" in error for error in result["errors"]))

    def test_search_track_allows_repeated_search_identifier(self) -> None:
        titles = make_titles(repeated_search_prefix=True)
        result = AUDIT.audit(titles, make_args(track="search"))
        self.assertTrue(result["ok"], result)

    def test_sensitive_group_requires_replacement_and_rejects_emotion(self) -> None:
        safe_result = AUDIT.audit(make_titles(sensitive=True), make_args(sensitive=True))
        self.assertTrue(safe_result["ok"], safe_result)

        unsafe_result = AUDIT.audit(make_titles(), make_args(sensitive=True))
        self.assertFalse(unsafe_result["ok"])
        self.assertTrue(any("sensitive title" in error for error in unsafe_result["errors"]))

    def test_manifest_requires_all_thirty_unique_starters(self) -> None:
        titles = make_titles()
        manifest = make_manifest(titles)
        del manifest["topics"][0]["starters"]["S30"]
        errors = AUDIT.audit_manifest(manifest, titles)
        self.assertTrue(any("missing starter IDs" in error for error in errors))

    def test_manifest_rejects_top5_from_same_group(self) -> None:
        titles = make_titles()
        manifest = make_manifest(titles)
        manifest["top5"] = [
            {"number": number, "title": AUDIT.title_body(titles[number - 1])}
            for number in range(1, 6)
        ]
        manifest["final"] = {"number": 1, "title": AUDIT.title_body(titles[0])}
        errors = AUDIT.audit_manifest(manifest, titles)
        self.assertTrue(any("five different groups" in error for error in errors))

    def test_manifest_rejects_changed_final_title(self) -> None:
        titles = make_titles()
        manifest = make_manifest(titles)
        manifest["final"]["title"] += " 수정"
        errors = AUDIT.audit_manifest(manifest, titles)
        self.assertTrue(any("does not exactly match" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
