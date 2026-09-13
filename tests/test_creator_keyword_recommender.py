from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "skills/naver-creator-keyword-recommender/scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from analyze_snapshots import ContractError, aggregate  # noqa: E402


AS_OF = date(2026, 9, 12)


def keyword(text: str, position: int = 1, **extra: object) -> dict[str, object]:
    return {"kind": "search_keyword", "text": text, "list_position": position, **extra}


def base_document(days: int = 14) -> dict[str, object]:
    snapshots: list[dict[str, object]] = []
    for offset in range(1, days + 1):
        day = (AS_OF - timedelta(days=offset)).isoformat()
        snapshots.extend(
            [
                {"date": day, "surface": "search_inflow", "status": "complete", "items": []},
                {"date": day, "surface": "main_inflow", "status": "complete", "items": []},
            ]
        )
    return {
        "schema": "naver-creator-snapshots/v1",
        "captured_at": "2026-09-12T21:00:00+09:00",
        "snapshots": snapshots,
    }


def snapshot(document: dict[str, object], offset: int, surface: str) -> dict[str, object]:
    target = (AS_OF - timedelta(days=offset)).isoformat()
    return next(
        item
        for item in document["snapshots"]  # type: ignore[index]
        if item["date"] == target and item["surface"] == surface
    )


