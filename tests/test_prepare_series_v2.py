from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/naver-series-workflow/scripts'))
import prepare_series as workflow


class SeriesPreparationV2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.inputs = self.root / 'input'
        self.inputs.mkdir()
        self.outputs = self.root / 'prepared'
        self.manifest = self.inputs / 'series.json'
        self.data = {
            'schema': 'naver-series/v2',
            'series_id': 'fixture-v2',
            'requested_episodes': [1],
            'target_blog': None,
            'requirements': {'visual_mode': 'required'},
            'episodes': [],
        }
        self.add_episode(1)
        self.save()

    def tearDown(self):
        self.temp.cleanup()

    def save(self):
        self.manifest.write_text(workflow.encoded(self.data))

    def add_episode(self, ep: int, *, chars: int = 3000, images: int = 3, roles: list[str] | None = None):
        folder = self.inputs / f'episode-{ep:02d}'
        folder.mkdir(exist_ok=True)
        roles = roles or ['cover'] + ['inline'] * max(0, images - 1)
        markers = []
        slots = []
        for index in range(images):
            name = f'image-{index + 1}.png'
            Image.new('RGB', (8, 8), (ep * 10, index * 20, 50)).save(folder / name)
            slot_id = 'cover' if index == 0 else f'section-{index}'
            markers.append(f'<!-- naver-image:{slot_id} -->')
            slots.append({
                'id': slot_id,
                'role': roles[index],
                'placement': f'본문 위치 {index + 1}',
                'purpose': f'정보 목적 {index + 1}',
                'mode': 'infographic-diagram',
                'prompt': f'테스트 프롬프트 {index + 1}',
                'alt': f'테스트 대체텍스트 {index + 1}',
                'caption': '',
                'path': f'episode-{ep:02d}/{name}',
                'status': 'approved',
            })
        article = '# 제목\n\n' + ('가' * chars) + '\n\n' + '\n\n'.join(markers) + '\n\n**태그**\n\n#정보\n'
        (folder / 'article.md').write_text(article)
        (folder / 'editorial.json').write_text(workflow.encoded({'series_id': 'fixture-v2', 'episode': ep}))
        (folder / 'slots.json').write_text(workflow.encoded({'version': 1, 'asset_root': f'episode-{ep:02d}', 'slots': slots}))
        entry = {'episode': ep, 'article': f'episode-{ep:02d}/article.md',
                 'editorial': f'episode-{ep:02d}/editorial.json',
                 'review': f'episode-{ep:02d}/review.json',
                 'image_slots': f'episode-{ep:02d}/slots.json'}
        self.data['episodes'] = [item for item in self.data['episodes'] if item['episode'] != ep]
        self.data['episodes'].append(entry)
        return folder

    def prepare(self, run='run', **kwargs):
        return workflow.prepare(self.manifest, self.inputs, self.outputs, run, **kwargs)

    def approve(self, episodes: list[int] | None = None, *, shared: bool = False):
        report = self.prepare(check=True)
        selected = episodes or [item['episode'] for item in report['episodes']]
        for item in report['episodes']:
            if item['episode'] not in selected or not item['content_revision']:
                continue
            ep = item['episode']
            checks = []
            styles = {self.data['requirements'].get('primary_style', 'expert'),
                      self.data['requirements'].get('secondary_style', 'friendly')}
            for check_id in sorted(workflow.required_review_checks(version=2, styles=styles)):
                suffix = '공유 근거입니다' if shared else f'{ep}편에서 확인했습니다'
                checks.append({'id': check_id, 'status': 'passed', 'evidence': [{
                    'location': f'{ep}편 소제목 2의 표',
                    'finding': f'{check_id} 항목의 구체 조건과 적용 범위를 {suffix}.',
                    'source_refs': ['본문 참고자료 1'] if check_id in {'factuality', 'source_integrity', 'claim_source_map'} else [],
                }]})
            review = {'schema': 'naver-review/v2', 'status': 'passed',
                      'content_revision': item['content_revision'], 'checks': checks,
                      'reviewed_by': 'synthetic-v2-test', 'reviewed_at': '2026-09-13T00:00:00+09:00'}
            (self.inputs / f'episode-{ep:02d}/review.json').write_text(workflow.encoded(review))

    def test_v2_defaults_and_pending_readiness_are_explicit(self):
        report = self.prepare(check=True)
        self.assertEqual(report['schema'], 'naver-series-prepared/v2')
        self.assertEqual(report['requirements']['primary_style'], 'expert')
        self.assertEqual(report['requirements']['secondary_style'], 'friendly')
        self.assertEqual(report['requirements']['min_body_chars'], 3000)
        self.assertEqual(report['requirements']['min_images_per_episode'], 3)
        self.assertEqual(report['requirements']['target_images_per_episode'], 5)
        item = report['episodes'][0]
        self.assertTrue(item['structure_ready'])
        self.assertTrue(item['length_ready'])
        self.assertTrue(item['visual_ready'])
        self.assertFalse(item['visual_target_met'])
        self.assertFalse(item['editorial_ready'])
        self.assertFalse(item['draft_input_ready'])

    def test_v2_rejects_weakened_or_conflicting_quality_contract(self):
        cases = [
            {'min_body_chars': 2999, 'visual_mode': 'required'},
            {'min_images_per_episode': 2, 'visual_mode': 'required'},
            {'min_images_per_episode': 4, 'target_images_per_episode': 3, 'visual_mode': 'required'},
            {'primary_style': 'expert', 'secondary_style': 'expert', 'visual_mode': 'required'},
            {'min_images_per_episode': 3, 'visual_mode': 'optional'},
        ]
        for requirements in cases:
            with self.subTest(requirements=requirements):
                self.data['requirements'] = requirements
                self.save()
                with self.assertRaises(workflow.BuildError):
                    self.prepare(check=True)

    def test_each_primary_style_resolves_documented_image_target(self):
        expected = {'expert': 5, 'story': 4, 'review': 5, 'friendly': 3,
                    'troubleshooting': 4, 'comparison': 4}
        for primary, target in expected.items():
            with self.subTest(primary=primary):
                secondary = 'friendly' if primary != 'friendly' else 'expert'
                self.data['requirements'] = {'visual_mode': 'required',
                                             'primary_style': primary, 'secondary_style': secondary}
                self.save()
                loaded = workflow.load_manifest(self.manifest, self.inputs)
                self.assertEqual(loaded['requirements']['target_images_per_episode'], target)

    def test_profile_specific_review_check_is_required(self):
        for style, check_id in workflow.PROFILE_REVIEW_CHECKS.items():
            with self.subTest(style=style):
                checks = workflow.required_review_checks(version=2, styles={style})
                self.assertIn(check_id, checks)
        self.data['requirements'].update({'primary_style': 'comparison', 'secondary_style': 'friendly'})
        self.save()
        self.approve()
        path = self.inputs / 'episode-01/review.json'
        review = json.loads(path.read_text())
        review['checks'] = [item for item in review['checks'] if item['id'] != 'symmetric_decision_criteria']
        path.write_text(workflow.encoded(review))
        result = self.prepare(check=True)['episodes'][0]
        self.assertEqual(result['status'], 'invalid_review')
        self.assertFalse(result['editorial_ready'])

    def test_v2_2999_fails_and_3000_can_become_ready(self):
        self.add_episode(1, chars=2999)
        self.save()
        report = self.prepare(check=True)
        self.assertEqual(report['episodes'][0]['status'], 'content_too_short')
        self.assertEqual(report['episodes'][0]['body_char_count'], 2999)
        self.add_episode(1, chars=3000)
        self.save()
        self.approve()
        ready = self.prepare(check=True)
        self.assertEqual(ready['status'], 'ready')
        self.assertTrue(ready['episodes'][0]['draft_input_ready'])
        self.add_episode(1, chars=3001)
        self.save()
        self.assertEqual(self.prepare(check=True)['episodes'][0]['body_char_count'], 3001)

    def test_v2_snapshot_and_status_preserve_version_and_ui_boundary(self):
        self.approve()
        self.prepare()
        metrics = json.loads((self.outputs / 'run/episode-01/content-metrics.json').read_text())
        self.assertEqual(metrics['body_char_count'], 3000)
        status = workflow.status(self.outputs / 'run')
        self.assertEqual(status['schema'], 'naver-series-status/v2')
        self.assertEqual(status['preparation'], 'ready')
        self.assertEqual(status['quality_contract'], 'full-article-v2')
        self.assertEqual(status['prepared_queue'], [1])
        self.assertTrue(status['episodes'][0]['draft_input_ready'])
        self.assertFalse(status['execution_complete'])
        self.assertFalse(status['live_complete'])
        self.assertFalse(status['ui_authorized'])

    def test_three_episode_v2_queue_is_all_or_nothing(self):
        self.add_episode(2)
        self.add_episode(3)
        self.data['requested_episodes'] = [1, 2, 3]
        self.save()
        self.approve()
        ready = self.prepare(check=True)
        self.assertEqual(ready['queue'], [1, 2, 3])
        self.assertEqual(ready['totals'], {'requested': 3, 'ready': 3, 'images': 9, 'missing': 0})
        self.add_episode(2, chars=2999)
        self.save()
        blocked = self.prepare(check=True)
        self.assertEqual(blocked['queue'], [])
        self.assertFalse(blocked['episodes'][1]['length_ready'])
        self.assertFalse(blocked['episodes'][1]['draft_input_ready'])

    def test_v2_rehashed_report_cannot_forge_readiness_flags(self):
        import hashlib
        self.approve()
        self.prepare()
        run = self.outputs / 'run'
        report_path = run / 'series-report.json'
        report = json.loads(report_path.read_text())
        report['episodes'][0]['length_ready'] = False
        report_path.write_text(workflow.encoded(report))
        snapshot_path = run / 'snapshot.json'
        snapshot = json.loads(snapshot_path.read_text())
        snapshot['files']['series-report.json'] = hashlib.sha256(report_path.read_bytes()).hexdigest()
        snapshot_path.write_text(workflow.encoded(snapshot))
        complete = run / 'complete.json'
        complete.write_text(workflow.encoded({'schema': 'naver-series-ready/v2',
            'snapshot_sha256': hashlib.sha256(snapshot_path.read_bytes()).hexdigest()}))
        with self.assertRaises(workflow.BuildError):
            workflow.status(run)

    def test_two_images_fail_and_three_distinct_roles_pass_visual_minimum(self):
        self.add_episode(1, images=2)
        self.save()
        report = self.prepare(check=True)
        self.assertEqual(report['episodes'][0]['status'], 'assets_pending')
        self.assertIn('VISUAL_MINIMUM_NOT_MET', report['episodes'][0]['error_codes'])
        self.assertIn('INLINE_IMAGES_MISSING', report['episodes'][0]['error_codes'])
        self.add_episode(1, images=3)
        self.save()
        report = self.prepare(check=True)
        self.assertTrue(report['episodes'][0]['visual_minimum_met'])
        self.assertTrue(report['episodes'][0]['visual_ready'])

    def test_zero_one_two_images_fail_and_five_reaches_expert_target(self):
        for count in (0, 1, 2):
            with self.subTest(count=count):
                self.add_episode(1, images=count)
                self.save()
                item = self.prepare(check=True)['episodes'][0]
                self.assertNotEqual(item['status'], 'ready')
                self.assertFalse(item.get('visual_minimum_met', False))
        self.add_episode(1, images=5)
        self.save()
        item = self.prepare(check=True)['episodes'][0]
        self.assertTrue(item['visual_minimum_met'])
        self.assertTrue(item['visual_target_met'])

    def test_missing_or_corrupt_v2_asset_is_not_counted_as_ready(self):
        folder = self.inputs / 'episode-01'
        (folder / 'image-2.png').unlink()
        missing = self.prepare(check=True)['episodes'][0]
        self.assertFalse(missing['visual_ready'])
        self.add_episode(1)
        (folder / 'image-2.png').write_text('not an image')
        self.save()
        corrupt = self.prepare(check=True)['episodes'][0]
        self.assertFalse(corrupt['visual_ready'])

    def test_duplicate_image_bytes_do_not_satisfy_minimum(self):
        folder = self.inputs / 'episode-01'
        (folder / 'image-2.png').write_bytes((folder / 'image-1.png').read_bytes())
        self.save()
        report = self.prepare(check=True)
        self.assertEqual(report['episodes'][0]['status'], 'assets_pending')
        self.assertIn('DUPLICATE_ASSET', report['episodes'][0]['error_codes'])
        self.assertFalse(report['episodes'][0]['visual_minimum_met'])

    def test_three_cover_roles_fail_inline_requirement(self):
        self.add_episode(1, images=3, roles=['cover', 'cover', 'cover'])
        self.save()
        report = self.prepare(check=True)
        self.assertIn('INLINE_IMAGES_MISSING', report['episodes'][0]['error_codes'])
        self.assertFalse(report['episodes'][0]['visual_ready'])

    def test_v2_review_rejects_string_and_weak_evidence(self):
        self.approve()
        path = self.inputs / 'episode-01/review.json'
        review = json.loads(path.read_text())
        review['checks'][0]['evidence'] = '포괄적 검수 완료'
        path.write_text(workflow.encoded(review))
        self.assertEqual(self.prepare(check=True)['episodes'][0]['status'], 'invalid_review')
        self.approve()
        review = json.loads(path.read_text())
        review['checks'][0]['evidence'][0]['finding'] = '짧음'
        path.write_text(workflow.encoded(review))
        result = self.prepare(check=True)['episodes'][0]
        self.assertEqual(result['status'], 'invalid_review')

    def test_reused_structured_review_evidence_across_episodes_is_rejected(self):
        self.add_episode(2)
        self.data['requested_episodes'] = [1, 2]
        self.save()
        # Build deliberately identical evidence independent of episode number.
        report = self.prepare(check=True)
        styles = {'expert', 'friendly'}
        shared_checks = [{'id': check_id, 'status': 'passed', 'evidence': [{
            'location': '모든 글 소제목 2의 표',
            'finding': f'{check_id} 항목을 같은 포괄 문장으로 검수한 기록입니다.',
            'source_refs': [],
        }]} for check_id in sorted(workflow.required_review_checks(version=2, styles=styles))]
        for item in report['episodes']:
            review = {'schema': 'naver-review/v2', 'status': 'passed',
                      'content_revision': item['content_revision'], 'checks': copy.deepcopy(shared_checks),
                      'reviewed_by': 'synthetic-v2-test', 'reviewed_at': '2026-09-13T00:00:00+09:00'}
            (self.inputs / f"episode-{item['episode']:02d}/review.json").write_text(workflow.encoded(review))
        result = self.prepare(check=True)
        self.assertEqual([item['status'] for item in result['episodes']], ['invalid_review', 'invalid_review'])
        self.assertTrue(all('REVIEW_EVIDENCE_REUSED' in item['error_codes'] for item in result['episodes']))

    def test_review_profile_requires_real_experience_basis(self):
        self.data['requirements'].update({'primary_style': 'review', 'secondary_style': 'friendly'})
        self.save()
        result = self.prepare(check=True)['episodes'][0]
        self.assertIn('EXPERIENCE_BASIS_MISSING', result['error_codes'])
        editorial = self.inputs / 'episode-01/editorial.json'
        editorial.write_text(workflow.encoded({'experience_basis': {'type': 'illustrative', 'evidence': []}}))
        result = self.prepare(check=True)['episodes'][0]
        self.assertIn('EXPERIENCE_BASIS_MISSING', result['error_codes'])
        editorial.write_text(workflow.encoded({'experience_basis': {'type': 'user_provided', 'evidence': ['사용 메모와 원본 사진']}}))
        result = self.prepare(check=True)['episodes'][0]
        self.assertNotIn('EXPERIENCE_BASIS_MISSING', result['error_codes'])

    def test_story_profile_accepts_labeled_illustrative_basis_but_not_empty_claimed_evidence(self):
        self.data['requirements'].update({'primary_style': 'story', 'secondary_style': 'friendly'})
        editorial = self.inputs / 'episode-01/editorial.json'
        editorial.write_text(workflow.encoded({'experience_basis': {'type': 'user_provided', 'evidence': []}}))
        self.save()
        self.assertIn('EXPERIENCE_BASIS_MISSING', self.prepare(check=True)['episodes'][0]['error_codes'])
        editorial.write_text(workflow.encoded({'experience_basis': {'type': 'illustrative', 'evidence': []}}))
        self.assertNotIn('EXPERIENCE_BASIS_MISSING', self.prepare(check=True)['episodes'][0]['error_codes'])

    def test_v1_remains_legacy_and_one_image_contract_is_unchanged(self):
        legacy = copy.deepcopy(self.data)
        legacy['schema'] = 'naver-series/v1'
        legacy['requirements'] = {'images_per_episode': 3, 'tag_line_max_chars': 100}
        self.data = legacy
        self.save()
        report = self.prepare(check=True)
        self.assertEqual(report['schema'], 'naver-series-prepared/v1')
        self.assertEqual(report['quality_contract'], 'legacy_ungraded')


if __name__ == '__main__':
    unittest.main()
