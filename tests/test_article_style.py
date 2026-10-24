from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import select_article_style as style


class ArticleStyleTests(unittest.TestCase):
    def test_title_examples(self):
        for title, expected in [
            ('남이섬 단풍 절정 언제? 나무별로 시기가 달라요', 'information'),
            ('듀오링고 슈퍼 vs 무료, 뭐가 다를까', 'comparison'),
            ('파라다이스그레인, 정말 살 빠질까? 연구로 확인해 봤어요', 'expert'),
            ('집·작업실 페인트·시너 보관 수칙', 'howto'),
            ('근조화환 보낼 때 리본 문구 쓰는 순서', 'howto'),
            ('가습기 고장, 켜지지 않을 때 해결 순서', 'troubleshooting'),
            ('예약 전 확인할 체크리스트', 'checklist'),
        ]:
            with self.subTest(title=title):
                result = style.select_style(title)
                self.assertEqual(result['article_type'], expected)
                self.assertEqual(result['status'], 'ready')
                self.assertEqual(style.validate_selection(result, title), result)

    def test_semantics_can_override_hint_not_explicit_choice(self):
        intent = {'article_type': 'checklist', 'reason': '두 브랜드의 순위가 아니라 구매 전 확인 순서를 묻는 제목'}
        result = style.select_style('A vs B 구매 전 무엇부터 확인할까', intent=intent)
        self.assertEqual(result['article_type'], 'checklist')
        self.assertEqual(result['method'], 'semantic')
        explicit = style.select_style('A vs B 구매 전 무엇부터 확인할까', requested_type='expert', intent=intent)
        self.assertEqual(explicit['article_type'], 'expert')
        self.assertEqual(explicit['method'], 'explicit')

    def test_missing_experience_and_title_conflict(self):
        for title in ['내돈내산 가습기 후기', '남이섬 방문기', '세 번의 실패에서 배운 도전기']:
            result = style.select_style(title)
            self.assertEqual(result['status'], 'needs_experience')
            with self.assertRaises(style.StyleError): style.validate_selection(result, title)
        result = style.select_style('가습기 사용 후기', requested_type='information')
        self.assertEqual(result['status'], 'needs_title_revision')

    def test_other_peoples_reviews_are_not_firsthand(self):
        for title in ['가습기 후기 읽는 법', '구매 후기만 믿어도 될까', '남이섬 후기 분석, 방문 전 체크리스트',
                      '후기 쓰는 법', '실사용 비교 대신 사양으로 고르는 법']:
            result = style.select_style(title)
            self.assertNotIn(result['article_type'], {'review', 'place'})
            self.assertEqual(result['status'], 'ready')

    def test_real_experience_and_illustrative_story(self):
        basis = {'type': 'user_provided', 'evidence': ['사용자가 제공한 2주 사용 메모']}
        result = style.select_style('가습기 2주 사용 후기', experience_basis=basis)
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(result['primary_style'], 'review')
        fake = {'type': 'illustrative', 'evidence': ['공개 가정 사례: 초보자의 준비 과정']}
        self.assertEqual(style.select_style('가습기 후기', experience_basis=fake)['status'], 'needs_experience')
        self.assertEqual(style.select_style('초보자의 준비 과정', requested_type='story', experience_basis=fake)['status'], 'ready')

    def test_selection_is_bound_and_recomputed(self):
        result = style.select_style('A vs B 차이')
        with self.assertRaises(style.StyleError): style.validate_selection(result, '다른 제목')
        for key, value in [('article_type', 'review'), ('primary_style', 'expert'), ('status', 'approved'), ('outline', ['무조건 후기'])]:
            altered = copy.deepcopy(result); altered[key] = value
            with self.assertRaises(style.StyleError): style.validate_selection(altered, result['title'])
        with self.assertRaises(style.StyleError):
            style.validate_selection(result, result['title'], experience_basis={'type': 'user_provided', 'evidence': ['메모']})

    def test_invalid_inputs_and_no_mutation(self):
        for basis in [True, {}, {'type': [], 'evidence': []}, {'type': 'verified_records', 'evidence': []}, {'type': 'user_provided', 'evidence': ['']}]:
            with self.assertRaises(style.StyleError): style.select_style('제목', experience_basis=basis)
        intent = {'article_type': 'information', 'reason': '조건 안내'}
        result = style.select_style('제목', intent=intent)
        result['intent']['reason'] = '변경'
        self.assertEqual(intent['reason'], '조건 안내')
        for title in ['', None, 123]:
            with self.assertRaises(style.StyleError): style.select_style(title)
        for requested in [[], {}, True]:
            with self.assertRaises(style.StyleError): style.select_style('제목', requested_type=requested)
        with self.assertRaises(style.StyleError):
            style.select_style('제목', intent={'article_type': [], 'reason': '조건'})

    def test_real_cli_is_readonly(self):
        result = subprocess.run([sys.executable, '-B', str(ROOT/'scripts/select_article_style.py'), '--title', '무료 vs 유료 차이'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['article_type'], 'comparison')
        missing = subprocess.run([sys.executable, '-B', str(ROOT/'scripts/select_article_style.py'), '--title', '내돈내산 후기'], capture_output=True, text=True)
        self.assertEqual(missing.returncode, 1)


if __name__ == '__main__':
    unittest.main()
