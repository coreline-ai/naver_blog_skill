from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parents[1] / "skills/naver-creator-keyword-recommender/scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from analyze_home_titles import ContractError, aggregate  # noqa: E402


def title(text: str, position: int) -> dict[str, object]:
    return {"kind": "home_title", "text": text, "list_position": position}


def base_document(page_end: int = 10, items_per_page: int = 10) -> dict[str, object]:
    pages: list[dict[str, object]] = []
    for page in range(1, page_end + 1):
        items = [
            title(f"{page}페이지 {position}번째 생활 정리 방법", position)
            for position in range(1, items_per_page + 1)
        ]
        pages.append({"page": page, "status": "complete", "items": items})
    return {
        "schema": "naver-blog-home-snapshot/v1",
        "captured_at": "2026-09-13T10:30:00+09:00",
        "source": {"directory_no": 0, "group_id": 0, "page_start": 1, "page_end": page_end},
        "pages": pages,
    }


class BlogHomeTitleAnalyzerTests(unittest.TestCase):
    def test_complete_ten_pages_aggregate_without_raw_titles(self) -> None:
        document = base_document()
        document["pages"][0]["items"][0] = title(  # type: ignore[index]
            '"4개월 만에 -78%? 계좌 박살 원인 확인"', 1
        )

        result = aggregate(document)

        self.assertEqual(result["analysis_status"], "complete")
        self.assertEqual(result["coverage"]["requested_pages"], 10)
        self.assertEqual(result["coverage"]["complete_pages"], 10)
        self.assertEqual(result["titles_observed"], 100)
        self.assertEqual(result["titles_unique"], 100)
        pattern_names = {item["name"] for item in result["patterns"]}
        self.assertTrue({"number", "direct_quote", "question", "howto_review"}.issubset(pattern_names))
        sensitivity_names = {item["name"] for item in result["sensitivity_flags"]}
        self.assertTrue({"sensational", "financial"}.issubset(sensitivity_names))
        self.assertNotIn("계좌 박살 원인 확인", json.dumps(result, ensure_ascii=False))
        self.assertNotIn("recommendations", result)

    def test_missing_and_partial_pages_are_not_complete(self) -> None:
        document = base_document()
        document["pages"].pop()  # type: ignore[union-attr]
        document["pages"][4]["status"] = "partial"  # type: ignore[index]
        document["pages"][4]["reason"] = "viewport_truncated"  # type: ignore[index]

        result = aggregate(document)

        self.assertEqual(result["analysis_status"], "partial")
        self.assertEqual(result["coverage"]["missing_pages"], [10])
        self.assertEqual(result["coverage"]["partial_pages"], 1)
        self.assertIn("one_or_more_requested_pages_missing", result["limitations"])
        self.assertIn("one_or_more_pages_incomplete", result["limitations"])

    def test_duplicate_titles_keep_observed_and_unique_counts_separate(self) -> None:
        document = base_document(page_end=2, items_per_page=2)
        duplicate = "같은 제목 3가지"
        document["pages"][0]["items"][0] = title(duplicate, 1)  # type: ignore[index]
        document["pages"][1]["items"][0] = title("  같은   제목 3가지  ", 1)  # type: ignore[index]

        result = aggregate(document)

        self.assertEqual(result["titles_observed"], 4)
        self.assertEqual(result["titles_unique"], 3)
        self.assertEqual(result["pattern_denominator"], "unique_titles")
        self.assertIn("duplicate_titles_removed_from_pattern_denominator", result["limitations"])

    def test_unavailable_document_has_no_invented_statistics(self) -> None:
        document = base_document(page_end=1)
        document["pages"][0] = {  # type: ignore[index]
            "page": 1,
            "status": "unavailable",
            "reason": "service_error",
            "items": [],
        }

        result = aggregate(document)

        self.assertEqual(result["analysis_status"], "unavailable")
        self.assertEqual(result["titles_observed"], 0)
        self.assertEqual(result["length"], {"average": 0.0, "minimum": 0, "maximum": 0})
        self.assertEqual(result["patterns"], [])

    def test_contract_rejects_contamination_and_invalid_page_data(self) -> None:
        wrong_kind = base_document(page_end=1)
        wrong_kind["pages"][0]["items"][0]["kind"] = "hot_topic_title"  # type: ignore[index]
        with self.assertRaisesRegex(ContractError, "kind must be 'home_title'"):
            aggregate(wrong_kind)

        duplicate_page = base_document(page_end=1)
        duplicate_page["pages"].append(duplicate_page["pages"][0])  # type: ignore[index,union-attr]
        with self.assertRaisesRegex(ContractError, "duplicate page"):
            aggregate(duplicate_page)

        duplicate_position = base_document(page_end=1)
        duplicate_position["pages"][0]["items"][1]["list_position"] = 1  # type: ignore[index]
        with self.assertRaisesRegex(ContractError, "duplicate list_position"):
            aggregate(duplicate_position)

        unknown_field = base_document(page_end=1)
        unknown_field["pages"][0]["items"][0]["href"] = "https://example.com"  # type: ignore[index]
        with self.assertRaisesRegex(ContractError, "unknown fields"):
            aggregate(unknown_field)

        invalid_time = base_document(page_end=1)
        invalid_time["captured_at"] = "오늘 오전"
        with self.assertRaisesRegex(ContractError, "ISO 8601"):
            aggregate(invalid_time)

    def test_cli_writes_reproducible_pattern_pack(self) -> None:
        document = base_document(page_end=2, items_per_page=2)
        script = SCRIPT_DIR / "analyze_home_titles.py"
        with tempfile.TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            source = root / "home-snapshot.json"
            first = root / "first.json"
            second = root / "second.json"
            source.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

            for output in (first, second):
                completed = subprocess.run(
                    [sys.executable, "-B", str(script), "--input", str(source), "--output", str(output)],
                    check=False,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)

            self.assertEqual(first.read_bytes(), second.read_bytes())
            result = json.loads(first.read_text(encoding="utf-8"))
            self.assertEqual(result["schema"], "naver-blog-home-pattern-pack/v1")


if __name__ == "__main__":
    unittest.main()
