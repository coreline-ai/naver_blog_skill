from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from insert_article_images import CompositionError, compose_article  # noqa: E402


class InsertArticleImagesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.assets = self.root / "assets" / "post"
        self.assets.mkdir(parents=True)
        (self.assets / "01-cover.png").write_bytes(b"cover")
        (self.assets / "02-detail (final).png").write_bytes(b"detail")
        self.article = self.root / "article.md"
        self.manifest = self.root / "manifest.json"
        self.output = self.root / "article-with-images.md"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _slot(
        self,
        slot_id: str,
        path: str,
        *,
        role: str = "inline",
        alt: str = "설명 이미지",
        caption: str = "",
        status: str = "approved",
    ) -> dict[str, str]:
        return {
            "id": slot_id,
            "role": role,
            "placement": "관련 문단 뒤",
            "purpose": "문맥 설명",
            "mode": "photorealistic-natural",
            "prompt": "자연스러운 편집 사진",
            "alt": alt,
            "caption": caption,
            "path": path,
            "status": status,
        }

    def _write_manifest(self, slots: list[dict[str, str]]) -> None:
        self.manifest.write_text(
            json.dumps(
                {
                    "version": 1,
                    "asset_root": "assets/post",
                    "slots": slots,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _compose(self, *, force: bool = False) -> int:
        return compose_article(
            self.article,
            self.manifest,
            self.output,
            force=force,
            root=self.root,
        )

    def test_inserts_multiple_slots_in_order(self) -> None:
        self.article.write_text(
            "# 제목\n\n<!-- naver-image:cover -->\n\n## 설명\n\n<!-- naver-image:detail -->\n",
            encoding="utf-8",
        )
        self._write_manifest(
            [
                self._slot(
                    "cover",
                    "assets/post/01-cover.png",
                    role="cover",
                    alt="퇴근 후 정보를 확인하는 직장인",
                    caption="이해를 돕기 위한 이미지입니다.",
                ),
                self._slot("detail", "assets/post/02-detail (final).png"),
            ]
        )

        self.assertEqual(self._compose(), 2)
        result = self.output.read_text(encoding="utf-8")
        self.assertIn(
            "![퇴근 후 정보를 확인하는 직장인](<assets/post/01-cover.png>)",
            result,
        )
        self.assertIn("*이해를 돕기 위한 이미지입니다.*", result)
        self.assertIn("![설명 이미지](<assets/post/02-detail (final).png>)", result)
        self.assertNotIn("naver-image:", result)

    def test_empty_caption_adds_no_caption_block(self) -> None:
        self.article.write_text("<!-- naver-image:cover -->\n", encoding="utf-8")
        self._write_manifest(
            [self._slot("cover", "assets/post/01-cover.png", role="cover")]
        )

        self._compose()
        self.assertEqual(
            self.output.read_text(encoding="utf-8"),
            "![설명 이미지](<assets/post/01-cover.png>)\n",
        )

    def test_escapes_korean_alt_and_caption_markdown(self) -> None:
        self.article.write_text("<!-- naver-image:detail -->", encoding="utf-8")
        self._write_manifest(
            [
                self._slot(
                    "detail",
                    "assets/post/02-detail (final).png",
                    alt="장점과 단점] 비교",
                    caption="개인별 *차이*와 _상황_을 확인합니다.",
                )
            ]
        )

        self._compose()
        result = self.output.read_text(encoding="utf-8")
        self.assertIn("장점과 단점\\] 비교", result)
        self.assertIn("\\*차이\\*", result)
        self.assertIn("\\_상황\\_", result)

    def test_rejects_duplicate_manifest_ids(self) -> None:
        self.article.write_text("<!-- naver-image:cover -->", encoding="utf-8")
        slot = self._slot("cover", "assets/post/01-cover.png", role="cover")
        self._write_manifest([slot, dict(slot)])

        with self.assertRaisesRegex(CompositionError, "Duplicate manifest slot ID"):
            self._compose()

    def test_rejects_duplicate_article_markers(self) -> None:
        self.article.write_text(
            "<!-- naver-image:cover -->\n<!-- naver-image:cover -->",
            encoding="utf-8",
        )
        self._write_manifest(
            [self._slot("cover", "assets/post/01-cover.png", role="cover")]
        )

        with self.assertRaisesRegex(CompositionError, "Duplicate article marker ID"):
            self._compose()

    def test_rejects_marker_without_manifest_slot(self) -> None:
        self.article.write_text(
            "<!-- naver-image:cover -->\n<!-- naver-image:detail -->",
            encoding="utf-8",
        )
        self._write_manifest(
            [self._slot("cover", "assets/post/01-cover.png", role="cover")]
        )

        with self.assertRaisesRegex(CompositionError, "markers without manifest slots: detail"):
            self._compose()

    def test_rejects_manifest_slot_without_marker(self) -> None:
        self.article.write_text("<!-- naver-image:cover -->", encoding="utf-8")
        self._write_manifest(
            [
                self._slot("cover", "assets/post/01-cover.png", role="cover"),
                self._slot("detail", "assets/post/02-detail (final).png"),
            ]
        )

        with self.assertRaisesRegex(CompositionError, "manifest slots without markers: detail"):
            self._compose()

    def test_rejects_manifest_order_mismatch(self) -> None:
        self.article.write_text(
            "<!-- naver-image:cover -->\n<!-- naver-image:detail -->",
            encoding="utf-8",
        )
        self._write_manifest(
            [
                self._slot("detail", "assets/post/02-detail (final).png"),
                self._slot("cover", "assets/post/01-cover.png", role="cover"),
            ]
        )

        with self.assertRaisesRegex(CompositionError, "slot order"):
            self._compose()

    def test_rejects_missing_image(self) -> None:
        self.article.write_text("<!-- naver-image:missing -->", encoding="utf-8")
        self._write_manifest(
            [self._slot("missing", "assets/post/99-missing.png")]
        )

        with self.assertRaisesRegex(CompositionError, "does not exist"):
            self._compose()

    def test_rejects_path_outside_asset_root(self) -> None:
        outside = self.root / "outside.png"
        outside.write_bytes(b"outside")
        self.article.write_text("<!-- naver-image:outside -->", encoding="utf-8")
        self._write_manifest([self._slot("outside", "outside.png")])

        with self.assertRaisesRegex(CompositionError, "must stay inside asset_root"):
            self._compose()

    def test_rejects_parent_traversal(self) -> None:
        self.article.write_text("<!-- naver-image:outside -->", encoding="utf-8")
        self._write_manifest([self._slot("outside", "assets/post/../post/01-cover.png")])

        with self.assertRaisesRegex(CompositionError, "must not contain"):
            self._compose()

    def test_rejects_unapproved_slot(self) -> None:
        self.article.write_text("<!-- naver-image:cover -->", encoding="utf-8")
        self._write_manifest(
            [
                self._slot(
                    "cover",
                    "assets/post/01-cover.png",
                    role="cover",
                    status="planned",
                )
            ]
        )

        with self.assertRaisesRegex(CompositionError, "is not approved"):
            self._compose()

    def test_existing_output_requires_force(self) -> None:
        self.article.write_text("<!-- naver-image:cover -->", encoding="utf-8")
        self._write_manifest(
            [self._slot("cover", "assets/post/01-cover.png", role="cover")]
        )
        self.output.write_text("old", encoding="utf-8")

        with self.assertRaisesRegex(CompositionError, "use --force"):
            self._compose()
        self.assertEqual(self.output.read_text(encoding="utf-8"), "old")

        self.assertEqual(self._compose(force=True), 1)
        self.assertNotEqual(self.output.read_text(encoding="utf-8"), "old")

    def test_failure_preserves_article_and_existing_output(self) -> None:
        original_article = "# 원본\n\n<!-- naver-image:missing -->\n"
        self.article.write_text(original_article, encoding="utf-8")
        self._write_manifest(
            [self._slot("missing", "assets/post/99-missing.png")]
        )
        self.output.write_text("stable output", encoding="utf-8")

        with self.assertRaises(CompositionError):
            self._compose(force=True)

        self.assertEqual(self.article.read_text(encoding="utf-8"), original_article)
        self.assertEqual(self.output.read_text(encoding="utf-8"), "stable output")


if __name__ == "__main__":
    unittest.main()
