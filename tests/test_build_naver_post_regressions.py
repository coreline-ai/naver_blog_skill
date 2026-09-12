"""Regression assertions replace unsafe outcomes from the 2026-09-12 audit."""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from PIL import Image

SCRIPTS=Path(__file__).resolve().parents[1]/'skills/naver-smarteditor-drafter/scripts'
sys.path.insert(0,str(SCRIPTS))
from build_naver_post import BuildError, build_post, preflight_report, run, main


class ConverterRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name).resolve()
        self.series=self.root/'series';self.series.mkdir()
    def tearDown(self): self.tmp.cleanup()
    def write(self,name,value):
        path=self.series/name;path.parent.mkdir(parents=True,exist_ok=True)
        path.write_text(value if isinstance(value,str) else json.dumps(value,ensure_ascii=False))
        return path
    def args(self,**kw):
        options=dict(input=None,input_root=str(self.series),project_root=str(self.root),output_root=str(self.root/'runs'),
                     run_id='test',batch=True,check=False,force=False,episode_min=None,episode_max=None,expected_images=None,expected_tags=None)
        options.update(kw);return argparse.Namespace(**options)
    def basic(self,ep=3,**kw):
        value={'episode':ep,'title':f'{ep}편','blocks':[{'type':'paragraph','text':'본문'}],**kw}
        return self.write(f'episode-{ep:02}.json',value)
    def tree(self,path):
        return {str(p.relative_to(path)):hashlib.sha256(p.read_bytes()).hexdigest() for p in path.rglob('*') if p.is_file()}
    def test_force_resets_saved_state(self):
        self.basic();run(self.args())
        directory=self.root/'runs/test'
        report=json.loads((directory/'run-report.json').read_text())
        report.update(status='complete',last_saved_episode=3)
        (directory/'run-report.json').write_text(json.dumps(report))
        (directory/'episode-03/draft-run-report.json').write_text('{"status":"saved_verified"}')
        before=self.tree(directory)
        with self.assertRaisesRegex(BuildError,'cannot overwrite'):
            run(self.args(force=True))
        self.assertEqual(before,self.tree(directory))
    def test_missing_requested_episode(self):
        self.basic(3);self.basic(5)
        result=run(self.args(episode_min=3,episode_max=5))
        self.assertEqual(result['missing'],[4]);self.assertEqual(result['queue'],[])
        self.assertEqual(result['totals']['failed'],1)
        self.assertFalse((self.root/'runs/test/complete.json').exists())
    def test_episode_identity_collision(self):
        self.basic(3)
        self.write('episode-04.json',{'episode':3,'title':'악성 덮어쓰기','blocks':[{'type':'paragraph','text':'다른 본문'}]})
        result=run(self.args())
        self.assertEqual(result['queue'],[]);self.assertEqual(result['totals']['failed'],1)
        self.assertEqual(result['episodes'][1]['error_code'],'EPISODE_IDENTITY_CONFLICT')
        stored=json.loads((self.root/'runs/test/episode-03/naver-post.json').read_text())
        self.assertEqual(stored['title'],'3편')
    def test_editor_notes_enter_body(self):
        source=self.write('episode-03.md','**편집자용 시리즈 안내 — 게시 본문 제외**\n\n# 제목\n\n본문')
        original=source.read_bytes()
        with self.assertRaises(BuildError) as ctx: build_post(source,self.root)
        self.assertEqual(ctx.exception.code,'EDITORIAL_BOUNDARY_AMBIGUOUS')
        self.assertEqual(source.read_bytes(),original)
        source=self.basic(blocks=[{'type':'paragraph','text':'게시 본문 제외'}])
        with self.assertRaises(BuildError): build_post(source,self.root)
    def test_malformed_level_aborts_batch(self):
        self.basic(3,blocks=[{'type':'heading','level':'invalid','text':'소제목'}]);self.basic(4)
        result=run(self.args())
        self.assertEqual(result['totals']['failed'],1)
        self.assertEqual(result['queue'],[])
        self.assertTrue((self.root/'runs/test/run-report.json').exists())
        self.assertEqual(result['prepared_queue'],[4])
    def test_fake_images_and_no_body_pass(self):
        blocks=[]
        for n in range(5):
            p=self.series/f'{n}.png';p.write_text('not a real image')
            blocks.append({'type':'image','path':str(p),'alt':'테스트'})
        source=self.basic(blocks=blocks,tags=['a','b','c','d','e','f'])
        post,w=build_post(source,self.root)
        report=preflight_report(post,source,w,expected_images=5,expected_tags=6)
        self.assertEqual(report['status'],'failed')
        self.assertIn('BODY_REQUIRED',report['error_codes'])
        self.assertEqual(report['error_codes'].count('INVALID_IMAGE'),5)
        self.assertIsNone(report['content_revision'])
    def test_unsupported_markdown_silently_passes(self):
        source=self.write('episode-03.md','# 제목\n\n😀 **강조** [출처](https://example.org/source)\n')
        post,w=build_post(source,self.root)
        self.assertEqual(post['blocks'][0]['text'],'😀 강조 출처 (https://example.org/source)')
        self.assertEqual(post['blocks'][0]['marks'],[{'type':'bold','start':2,'end':4}])
        self.assertIn('links rendered as label (URL)',w)
        for syntax in ['#### H4','```python\nprint(1)\n```','<script>bad</script>','[a][ref]','  - nested','plain ![x](a.png)']:
            source.write_text('# 제목\n\n'+syntax)
            with self.subTest(syntax=syntax),self.assertRaises(BuildError): build_post(source,self.root)
    def test_canonical_marks_lost(self):
        source=self.write('episode-03.md','# 제목\n\n😀 **원문**과 `code`')
        canonical,_=build_post(source,self.root)
        canonical['blocks'][0]['id']='custom-id'
        duplicate=self.write('canonical.json',canonical)
        reread,_=build_post(duplicate,self.root)
        self.assertEqual(reread,canonical)
        for mark in [{'type':'bold','start':0,'end':999},{'type':'bold','start':True,'end':2}]:
            bad=copy.deepcopy(canonical);bad['blocks'][0]['marks']=[mark];duplicate.write_text(json.dumps(bad))
            with self.assertRaises(BuildError): build_post(duplicate,self.root)
    def test_string_tags_become_characters(self):
        for value in ['가이드',None,12,{'a':'b'},[5]]:
            source=self.basic(tags=value)
            with self.subTest(value=value),self.assertRaises(BuildError): build_post(source,self.root)
    def test_image_change_untracked(self):
        img=self.series/'asset.png';Image.new('RGB',(4,4),'red').save(img)
        source=self.basic(blocks=[{'type':'paragraph','text':'설명'},{'type':'image','path':str(img),'alt':'설명'}])
        post,w=build_post(source,self.root);first=preflight_report(post,source,w)
        Image.new('RGB',(4,4),'blue').save(img)
        second=preflight_report(post,source,w)
        self.assertNotEqual(first['content_revision'],second['content_revision'])
        self.assertEqual(first['source_sha256'],second['source_sha256'])
    def test_parent_run_id_accepted(self):
        self.basic()
        for value in ['.','..','../outside','/tmp/escape','a/b','a\\b','', 'hidden\x00']:
            with self.subTest(value=value),self.assertRaises(BuildError):run(self.args(run_id=value))
        self.assertFalse((self.root/'runs').exists())
    def test_symlink_destination_and_output_root_rejected(self):
        self.basic();outside=self.root/'outside';outside.mkdir();out=self.root/'runs';out.mkdir()
        (out/'test').symlink_to(outside,target_is_directory=True)
        with self.assertRaises(BuildError):run(self.args())
        link=self.root/'rootlink';link.symlink_to(outside,target_is_directory=True)
        with self.assertRaises(BuildError):run(self.args(output_root=str(link)))
        self.assertEqual(list(outside.iterdir()),[])
    def test_invalid_types_and_duplicate_ids(self):
        for value in [True,'3',3.5,0,-1]:
            src=self.write('episode-03.json',{'episode':value,'title':'제목','blocks':[]})
            with self.subTest(value=value),self.assertRaises(BuildError):build_post(src,self.root)
        for blocks in [[{'id':'same','type':'paragraph','text':'1'},{'id':'same','type':'paragraph','text':'2'}],
                       [{'type':'heading','text':'제목','style':'unknown'}],
                       [{'type':'paragraph','text':5}]]:
            source=self.basic(blocks=blocks)
            with self.assertRaises(BuildError):build_post(source,self.root)
    def test_tag_boundaries_and_terminal_tags(self):
        for length,success in [(99,True),(100,True),(101,False)]:
            source=self.basic(tags=['가'*(length-1)])
            if success:self.assertEqual(len('#'+build_post(source,self.root)[0]['tags'][0]),length)
            else:
                with self.assertRaises(BuildError):build_post(source,self.root)
        source=self.write('episode-04.md','# 제목\n\n본문\n\n**태그**\n#태그\n\n## 몰래 남은 본문')
        with self.assertRaises(BuildError):build_post(source,self.root)
    def test_force_identical_is_no_write_and_changed_is_conflict(self):
        src=self.basic();run(self.args())
        directory=self.root/'runs/test';before={p:p.stat().st_mtime_ns for p in directory.rglob('*') if p.is_file()}
        run(self.args(force=True))
        self.assertEqual(before,{p:p.stat().st_mtime_ns for p in before})
        src.write_text(src.read_text().replace('본문','수정된 본문'))
        with self.assertRaises(BuildError):run(self.args(force=True))
        self.assertEqual(before,{p:p.stat().st_mtime_ns for p in before})
    def test_duplicate_json_keys_rejected(self):
        src=self.write('episode-03.json','{"title":"A","title":"B","blocks":[]}')
        with self.assertRaisesRegex(BuildError,'duplicate JSON key'):build_post(src,self.root)
    def test_content_revision_ignores_relocation(self):
        img=self.series/'a.png';Image.new('RGB',(4,4),'red').save(img)
        source=self.basic(blocks=[{'type':'paragraph','text':'본문'},{'type':'image','path':str(img),'alt':'x'}])
        post,w=build_post(source,self.root);first=preflight_report(post,source,w)
        copied=self.root/'moved';copied.mkdir();other=copied/'a.png';other.write_bytes(img.read_bytes())
        moved=copy.deepcopy(post);moved['source']=str(copied/'original.md');moved['blocks'][1]['path']=str(other)
        second=preflight_report(moved,source,w,project_root=self.root)
        self.assertEqual(first['content_revision'],second['content_revision'])

if __name__=='__main__':unittest.main()