class CreatorKeywordRecommenderTests(unittest.TestCase):
    def test_complete_windows_score_and_dedupe_days(self) -> None:
        document = base_document()
        for offset in (1, 2, 3, 4, 5):
            snapshot(document, offset, "search_inflow")["items"].append(  # type: ignore[union-attr]
                keyword("화담숲 예약", offset, category="국내여행", segment="topic")
            )
        snapshot(document, 1, "search_inflow")["items"].append(  # type: ignore[union-attr]
            keyword("  화담숲   예약  ", 20, category="국내여행", segment="audience", indicator_raw="new")
        )
        for offset in (8, 9):
            snapshot(document, offset, "search_inflow")["items"].append(keyword("화담숲 예약", 7))  # type: ignore[union-attr]
        for offset in (1, 2):
            snapshot(document, offset, "search_inflow")["items"].append(keyword("새 키워드", 3))  # type: ignore[union-attr]

        title_text = '"307억 계약, 시작도 전에 무효?"'
        snapshot(document, 1, "main_inflow")["items"].append(  # type: ignore[union-attr]
            {"kind": "main_title", "text": title_text, "list_position": 1}
        )
        result = aggregate(document, AS_OF, limit=10)

        self.assertEqual(result["analysis_status"], "complete")
        self.assertTrue(result["comparison_ready"])
        first = result["recommendations"][0]
        self.assertEqual(first["normalized_keyword"], "화담숲 예약")
        self.assertEqual(first["recent_days_seen"], 5)
        self.assertEqual(first["comparison_days_seen"], 2)
        self.assertEqual(first["trend_type"], "persistent")
        self.assertTrue(first["new_signal_observed"])
        emerging = next(item for item in result["recommendations"] if item["keyword"] == "새 키워드")
        self.assertEqual(emerging["trend_type"], "emerging")

        summary = result["title_pattern_summary"]
        pattern_names = {item["name"] for item in summary["patterns"]}
        self.assertTrue({"direct_quote", "number", "question", "conflict"}.issubset(pattern_names))
        self.assertNotIn(title_text, json.dumps(result, ensure_ascii=False))

    def test_incomplete_comparison_blocks_trend_confirmation(self) -> None:
        document = base_document()
        missing = snapshot(document, 14, "search_inflow")
        document["snapshots"].remove(missing)  # type: ignore[union-attr]
        for offset in (1, 2):
            snapshot(document, offset, "search_inflow")["items"].append(keyword("관찰 후보", 2))  # type: ignore[union-attr]

        result = aggregate(document, AS_OF)
        self.assertEqual(result["analysis_status"], "partial")
        self.assertFalse(result["comparison_ready"])
        self.assertEqual(result["recommendations"][0]["trend_type"], "repeated_observed")
        self.assertIn(
            "trend_windows_incomplete_no_rising_or_emerging_confirmation",
            result["limitations"],
        )

    def test_incomplete_recent_window_also_blocks_trend_confirmation(self) -> None:
        document = base_document()
        missing = snapshot(document, 7, "search_inflow")
        document["snapshots"].remove(missing)  # type: ignore[union-attr]
        for offset in (1, 2):
            snapshot(document, offset, "search_inflow")["items"].append(keyword("최근 부분 후보", 2))  # type: ignore[union-attr]

        result = aggregate(document, AS_OF)
        self.assertEqual(result["analysis_status"], "partial")
        self.assertFalse(result["comparison_ready"])
        self.assertEqual(result["recommendations"][0]["trend_type"], "repeated_observed")

    def test_today_and_older_than_comparison_window_are_ignored(self) -> None:
        document = base_document()
        document["snapshots"].extend(  # type: ignore[union-attr]
            [
                {
                    "date": AS_OF.isoformat(),
                    "surface": "search_inflow",
                    "status": "complete",
                    "items": [keyword("오늘만 있는 키워드")],
                },
                {
                    "date": (AS_OF - timedelta(days=15)).isoformat(),
                    "surface": "search_inflow",
                    "status": "complete",
                    "items": [keyword("오래된 키워드")],
                },
            ]
        )
        snapshot(document, 1, "search_inflow")["items"].append(keyword("정상 키워드"))  # type: ignore[union-attr]
        result = aggregate(document, AS_OF)
        serialized = json.dumps(result, ensure_ascii=False)
        self.assertIn("정상 키워드", serialized)
        self.assertNotIn("오늘만 있는 키워드", serialized)
        self.assertNotIn("오래된 키워드", serialized)
        self.assertIn("ignored_out_of_window_snapshots:2", result["limitations"])

    def test_business_title_is_not_keyword(self) -> None:
        document = base_document()
        document["snapshots"].append(  # type: ignore[union-attr]
            {
                "date": (AS_OF - timedelta(days=1)).isoformat(),
                "surface": "business",
                "status": "complete",
                "items": [
                    {"kind": "business_title", "text": "매출 300억, 결과는?", "list_position": 1},
                    {"kind": "business_keyword", "text": "소상공인 정책", "list_position": 2},
                ],
            }
        )
        result = aggregate(document, AS_OF)
        values = {item["keyword"] for item in result["recommendations"]}
        self.assertEqual(values, {"소상공인 정책"})
        self.assertEqual(result["title_pattern_summary"]["titles_observed"], 1)

    def test_contract_rejects_wrong_kind_and_unavailable_items(self) -> None:
        wrong = base_document()
        snapshot(wrong, 1, "main_inflow")["items"].append(keyword("잘못된 종류"))  # type: ignore[union-attr]
        with self.assertRaisesRegex(ContractError, "not allowed"):
            aggregate(wrong, AS_OF)

        unavailable = base_document()
        target = snapshot(unavailable, 1, "search_inflow")
        target["status"] = "unavailable"
        target["items"].append(keyword("있으면 안 됨"))  # type: ignore[union-attr]
        with self.assertRaisesRegex(ContractError, "must be empty"):
            aggregate(unavailable, AS_OF)

    def test_cli_writes_reproducible_json(self) -> None:
        document = base_document()
        snapshot(document, 1, "search_inflow")["items"].append(keyword("커피 분쇄도", 1))  # type: ignore[union-attr]
        script = SCRIPT_DIR / "analyze_snapshots.py"
        with tempfile.TemporaryDirectory() as temp_directory:
            root = Path(temp_directory)
            source = root / "snapshots.json"
            output = root / "pack.json"
            source.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    "-B",
                    str(script),
                    "--input",
                    str(source),
                    "--output",
                    str(output),
                    "--as-of",
                    AS_OF.isoformat(),
                    "--limit",
                    "1",
                ],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr)
            result = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(result["schema"], "naver-creator-keyword-pack/v1")
            self.assertEqual(result["recommendations"][0]["keyword"], "커피 분쇄도")


if __name__ == "__main__":
    unittest.main()
