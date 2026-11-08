from __future__ import annotations
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from check_blog_body_length import check_length
sys.path.insert(0, str(ROOT / 'skills/naver-blog-wizard/scripts'))
import wizard_session
import wizard_artifacts
import build_blog_image_prompts
from post_contract import BuildError


class BlogBodyLengthGateTests(unittest.TestCase):
    def post(self, text):
        return {'schema': 'naver-post/v1', 'title': '제목', 'tags': ['태그'], 'blocks': [
            {'id': 'a', 'type': 'paragraph', 'text': text},
            {'id': 'b', 'type': 'image', 'alt': '이미지는 세지 않음'},
            {'id': 'c', 'type': 'heading', 'text': '참고자료'},
            {'id': 'd', 'type': 'paragraph', 'text': '출처' * 4000},
        ]}

    def test_full_enforces_exact_threshold(self):
        self.assertEqual(check_length(self.post('가' * 2999), mode='full')['shortfall'], 1)
        self.assertEqual(check_length(self.post('가' * 2999), mode='full')['status'], 'failed')
        self.assertEqual(check_length(self.post('가' * 3000), mode='full')['status'], 'passed')

    def test_explicit_short_and_existing_preserve_are_not_blocked(self):
        self.assertEqual(check_length(self.post('짧은 글'), mode='explicit')['status'], 'measured')
        self.assertEqual(check_length(self.post('짧은 글'), mode='preserve')['status'], 'not_applicable')
        self.assertEqual(check_length(self.post('짧은 글'), mode='explicit', minimum=30)['status'], 'failed')
        with self.assertRaises(ValueError):
            check_length(self.post('글'), mode='full', minimum=1)

    def test_excluded_caption_is_only_excluded_by_id(self):
        post = {'blocks': [{'id':'one','type':'paragraph','text':'같은 말'},
                           {'id':'two','type':'paragraph','text':'같은 말'}]}
        self.assertEqual(check_length(post, mode='explicit', excluded_block_ids=('two',))['body_char_count'], 4)

    def test_cli_does_not_mutate_source_and_reports_sha(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / 'article.md'
            p.write_text('# 제목\n\n<!-- naver-image:cover -->\n\n짧은 본문\n\n## 참고자료\n\n출처\n', encoding='utf-8')
            before = p.read_bytes()
            cmd = [sys.executable, str(ROOT/'scripts/check_blog_body_length.py'), '--project-root', td, '--input', str(p)]
            fail = subprocess.run(cmd + ['--mode','full'], capture_output=True, text=True)
            self.assertEqual(fail.returncode, 1, fail.stderr)
            self.assertEqual(json.loads(fail.stdout)['body_char_count'], len('짧은 본문'))
            self.assertEqual(p.read_bytes(), before)
            preserve = subprocess.run(cmd + ['--mode','preserve'], capture_output=True, text=True)
            self.assertEqual(preserve.returncode, 0, preserve.stderr)
            self.assertEqual(json.loads(preserve.stdout)['status'], 'not_applicable')
            self.assertEqual(p.read_bytes(), before)

    def test_wizard_registration_enforces_default_but_preserves_explicit_and_existing(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            article = root / 'article.md'
            article.write_text('# 목도리 선택\n\n짧은 본문\n', encoding='utf-8')
            initial = dict(task_mode='new', topic='목도리 선택', audience='general',
                           article_type='information', tone='plain', format_preset='auto')
            default_session = wizard_session.new_session(root, initial)
            with self.assertRaises(BuildError) as error:
                wizard_artifacts.register_article(article, root, session=default_session)
            self.assertEqual(error.exception.code, 'CONTENT_TOO_SHORT')
            explicit_session = wizard_session.new_session(root, {**initial, 'length':'short'})
            actual = wizard_artifacts.register_article(article, root, session=explicit_session)
            self.assertEqual(actual['length_gate']['status'], 'measured')
            existing = wizard_session.new_session(root, {'task_mode':'images-only','source_article':str(article)})
            actual = wizard_artifacts.register_article(article, root, session=existing)
            self.assertEqual(actual['length_gate']['status'], 'not_applicable')
            self.assertEqual(article.read_text(encoding='utf-8'), '# 목도리 선택\n\n짧은 본문\n')

    def test_image_prompt_handoff_enforces_selected_policy(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td).resolve()
            source = root / 'article.md'
            source.write_text('# 제목\n\n짧은 본문입니다.\n', encoding='utf-8')
            request = {'schema':'naver-blog-image-request/v1', 'article':{'path':'article.md'},
                       'body_length_policy':'full'}
            with self.assertRaises(BuildError) as error:
                build_blog_image_prompts.build_plan(request, root)
            self.assertEqual(error.exception.code, 'CONTENT_TOO_SHORT')
            request['body_length_policy'] = 'explicit'
            self.assertEqual(build_blog_image_prompts.build_plan(request, root)['body_length_gate']['status'], 'measured')
            request['body_length_policy'] = 'preserve'
            self.assertEqual(build_blog_image_prompts.build_plan(request, root)['body_length_gate']['status'], 'not_applicable')
            source.write_text('# 제목\n\n' + '가'*3000 + '\n', encoding='utf-8')
            request['body_length_policy'] = 'full'
            self.assertEqual(build_blog_image_prompts.build_plan(request, root)['body_length_gate']['status'], 'passed')


if __name__ == '__main__':
    unittest.main()
