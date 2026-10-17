"""Presentation checks are not factual review or live SmartEditor tests."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS=Path(__file__).resolve().parents[1]/'skills/naver-smarteditor-drafter/scripts'
sys.path.insert(0,str(SCRIPTS))
from build_naver_post import build_post, preflight_report, RENDER_POLICY
from post_contract import BuildError, validate_link_url, validate_marks
from presentation_quality import review_presentation

class PresentationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.source=self.root/'article.md'
    def tearDown(self): self.tmp.cleanup()
    def build(self,body):
        self.source.write_text('# 제목\n\n'+body)
        return build_post(self.source,self.root)
    def test_newlines_links_bold_and_unicode_preserved(self):
        original='첫 줄\n둘째 줄\n\n## 참고자료\n\n😀 [**공식 자료**](https://example.org/a?q=1&n=2)'
        post,w=self.build(original)
        self.assertEqual(post['blocks'][0]['text'],'첫 줄\n둘째 줄')
        last=post['blocks'][-1]
        self.assertEqual(last['text'],'😀 공식 자료')
        self.assertEqual(last['marks'],[{'type':'link','start':2,'end':7,'url':'https://example.org/a?q=1&n=2'},
                                      {'type':'bold','start':2,'end':7}])
        self.assertEqual(preflight_report(post,self.source,w)['status'],'passed')
        self.assertEqual(self.source.read_text(),'# 제목\n\n'+original)
        self.assertEqual(RENDER_POLICY,'smarteditor-layout/v2')
    def test_bold_containing_link(self):
        post,_=self.build('**참고 [출처](https://example.org)**')
        self.assertEqual(post['blocks'][0]['text'],'참고 출처')
        self.assertEqual(post['blocks'][0]['marks'][0]['start'],3)
    def test_unsafe_urls(self):
        for url in ['javascript:alert(1)','data:text/html,bad','file:///tmp/a','https://user:pass@example.org',
                    'https://example.org:bad','https://example.org/a b','https://example.org/\n','https:///missing']:
            with self.subTest(url=url),self.assertRaises(BuildError):validate_link_url(url)
        self.assertEqual(validate_link_url('https://example.org/a?b=1#c'),'https://example.org/a?b=1#c')
    def test_link_mark_shape_and_bounds(self):
        for mark in [{'type':'link','start':0,'end':2}, {'type':'link','start':0,'end':99,'url':'https://example.org'},
                     {'type':'link','start':0,'end':2,'url':'https://example.org','extra':True}]:
            with self.subTest(mark=mark),self.assertRaises(BuildError):validate_marks({'text':'자료','marks':[mark]})
    def test_source_placement_and_duplicate_check(self):
        post,w=self.build('[공식](https://example.org/a)\n\n## 참고자료\n\n[다시](https://EXAMPLE.org/a)')
        self.assertEqual({i['code'] for i in review_presentation(post)['issues']},{'INLINE_SOURCE_LINK','DUPLICATE_SOURCE_LINK'})
        self.assertEqual({i['code'] for i in review_presentation(post,source_placement='inline')['issues']},{'DUPLICATE_SOURCE_LINK'})
        before=copy.deepcopy(post);review_presentation(post);self.assertEqual(post,before)
    def test_raw_urls_and_nonterminal_refs_stop_preflight(self):
        post,w=self.build('본문 https://example.org\n\n## 참고자료\n\n[공식](https://example.org)\n\n## 결론\n\n끝')
        report=preflight_report(post,self.source,w)
        self.assertIn('RAW_URL_DISPLAY',report['error_codes'])
        self.assertIn('REFERENCE_SECTION_NOT_TERMINAL',report['error_codes'])
        self.assertEqual(report['presentation_review']['factual_review'],'not_evaluated')
    def test_table_cells_and_empty_cell_preserved(self):
        post,_=self.build('|항목|값|\n|---|---|\n|A||\n|B|둘째|')
        self.assertEqual(post['blocks'][0]['rows'],[['A',''],['B','둘째']])
        for cell in ['**강조**','`code`','[링크](https://example.org)']:
            with self.subTest(cell=cell),self.assertRaises(BuildError) as ctx:self.build('|항목|\n|---|\n|'+cell+'|')
            self.assertEqual(ctx.exception.code,'UNSUPPORTED_TABLE_INLINE')
    def test_title_link_not_silently_lost(self):
        self.source.write_text('# [제목](https://example.org)\n\n본문')
        with self.assertRaises(BuildError) as ctx:build_post(self.source,self.root)
        self.assertEqual(ctx.exception.code,'UNSUPPORTED_TITLE_LINK')

if __name__=='__main__':unittest.main()
