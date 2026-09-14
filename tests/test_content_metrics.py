from __future__ import annotations

from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'skills/naver-series-workflow/scripts'))
from content_metrics import body_metrics, visible_body_text


class ContentMetricsTests(unittest.TestCase):
    def post(self, blocks):
        return {'schema': 'naver-post/v1', 'title': '제목은 제외', 'tags': ['태그'], 'blocks': blocks}

    def test_excludes_title_tags_images_captions_and_reference_section(self):
        post = self.post([
            {'type': 'paragraph', 'text': '본문 한 줄'},
            {'type': 'image', 'alt': '아주 긴 대체텍스트', 'caption': '아주 긴 캡션'},
            {'type': 'heading', 'text': '참고자료'},
            {'type': 'paragraph', 'text': '출처 설명 https://example.com/very-long-url'},
        ])
        self.assertEqual(visible_body_text(post), '본문 한 줄')
        self.assertEqual(body_metrics(post)['body_char_count'], len('본문 한 줄'))

    def test_excludes_composed_caption_paragraph_when_supplied(self):
        post = self.post([
            {'type': 'paragraph', 'text': '본문 한 줄'},
            {'type': 'image', 'alt': '대체텍스트'},
            {'type': 'paragraph', 'text': '이해를 돕기 위한 생성 이미지입니다.'},
        ])
        self.assertEqual(
            visible_body_text(post, excluded_texts=['이해를 돕기 위한 생성 이미지입니다.']),
            '본문 한 줄',
        )

    def test_includes_public_headings_lists_tables_and_callouts(self):
        post = self.post([
            {'type': 'heading', 'text': '실전 방법'},
            {'type': 'list', 'items': [{'text': '첫째'}, {'text': '둘째'}]},
            {'type': 'table', 'columns': ['조건', '조치'], 'rows': [['빠름', '조절']]},
            {'type': 'callout', 'title': '핵심 요약', 'text': '한 번에 하나씩 바꿉니다.'},
        ])
        self.assertEqual(visible_body_text(post), '실전 방법 첫째 둘째 조건 조치 빠름 조절 핵심 요약 한 번에 하나씩 바꿉니다.')

    def test_nfkc_urls_and_whitespace_are_normalized(self):
        post = self.post([{'type': 'paragraph', 'text': 'Ａ  \r\n B https://example.com/x  C'}])
        self.assertEqual(visible_body_text(post), 'A B C')

    def test_reference_section_resumes_at_next_public_heading(self):
        post = self.post([
            {'type': 'heading', 'text': '출처'},
            {'type': 'paragraph', 'text': '제외'},
            {'type': 'heading', 'text': '다음 편 예고'},
            {'type': 'paragraph', 'text': '포함'},
        ])
        self.assertEqual(visible_body_text(post), '다음 편 예고 포함')


if __name__ == '__main__':
    unittest.main()
