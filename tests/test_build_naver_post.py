from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import unittest
from PIL import Image
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = PROJECT_ROOT / "skills" / "naver-smarteditor-drafter" / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "naver-smarteditor"
sys.path.insert(0, str(SCRIPT_DIR))

from build_naver_post import BuildError, build_post, preflight_report, run  # noqa: E402


class BuildNaverPostTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.series = self.root / "series"
        self.series.mkdir()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _markdown_fixture(self, episode: int = 3) -> Path:
        episode_dir = self.series / f"episode-{episode:02d}"
        episode_dir.mkdir(parents=True)
        target = episode_dir / f"episode-{episode:02d}.md"
        shutil.copyfile(FIXTURES / "episode-03.md", target)
        Image.new("RGB", (4, 4), "blue").save(episode_dir / "01-cover.png")
        return target

    def _args(self, **overrides: object) -> argparse.Namespace:
        values: dict[str, object] = {
            "input": None,
            "input_root": str(self.series),
            "output_root": str(self.root / "runs"),
            "run_id": "test-run",
            "project_root": str(self.root),
            "batch": True,
            "check": False,
            "force": False,
            "episode_min": None,
            "episode_max": None,
            "expected_images": 1,
            "expected_tags": 2,
        }
        values.update(overrides)
        return argparse.Namespace(**values)

    def test_markdown_preserves_order_and_styles(self) -> None:
        source = self._markdown_fixture()
        post, warnings = build_post(source, self.root)

        self.assertTrue(all("text-render fallback" in warning for warning in warnings))
        self.assertEqual(post["schema"], "naver-post/v1")
        self.assertEqual(post["episode"], 3)
        self.assertEqual(post["title"], "테스트 사진 정리 가이드")
        self.assertEqual(post["tags"], ["사진정리", "테스트가이드"])
        self.assertEqual([block["id"] for block in post["blocks"]], [f"b{i:03d}" for i in range(1, len(post["blocks"]) + 1)])

        headings = [block for block in post["blocks"] if block["type"] == "heading"]
        self.assertEqual(headings[0]["style"], "quotation_bubble")
        self.assertEqual(headings[-1]["style"], "subtitle")
        summary = next(block for block in post["blocks"] if block.get("variant") == "summary")
        self.assertEqual(summary["style"], "quotation_line")

        paragraph = next(block for block in post["blocks"] if block.get("text") == "본문의 중요한 문장을 설명합니다.")
        self.assertEqual(paragraph["marks"], [{"start": 4, "end": 10, "type": "bold"}])
        table = next(block for block in post["blocks"] if block["type"] == "table")
        self.assertEqual(table["columns"], ["기준", "확인 내용"])
        self.assertEqual(table["rows"][1], ["기록성", "다시 찍을 수 있는지 확인"])

    def test_structured_input_normalizes_extended_blocks(self) -> None:
        source = self.root / "structured-input.json"
        shutil.copyfile(FIXTURES / "structured-input.json", source)
        post, warnings = build_post(source, self.root)

        self.assertTrue(all("text-render fallback" in warning for warning in warnings))
        self.assertEqual(post["episode"], 9)
        self.assertEqual([block["type"] for block in post["blocks"]], ["heading", "list", "table", "list", "callout"])
        self.assertEqual(post["blocks"][0]["style"], "quotation_bubble")
        self.assertEqual(post["blocks"][1]["style"], "ordered")
        self.assertEqual(post["blocks"][2]["columns"], ["항목", "설명"])
        self.assertEqual(post["blocks"][3]["style"], "checklist")
        self.assertEqual(post["blocks"][4]["style"], "quotation_line")

    def test_fenced_json_is_accepted_but_prompts_are_not_images(self) -> None:
        source = self.root / "input.txt"
        source.write_text(
            "```json\n" + json.dumps({"title": "제목", "content": [{"type": "paragraph", "text": "본문"}], "seo_tags": ["태그"], "image_prompts": [{"prompt": "x"}]}, ensure_ascii=False) + "\n```",
            encoding="utf-8",
        )
        post, warnings = build_post(source, self.root)
        self.assertEqual(sum(block["type"] == "image" for block in post["blocks"]), 0)
        self.assertIn("image_prompts are not uploadable image blocks", warnings)

    def test_rejects_missing_or_duplicate_h1(self) -> None:
        missing = self.root / "missing.md"
        missing.write_text("본문", encoding="utf-8")
        with self.assertRaisesRegex(BuildError, "exactly one H1"):
            build_post(missing, self.root)

        duplicate = self.root / "duplicate.md"
        duplicate.write_text("# 하나\n\n# 둘\n", encoding="utf-8")
        with self.assertRaisesRegex(BuildError, "found 2"):
            build_post(duplicate, self.root)

    def test_rejects_missing_image_and_path_escape(self) -> None:
        missing = self.root / "missing-image.md"
        missing.write_text("# 제목\n\n![누락](missing.png)\n", encoding="utf-8")
        with self.assertRaisesRegex(BuildError, "does not exist"):
            build_post(missing, self.root)

        outside = self.root.parent / "outside.png"
        outside.write_bytes(b"outside")
        escaped = self.root / "escaped.json"
        escaped.write_text(json.dumps({"title": "제목", "blocks": [{"type": "image", "path": str(outside), "alt": "밖"}]}), encoding="utf-8")
        with self.assertRaisesRegex(BuildError, "escapes project root"):
            build_post(escaped, self.root)

    def test_rejects_duplicate_and_long_tags(self) -> None:
        duplicate = self.root / "duplicate-tags.json"
        duplicate.write_text(json.dumps({"title": "제목", "content": [], "tags": ["중복", "#중복"]}), encoding="utf-8")
        with self.assertRaisesRegex(BuildError, "duplicate tag"):
            build_post(duplicate, self.root)

        long_tags = self.root / "long-tags.json"
        long_tags.write_text(json.dumps({"title": "제목", "content": [], "tags": ["가" * 101]}, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(BuildError, "exceeds 100"):
            build_post(long_tags, self.root)

    def test_preflight_enforces_expected_counts(self) -> None:
        source = self._markdown_fixture()
        post, warnings = build_post(source, self.root)
        report = preflight_report(post, source, warnings, expected_images=5, expected_tags=6)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(len(report["errors"]), 2)

    def test_batch_discovers_episode_order_and_writes_reports(self) -> None:
        self._markdown_fixture(5)
        self._markdown_fixture(3)
        self._markdown_fixture(4)
        report = run(self._args(episode_min=3, episode_max=5))

        self.assertEqual(report["queue"], [3, 4, 5])
        self.assertEqual(report["totals"]["prepared"], 3)
        run_dir = self.root / "runs" / "test-run"
        self.assertTrue((run_dir / "run-report.json").is_file())
        self.assertTrue((run_dir / "episode-03" / "naver-post.json").is_file())
        saved = json.loads((run_dir / "run-report.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["status"], "prepared")

    def test_check_mode_writes_nothing(self) -> None:
        self._markdown_fixture()
        report = run(self._args(check=True))
        self.assertEqual(report["status"], "prepared")
        self.assertFalse((self.root / "runs").exists())

    def test_single_input_without_episode_uses_source_name_in_queue(self) -> None:
        source = self.root / "standalone.json"
        source.write_text(
            json.dumps({"title": "단일 원고", "content": [{"type": "paragraph", "text": "본문"}]}, ensure_ascii=False),
            encoding="utf-8",
        )
        report = run(
            self._args(
                input=str(source),
                input_root=None,
                batch=False,
                check=True,
                expected_images=0,
                expected_tags=0,
            )
        )
        self.assertEqual(report["queue"], ["standalone"])

    def test_existing_run_requires_force(self) -> None:
        self._markdown_fixture()
        run(self._args())
        with self.assertRaisesRegex(BuildError, "new --run-id"):
            run(self._args())
        rerun = run(self._args(force=True))
        self.assertEqual(rerun["status"], "prepared")

    def test_batch_isolates_failed_episode(self) -> None:
        self._markdown_fixture(3)
        failed = self.series / "episode-04"
        failed.mkdir()
        (failed / "episode-04.md").write_text("본문만 있음", encoding="utf-8")
        report = run(self._args())
        self.assertEqual(report["status"], "preflight_failed")
        self.assertEqual(report["queue"], [])
        self.assertEqual(report["prepared_queue"], [3])
        self.assertEqual(report["totals"]["failed"], 1)
        self.assertTrue((self.root / "runs" / "test-run" / "episode-03" / "naver-post.json").is_file())


if __name__ == "__main__":
    unittest.main()
