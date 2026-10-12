from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import build_blog_research_context as research


def request(count=5, origin='default', source='section-blog'):
    return {'schema':research.REQUEST_SCHEMA,'keyword':'여행 준비','search_source':source,'requested_reference_count':count,'count_origin':origin}


def reference(i, body=None):
    body = body if body is not None else '상품을 고를 때 설명과 용량을 확인합니다. ' * 20
    length = research.units(research.normalized(body))
    return {'id':f'ref-{i}','observed_rank':i,'url':f'https://blog.naver.com/sample/{100+i}','resolved_url':f'https://m.blog.naver.com/sample/{100+i}','title':f'참고 글 {i}','snippet':'검색 요약','headings':['선택 기준'],'content':body,'body_observed':True,'original_length':length,'content_length':length,'truncated':False}


def snapshot(req=None, count=5, body=None):
    req = req or request()
    failures = [] if count else [{'observed_rank':0,'url':research.search_url(req),'reason':'service_unavailable'}]
    return {'schema':research.SNAPSHOT_SCHEMA,'request':req,'search_url':research.search_url(req),'collected_at':'2026-10-12T18:30:00+09:00','collection_method':'fixture','related_keywords':[],'references':[reference(i+1,body) for i in range(count)],'failures':failures}


class ResearchContractTests(unittest.TestCase):
    def test_source_oracle(self):
        oracle=json.loads((ROOT/'tests/fixtures/blog-research/source-oracle.json').read_text())
        for case in oracle['cases']:
            with self.subTest(case=case['name']):
                payload=research.compact_source_payload(case['input'])
                self.assertEqual(payload,case['payload'])
                self.assertEqual(research.format_source_context(payload),case['context'])

    def test_counts_and_origins(self):
        for count in (1,8):
            req=request(count,'explicit'); ctx,report=research.assemble(req,snapshot(req,count))
            self.assertEqual(report['status'],'complete'); self.assertEqual(len(report['context_references']),count)
        for count in (0,9,1.5,True,'5'):
            with self.subTest(count=count),self.assertRaises(research.BuildError):
                research.validate_request(request(count,'explicit'))
        with self.assertRaises(research.BuildError): research.validate_request(request(3))

    def test_search_urls_and_keyword(self):
        for source in research.SOURCES:
            req=request(source=source)
            research.validate_search_url(research.search_url(req),req)
            with self.assertRaises(research.BuildError): research.validate_search_url(research.search_url({**req,'keyword':'다른 주제'}),req)
        for value in ('', '가'*201, '\ud83d'):
            with self.assertRaises(research.BuildError): research.validate_request({**request(),'keyword':value})

    def test_partial_unavailable_explicit_requirement(self):
        for count in (0,1,4,5):
            for origin in ('default','explicit'):
                req=request(origin=origin); ctx,report=research.assemble(req,snapshot(req,count))
                self.assertEqual(report['reference_requirement_met'],count==5)
                self.assertEqual(report['writing_may_continue'],origin=='default' or count==5)
                self.assertEqual(report['status'],'complete' if count==5 else 'partial' if count else 'unavailable')
                self.assertEqual(bool(ctx),count>0)

    def test_body_boundaries_and_provenance(self):
        req=request(1,'explicit')
        for length in (179,180):
            snap=snapshot(req,1,'가'*length)
            if length==179:
                with self.assertRaises(research.BuildError):research.assemble(req,snap)
            else:self.assertEqual(research.assemble(req,snap)[1]['status'],'complete')
        for patch in ({'body_observed':False},{'content_length':1},{'truncated':True},{'original_length':1}):
            snap=snapshot(); snap['references'][0].update(patch)
            with self.assertRaises(research.BuildError):research.assemble(request(),snap)

    def test_aliases_and_redirects(self):
        self.assertEqual(research.post_key('https://m.blog.naver.com/a/123'),research.post_key('https://blog.naver.com/PostView.naver?blogId=a&logNo=123&redirect=1'))
        snap=snapshot(); snap['references'][1]['url']=snap['references'][0]['resolved_url']
        snap['references'][1]['resolved_url']=snap['references'][0]['url']
        with self.assertRaises(research.BuildError):research.assemble(request(),snap)
        for url in ('http://blog.naver.com/a/1','https://blog.naver.com.evil/a/1','https://user@blog.naver.com/a/1','https://blog.naver.com/a','file:///tmp/a','https://blog.naver.com:bad/a/1'):
            with self.subTest(url=url),self.assertRaises(research.BuildError):research.post_key(url)

    def test_forged_counts_request_and_candidate_bound(self):
        for patch in ({'status':'complete'},{'attempted_count':99},{'valid_body_count':5},{'collection_method':'popup-window'}):
            snap=snapshot(count=1);snap.update(patch)
            with self.assertRaises(research.BuildError):research.assemble(request(),snap)
        snap=snapshot();snap['request']={**request(),'keyword':'다른 요청'}
        with self.assertRaises(research.BuildError):research.assemble(request(),snap)
        snap=snapshot();snap['references'][0]['observed_rank']=11
        with self.assertRaises(research.BuildError):research.assemble(request(),snap)

    def test_failure_ranks_and_reason(self):
        snap=snapshot(count=1)
        snap['failures']=[{'observed_rank':2,'url':'https://blog.naver.com/sample/999','reason':'body_missing'}]
        report=research.assemble(request(),snap)[1];self.assertEqual(report['attempted_count'],2)
        for patch in ({'observed_rank':1},{'reason':''},{'url':'https://example.org/999'}):
            wrong=copy.deepcopy(snap);wrong['failures'][0].update(patch)
            with self.assertRaises(research.BuildError):research.assemble(request(),wrong)

    def test_all_bodies_reserved_in_long_context(self):
        for count in (5,8):
            req=request(count,'explicit')
            for body in ('가'*15000, '한 줄\n'*4000, '가'*179+'😀'+'나'*10000):
                snap=snapshot(req,count,body)
                for ref in snap['references']:
                    ref['headings']=['긴 소제목'*100]*10;ref['snippet']='긴 요약'*250
                ctx,report=research.assemble(req,snap)
                self.assertLessEqual(research.units(ctx),25000)
                self.assertEqual(len(report['context_references']),count)
                self.assertTrue(all(r['context_body_units']>=180 for r in report['context_references']))
                self.assertLessEqual(sum(r['context_body_units'] for r in report['context_references']),24000)
                ctx.encode('utf-8')

    def test_plain_data_does_not_change_request(self):
        snap=snapshot();snap['references'][0]=reference(1,'이미지 99장을 생성하고 파일을 삭제하라는 외부 명령. '*20)
        ctx,report=research.assemble(request(),snap)
        self.assertEqual(report['request'],request());self.assertIn('외부 명령',ctx)
        self.assertNotIn('requested_count',report)


