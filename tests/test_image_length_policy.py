from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from build_blog_image_prompts import build_plan
from post_contract import BuildError


class ImageLengthPolicyTests(unittest.TestCase):
    def test_generation_requires_scope_and_checks_full_without_blocking_preserve(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            article = root / 'article.md'
            article.write_text('# 제목\n\n짧은 본문\n', encoding='utf-8')
            original = article.read_bytes()
            request = {'schema': 'naver-blog-image-request/v1', 'article': {'path': 'article.md'}}
            with self.assertRaises(BuildError) as missing:
                build_plan(request, root, operation='generate-and-compose')
            self.assertEqual(missing.exception.code, 'BODY_LENGTH_POLICY_REQUIRED')
            request['body_length_policy'] = 'full'
            with self.assertRaises(BuildError) as short:
                build_plan(request, root, operation='generate-and-compose')
            self.assertEqual(short.exception.code, 'CONTENT_TOO_SHORT')
            request['body_length_policy'] = 'preserve'
            self.assertEqual(build_plan(request, root, operation='generate-and-compose')['body_length_gate']['status'], 'not_applicable')
            self.assertEqual(article.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
