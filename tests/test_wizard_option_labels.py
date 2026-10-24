"""Regression coverage for the two independently added question-label branches."""
from pathlib import Path
import copy
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'skills/naver-blog-wizard/scripts'
sys.path.insert(0, str(SCRIPT))
import wizard_session as wizard


class WizardOptionLabelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()

    def question(self, key, options=None):
        session = wizard.new_session(self.root)
        before = copy.deepcopy(session)
        question = wizard._question(session, key, options)
        self.assertEqual(session, before)
        self.assertEqual(question['key'], key)
        self.assertEqual(question['question_id'], f'{key}:r0')
        self.assertTrue(question['accepts_custom'])
        return question

    def test_article_type_auto_is_specific_in_public_question_flow(self):
        session = wizard.new_session(self.root, {
            'task_mode': 'new', 'topic': '선택 기준', 'audience': 'general',
            'aspect_ratios': {'cover': '1:1', 'inline': '16:9'},
        })
        before = copy.deepcopy(session)
        question = wizard.next_step(session)
        self.assertEqual(session, before)
        self.assertEqual(question['key'], 'article_type')
        self.assertEqual(question['options'][0], {
            'value': 'auto', 'label': '제목에 맞춰 자동 선택',
        })
        answered = wizard.apply_answer(session, question['question_id'], 'auto', 0)
        self.assertEqual(wizard.value(answered, 'article_type'), 'auto')
        self.assertEqual(wizard.value(answered, 'aspect_ratios'), {
            'cover': '1:1', 'inline': '16:9',
        })

    def test_aspect_ratio_default_and_clear_labels_both_survive(self):
        self.assertEqual(self.question('aspect_ratios')['options'], [
            {'value': {'cover': '1:1', 'inline': '16:9'},
             'label': '대표 1:1 · 본문 16:9'},
            {'value': {}, 'label': '비율 지정 해제(기존 기본값)'},
        ])

    def test_explicit_aspect_ratio_clear_remains_a_session_value(self):
        session = wizard.new_session(self.root, {
            'aspect_ratios': {'cover': '1:1', 'inline': '16:9'},
        })
        changed = wizard.apply_change(session, 'aspect_ratios', {}, 0)
        self.assertEqual(wizard.value(changed, 'aspect_ratios'), {})
        self.assertEqual(wizard.value(session, 'aspect_ratios'), {
            'cover': '1:1', 'inline': '16:9',
        })

    def test_requested_count_auto_retains_five_image_recommendation(self):
        options = self.question('requested_count')['options']
        self.assertEqual([o['value'] for o in options], [1, 3, 5, 'auto'])
        self.assertEqual(options[-1]['label'], '추천 구성(5장)')
        self.assertEqual(options[0]['label'], '1')

    def test_additional_requirements_none_does_not_rename_image_action_none(self):
        self.assertEqual(self.question('additional_requirements')['options'], [
            {'value': 'none', 'label': '추가 요구 없음'},
        ])
        none = next(o for o in self.question('image_action')['options']
                    if o['value'] == 'none')
        self.assertEqual(none['label'], '이미지 없음')

    def test_generic_auto_and_fallback_labels_are_unchanged(self):
        self.assertEqual(self.question('format_preset')['options'][0], {
            'value': 'auto', 'label': '자동 선택',
        })
        self.assertEqual(self.question('tone', ['friendly', 'custom-tone'])['options'], [
            {'value': 'friendly', 'label': '친근하게'},
            {'value': 'custom-tone', 'label': 'custom-tone'},
        ])

    def test_choice_order_limit_and_images_only_filter_are_unchanged(self):
        question = self.question('article_type')
        self.assertEqual([o['value'] for o in question['options']],
                         list(wizard.ENUMS['article_type'][:5]))
        session = wizard.new_session(self.root, {'task_mode': 'images-only'})
        question = wizard._question(session, 'image_action')
        self.assertNotIn('none', [o['value'] for o in question['options']])


if __name__ == '__main__':
    unittest.main()