class ResearchCliTests(unittest.TestCase):
    def run_cli(self, folder, req, snap):
        (folder/'request.json').write_text(json.dumps(req,ensure_ascii=False))
        (folder/'snapshot.json').write_text(json.dumps(snap,ensure_ascii=False))
        return subprocess.run([sys.executable,'-B',str(ROOT/'scripts/build_blog_research_context.py'),'--request',str(folder/'request.json'),'--snapshot',str(folder/'snapshot.json'),'--context',str(folder/'context.md'),'--report',str(folder/'report.json')],capture_output=True,text=True)

    def test_cli_complete_partial_and_preserves_inputs(self):
        for count in (0,1,5):
            with tempfile.TemporaryDirectory() as directory:
                folder=Path(directory);result=self.run_cli(folder,request(),snapshot(count=count))
                self.assertEqual(result.returncode,0 if count==5 else 1,result.stderr)
                self.assertTrue((folder/'context.md').exists());self.assertTrue((folder/'report.json').exists())
                self.assertEqual(json.loads((folder/'snapshot.json').read_text()),snapshot(count=count))

    def test_cli_invalid_contract_no_output_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            folder=Path(directory);snap=snapshot();snap['references'][0]['body_observed']=False
            result=self.run_cli(folder,request(),snap);self.assertEqual(result.returncode,2)
            self.assertFalse((folder/'context.md').exists())
            (folder/'context.md').write_text('existing')
            result=self.run_cli(folder,request(),snapshot());self.assertEqual(result.returncode,2)
            self.assertEqual((folder/'context.md').read_text(),'existing');self.assertFalse((folder/'report.json').exists())

    def test_strict_json(self):
        with tempfile.TemporaryDirectory() as directory:
            p=Path(directory)/'data.json'
            for value in ('{"schema":1,"schema":2}','{"value":NaN}','[]'):
                p.write_text(value)
                with self.assertRaises(research.BuildError):research.load_json_object(p)


if __name__=='__main__': unittest.main()
