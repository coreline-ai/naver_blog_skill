from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/naver-smarteditor-drafter/scripts'))
from build_naver_post import BuildError, run
from verify_prepared_content import verify


class SmartEditorLengthEnforcementTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.sources = self.root / 'inputs'
        self.sources.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, ep, text):
        p = self.sources / f'episode-{ep:02}.md'
        p.write_text('# 제목\n\n' + text + '\n', encoding='utf-8')
        return p

    def args(self, **overrides):
        base = dict(input=None, input_root=str(self.sources), output_root=str(self.root / 'runs'),
                    project_root=str(self.root), run_id='test', batch=True, check=False, force=False,
                    episode_min=None, episode_max=None, expected_images=None, expected_tags=None)
        base.update(overrides)
        return argparse.Namespace(**base)

    def test_default_full_2999_rejected_3000_accepted(self):
        self.write(1, '가' * 2999)
        short = run(self.args(check=True))
        self.assertEqual(short['episodes'][0]['error_code'], 'BODY_TOO_SHORT')
        self.assertIn('2999', short['episodes'][0]['error'])
        self.assertEqual(short['queue'], [])
        self.write(1, '가' * 3000)
        ready = run(self.args())
        self.assertEqual(ready['episodes'][0]['body_char_count'], 3000)
        self.assertTrue(ready['episodes'][0]['length_ready'])
        self.assertFalse(ready['ui_executable'])
        self.assertEqual(verify(self.root / 'runs/test', self.root)['status'], 'passed')

    def test_short_and_exact_need_explicit_scope_and_preserve_original(self):
        path = self.write(1, '짧은 본문')
        original = path.read_bytes()
        for mode in ('explicit', 'preserve'):
            with self.subTest(mode=mode), self.assertRaises(BuildError):
                run(self.args(check=True, content_mode=mode))
            report = run(self.args(check=True, content_mode=mode, scope_evidence='사용자가 원문 그대로 요청'))
            self.assertEqual(report['status'], 'prepared')
            self.assertIsNone(report['episodes'][0]['length_ready'])
        self.assertEqual(path.read_bytes(), original)
        result = run(self.args(check=True, content_mode='explicit', scope_evidence='최소 10자 요청', explicit_minimum=10))
        self.assertEqual(result['episodes'][0]['error_code'], 'BODY_TOO_SHORT')

    def test_multiple_articles_short_one_blocks_entire_queue(self):
        self.write(1, '가' * 3000)
        self.write(2, '나' * 2999)
        report = run(self.args())
        self.assertEqual(report['queue'], [])
        self.assertEqual(report['prepared_queue'], [1])
        self.assertEqual(report['episodes'][1]['error_code'], 'BODY_TOO_SHORT')
        self.assertFalse((self.root / 'runs/test/complete.json').exists())
        with self.assertRaises((BuildError, OSError)):
            verify(self.root / 'runs/test', self.root)

    def test_stale_source_or_image_invalidates_snapshot(self):
        img = self.sources / 'cover.png'
        Image.new('RGB', (4, 4), 'blue').save(img)
        path = self.write(1, '![대표](cover.png)\n\n' + '가' * 3000)
        run(self.args())
        self.assertEqual(verify(self.root / 'runs/test', self.root)['status'], 'passed')
        path.write_text(path.read_text() + '\n변경\n')
        with self.assertRaises(BuildError) as raised:
            verify(self.root / 'runs/test', self.root)
        self.assertEqual(raised.exception.code, 'SOURCE_CHANGED')
        path.write_text(path.read_text().replace('\n변경\n', ''))
        Image.new('RGB', (4, 4), 'red').save(img)
        with self.assertRaises(BuildError) as raised:
            verify(self.root / 'runs/test', self.root)
        self.assertEqual(raised.exception.code, 'ASSET_CHANGED')

    def test_reference_and_image_alt_do_not_fill_body(self):
        img = self.sources / 'cover.png'
        Image.new('RGB', (4, 4), 'blue').save(img)
        self.write(1, '![' + '설명' * 2000 + '](cover.png)\n\n본문\n\n## 참고자료\n\n' + '자료' * 2000)
        report = run(self.args(check=True))
        self.assertEqual(report['episodes'][0]['error_code'], 'BODY_TOO_SHORT')
        self.assertIn('found 2', report['episodes'][0]['error'])

    def test_identified_caption_excluded_and_snapshot_tamper_detected(self):
        img = self.sources / 'cover.png'
        Image.new('RGB', (4, 4), 'blue').save(img)
        self.write(1, '![대표](cover.png)\n\n사진 설명\n\n' + '가' * 3000)
        report = run(self.args(exclude_block_id=['b002']))
        self.assertEqual(report['episodes'][0]['body_char_count'], 3000)
        folder = self.root / 'runs/test'
        self.assertEqual(verify(folder, self.root)['status'], 'passed')
        marker = json.loads((folder / 'complete.json').read_text())
        preflight = next(name for name in marker['files'] if name.endswith('/preflight-report.json'))
        (folder / preflight).write_text('{}')
        with self.assertRaises(BuildError) as raised:
            verify(folder, self.root)
        self.assertEqual(raised.exception.code, 'SNAPSHOT_CHANGED')


if __name__ == '__main__':
    unittest.main()
