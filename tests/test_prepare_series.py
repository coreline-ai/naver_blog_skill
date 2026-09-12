from __future__ import annotations
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image

IMPL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(IMPL / 'skills/naver-series-workflow/scripts'))
import prepare_series as workflow
from execution_state import ExecutionKey, ExecutionStore


def snapshot(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}


class SeriesPreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.inputs = self.root / 'input'; self.inputs.mkdir()
        self.outputs = self.root / 'prepared'
        self.manifest = self.inputs / 'series.json'
        self.data = {'schema': 'naver-series/v1', 'series_id': 'fixture-series', 'requested_episodes': [3],
                     'target_blog': 'fixture-blog', 'requirements': {'images_per_episode': 1, 'tag_line_max_chars': 100}, 'episodes': []}
        self.add_episode(3); self.save_manifest()
    def tearDown(self): self.temp.cleanup()
    def save_manifest(self): self.manifest.write_text(workflow.encoded(self.data))
    def add_episode(self, ep):
        folder = self.inputs / f'episode-{ep:02d}'; folder.mkdir()
        Image.new('RGB', (4, 4), (ep, 30, 70)).save(folder / 'image.png')
        (folder / 'article.md').write_text(f'# 회차 {ep}\n\n도입 설명입니다.\n\n## 실천 방법\n\n확인할 **내용**입니다.\n\n![개념 이미지](image.png)\n\n마지막 확인입니다.\n\n**핵심 요약**\n\n- 첫째\n- 둘째\n\n**태그**\n\n#정보 #정리\n')
        (folder / 'editorial.json').write_text(workflow.encoded({'note': '게시 본문 제외: 이 메모를 본문으로 보내지 않는다.'}))
        self.data['episodes'].append({'episode': ep, 'article': f'episode-{ep:02d}/article.md', 'editorial': f'episode-{ep:02d}/editorial.json', 'review': f'episode-{ep:02d}/review.json'})
        return folder
    def run_prepare(self, run='run', **kwargs):
        return workflow.prepare(self.manifest, self.inputs, self.outputs, run, **kwargs)
    def approve(self):
        report = self.run_prepare(check=True)
        for entry in report['episodes']:
            if entry['content_revision']:
                review = {'schema': 'naver-review/v1', 'status': 'passed', 'content_revision': entry['content_revision'],
                          'checks': [{'id': c, 'status': 'passed', 'evidence': 'Synthetic test fixture manually specified; not a real factual review.'} for c in sorted(workflow.REVIEW_CHECKS)],
                          'reviewed_by': 'synthetic-test', 'reviewed_at': '2026-09-12T00:00:00+00:00'}
                (self.inputs / f"episode-{entry['episode']:02d}/review.json").write_text(workflow.encoded(review))
    def error(self, code=None):
        with self.assertRaises(workflow.BuildError) as cm: self.run_prepare()
        if code: self.assertEqual(cm.exception.code, code)
        self.assertFalse(self.outputs.exists())
    def test_pending_retains_candidate_and_review_template_without_ready_marker(self):
        before = snapshot(self.inputs); report = self.run_prepare()
        self.assertEqual(report['episodes'][0]['status'], 'review_pending')
        self.assertEqual(report['queue'], []); self.assertFalse(report['ui_executable'])
        self.assertEqual(before, snapshot(self.inputs))
        out = self.outputs / 'run/episode-03'
        self.assertTrue((out / 'naver-post.json').is_file())
        self.assertTrue((out / 'review-template.json').is_file())
        self.assertFalse((out.parent / 'complete.json').exists())
        self.assertEqual(workflow.status(out.parent)['preparation'], 'blocked')
    def test_approved_ready_but_not_authorization_or_saved(self):
        self.approve(); report = self.run_prepare()
        self.assertEqual(report['queue'], [3]); self.assertFalse(report['ui_authorized'])
        status = workflow.status(self.outputs / 'run', execution_root=self.root/'events')
        self.assertFalse(status['live_complete']); self.assertEqual(status['next_episode'], 3)
        self.assertEqual(status['next_action'], 'start'); self.assertFalse((self.root/'events').exists())
    def test_missing_requested_episode_blocks_entire_queue(self):
        self.add_episode(5); self.data['requested_episodes']=[3,4,5]; self.save_manifest(); self.approve()
        report=self.run_prepare()
        self.assertEqual(report['totals']['missing'],1); self.assertEqual(report['queue'],[])
        self.assertEqual(report['episodes'][1]['status'],'missing')
    def test_sparse_reverse_request_preserves_set_and_sorts_execution(self):
        self.add_episode(4); self.add_episode(5); self.data['requested_episodes']=[5,3]; self.save_manifest(); self.approve()
        report=self.run_prepare(); self.assertEqual(report['queue'],[3,5]); self.assertEqual(report['ignored_episodes'],[4])
        self.assertEqual(report['original_request'],[5,3]); self.assertFalse((self.outputs/'run/episode-04').exists())
    def test_bad_requested_values_and_duplicates_rejected_before_write(self):
        for values in ([],[3,3],[True],[0],['3'],[3.0]):
            with self.subTest(values=values):
                self.data['requested_episodes']=values; self.save_manifest(); self.error()
    def test_duplicate_entries_and_article_collisions_rejected(self):
        self.data['episodes'].append(copy.deepcopy(self.data['episodes'][0])); self.save_manifest(); self.error('DUPLICATE_EPISODE')
        self.data['episodes'][-1]['episode']=4; self.save_manifest(); self.error('EPISODE_IDENTITY_CONFLICT')
    def test_manifest_episode_conflicts_with_folder(self):
        self.data['episodes'][0]['episode']=4; self.data['requested_episodes']=[4]; self.save_manifest()
        report=self.run_prepare(); self.assertEqual(report['episodes'][0]['error_codes'],['EPISODE_IDENTITY_CONFLICT'])
    def test_path_and_symlink_escape_rejected(self):
        self.data['episodes'][0]['article']='../../escape.md'; self.save_manifest(); self.error('UNSAFE_PATH')
        target=self.root/'outside.md'; target.write_text('# Outside')
        (self.inputs/'escape.md').symlink_to(target); self.data['episodes'][0]['article']='escape.md'; self.save_manifest(); self.error('UNSAFE_PATH')
    def test_output_escape_or_existing_snapshot_never_overwritten(self):
        with self.assertRaises(workflow.BuildError): self.run_prepare('../escape')
        self.run_prepare(); before=snapshot(self.outputs)
        with self.assertRaises(workflow.BuildError): self.run_prepare()
        self.assertEqual(before,snapshot(self.outputs))
    def test_exact_reuse_does_not_change_snapshot_or_execution_history(self):
        self.approve(); self.run_prepare(); before=snapshot(self.outputs)
        events=self.root/'events'; events.mkdir(); (events/'sentinel.json').write_text('{"saved":true}')
        self.run_prepare(reuse=True); self.assertEqual(before,snapshot(self.outputs))
        self.assertEqual((events/'sentinel.json').read_text(),'{"saved":true}')
        article=self.inputs/'episode-03/article.md'; article.write_text(article.read_text().replace('**태그**','변경된 본문\n\n**태그**'))
        with self.assertRaises(workflow.BuildError): self.run_prepare(reuse=True)
        self.assertEqual(before,snapshot(self.outputs))
    def test_editorial_is_separate_and_body_metadata_blocks(self):
        self.approve(); self.run_prepare()
        post=(self.outputs/'run/episode-03/naver-post.json').read_text(); self.assertNotIn('게시 본문 제외',post)
        article=self.inputs/'episode-03/article.md'; article.write_text(article.read_text()+'\n게시 본문 제외: 관리용\n')
        report=self.run_prepare('bad'); self.assertEqual(report['episodes'][0]['error_codes'],['EDITORIAL_BOUNDARY_AMBIGUOUS'])
    def test_invalid_article_does_not_abort_other_episode_diagnostics(self):
        self.add_episode(4); self.data['requested_episodes']=[3,4]; self.save_manifest()
        (self.inputs/'episode-03/article.md').write_text('# 제목\n\n#### 미지원\n')
        report=self.run_prepare(); self.assertEqual(len(report['episodes']),2)
        self.assertEqual(report['episodes'][0]['status'],'preflight_failed'); self.assertEqual(report['episodes'][1]['status'],'review_pending')
    def test_changed_body_makes_review_stale(self):
        self.approve(); article=self.inputs/'episode-03/article.md'; article.write_text(article.read_text().replace('**태그**','새 본문입니다.\n\n**태그**'))
        report=self.run_prepare(); self.assertEqual(report['episodes'][0]['status'],'stale_review')
    def test_changed_image_same_path_makes_review_stale(self):
        self.approve(); Image.new('RGB',(4,4),'red').save(self.inputs/'episode-03/image.png')
        self.assertEqual(self.run_prepare()['episodes'][0]['status'],'stale_review')
    def test_image_disguised_or_wrong_count_blocks(self):
        (self.inputs/'episode-03/image.png').write_bytes(b'not an image')
        report=self.run_prepare(); self.assertEqual(report['episodes'][0]['status'],'assets_pending')
        self.assertEqual(report['queue'],[])
    def test_review_quality_checks_evidence_and_identity_required(self):
        self.approve(); path=self.inputs/'episode-03/review.json'; good=json.loads(path.read_text())
        for change in ('missing','failed','empty','reviewer','date','duplicate','unknown'):
            with self.subTest(change=change):
                review=copy.deepcopy(good)
                if change=='missing': review['checks'].pop()
                if change=='failed': review['checks'][0]['status']='pending'
                if change=='empty': review['checks'][0]['evidence']=''
                if change=='reviewer': review['reviewed_by']=''
                if change=='date': review['reviewed_at']='yesterday'
                if change=='duplicate': review['checks'].append(review['checks'][0])
                if change=='unknown': review['extra']=True
                path.write_text(workflow.encoded(review))
                report=self.run_prepare(check=True)
                self.assertEqual(report['episodes'][0]['status'],'invalid_review')
                self.assertEqual(report['queue'],[])
    def test_needs_revision_never_rewrites_article(self):
        self.approve(); path=self.inputs/'episode-03/review.json'; review=json.loads(path.read_text()); review['status']='needs_revision'; path.write_text(workflow.encoded(review))
        before=snapshot(self.inputs); self.assertEqual(self.run_prepare()['episodes'][0]['status'],'needs_revision'); self.assertEqual(before,snapshot(self.inputs))
    def test_review_pending_current_revision_is_not_passed(self):
        self.approve(); path=self.inputs/'episode-03/review.json'; review=json.loads(path.read_text()); review['status']='pending'; path.write_text(workflow.encoded(review))
        self.assertEqual(self.run_prepare()['episodes'][0]['status'],'review_pending')
    def test_tag_limit_unicode_and_hash_spaces(self):
        article=self.inputs/'episode-03/article.md'
        for size in (99,100,101):
            with self.subTest(size=size):
                article.write_text('# 제목\n\n본문입니다.\n\n![그림](image.png)\n\n**태그**\n\n#'+('가'*(size-1))+'\n')
                report=self.run_prepare(check=True)
                self.assertEqual(bool(report['episodes'][0]['content_revision']),size<=100)
        self.data['requirements']['tag_line_max_chars']=5; self.save_manifest()
        article.write_text('# 제목\n\n본문\n\n![그림](image.png)\n\n**태그**\n\n#한글 #😀\n')
        self.assertIn('TAG_LENGTH_EXCEEDED',self.run_prepare(check=True)['episodes'][0]['error_codes'])
    def test_status_read_only_and_detects_asset_and_input_changes(self):
        self.approve(); self.run_prepare(); before=snapshot(self.root)
        with patch('subprocess.run',side_effect=AssertionError('no browser, model, or shell')):
            result=workflow.status(self.outputs/'run',execution_root=self.root/'missing-events')
        self.assertEqual(result['integrity'],'passed'); self.assertEqual(before,snapshot(self.root))
        (self.inputs/'episode-03/image.png').write_bytes(b'changed')
        result=workflow.status(self.outputs/'run'); self.assertEqual(result['integrity'],'failed'); self.assertEqual(result['queue'],[])
    def test_snapshot_tampering_partial_and_extra_files_fail_closed(self):
        self.approve(); self.run_prepare(); directory=self.outputs/'run'
        (directory/'extra.json').write_text('{}')
        with self.assertRaises(workflow.BuildError): workflow.status(directory)
        (directory/'extra.json').unlink(); (directory/'complete.json').unlink()
        with self.assertRaises(workflow.BuildError): workflow.status(directory)
    def test_partial_diagnostic_snapshot_readable_but_never_ui_ready(self):
        self.run_prepare(); result=workflow.status(self.outputs/'run',execution_root=self.root/'events')
        self.assertFalse(result['live_complete']); self.assertEqual(result['queue'],[]); self.assertEqual(result['next_action'],'not_eligible')
    def test_check_mode_writes_nothing_and_invokes_no_external_process(self):
        before=snapshot(self.root)
        with patch('subprocess.run',side_effect=AssertionError('no external calls')):
            self.run_prepare(check=True)
        self.assertEqual(before,snapshot(self.root)); self.assertFalse(self.outputs.exists())
    def test_unknown_schema_keys_duplicate_json_and_nonfinite_rejected(self):
        for raw in ('{"schema":1,"schema":2}', '{"n":NaN}', '{"x": Infinity}'):
            self.manifest.write_text(raw); self.error()
        self.data['surprise']=True; self.save_manifest(); self.error('INVALID_CONTRACT')
    def test_optional_blog_and_different_blog_conflict(self):
        self.data.pop('target_blog'); self.save_manifest(); self.approve(); self.run_prepare()
        result=workflow.status(self.outputs/'run',execution_root=self.root/'events')
        self.assertIsNone(result['target_blog']); self.assertEqual(result['queue'],[])
        self.assertEqual(workflow.status(self.outputs/'run',execution_root=self.root/'events',target_blog='chosen-blog')['next_episode'],3)
    def test_cli_refuses_draft_and_missing_dependency_is_clear(self):
        command=[sys.executable,'-B',str(IMPL/'skills/naver-series-workflow/scripts/prepare_series.py'),'draft']
        result=subprocess.run(command,text=True,capture_output=True); self.assertEqual(result.returncode,2)
        copied=self.root/'skills/naver-series-workflow/scripts/prepare_series.py'; copied.parent.mkdir(parents=True)
        shutil.copyfile(command[2],copied)
        result=subprocess.run([sys.executable,'-B',str(copied),'--help'],text=True,capture_output=True)
        self.assertIn('DEPENDENCY_MISSING',result.stderr)
    def test_approved_slots_use_root_paths_without_source_writes(self):
        folder=self.inputs/'episode-03'; (folder/'article.md').write_text('# 제목\n\n설명입니다.\n\n<!-- naver-image:cover -->\n\n사진 뒤 문단\n')
        slots={'version':1,'asset_root':'episode-03','slots':[{'id':'cover','role':'cover','placement':'설명 뒤','purpose':'개념','mode':'infographic-diagram','prompt':'테스트용','alt':'개념','caption':'그림 설명','path':'episode-03/image.png','status':'approved'}]}
        (folder/'slots.json').write_text(workflow.encoded(slots)); self.data['episodes'][0]['image_slots']='episode-03/slots.json'; self.save_manifest()
        before=snapshot(self.inputs); report=self.run_prepare(); self.assertEqual(report['episodes'][0]['status'],'review_pending')
        post=json.loads((self.outputs/'run/episode-03/naver-post.json').read_text()); image=next(b for b in post['blocks'] if b['type']=='image')
        self.assertEqual(image['path'],str(folder/'image.png')); self.assertEqual(post['source'],str(folder/'article.md'))
        self.assertEqual(before,snapshot(self.inputs)); self.assertEqual(report['totals']['images'],1)
    def test_unapproved_slot_stops_without_generation(self):
        folder=self.inputs/'episode-03'; (folder/'article.md').write_text('# 제목\n\n본문\n\n<!-- naver-image:cover -->\n')
        slots={'version':1,'asset_root':'episode-03','slots':[{'id':'cover','role':'cover','placement':'본문 뒤','purpose':'개념','mode':'infographic-diagram','prompt':'미실행','alt':'개념','caption':'','path':'episode-03/image.png','status':'pending'}]}
        (folder/'slots.json').write_text(workflow.encoded(slots)); self.data['episodes'][0]['image_slots']='episode-03/slots.json'; self.save_manifest()
        with patch('subprocess.run',side_effect=AssertionError('no generation')):
            result=self.run_prepare()
        self.assertEqual(result['episodes'][0]['status'],'assets_pending'); self.assertEqual(result['queue'],[])
    def test_new_review_requires_new_snapshot_and_does_not_upgrade_pending(self):
        self.run_prepare(); self.approve()
        info=workflow.status(self.outputs/'run')
        self.assertEqual(info['integrity'],'failed'); self.assertEqual(info['preparation'],'blocked')
        self.assertEqual(info['queue'],[])
    def test_canonical_unsupported_heading_pair_fails_before_render(self):
        post,_=workflow.build_post(self.inputs/'episode-03/article.md',self.inputs)
        heading=next(b for b in post['blocks'] if b['type']=='heading');heading['style']='subtitle'
        path=self.inputs/'episode-03/post.json';path.write_text(workflow.encoded(post))
        self.data['episodes'][0]['article']='episode-03/post.json';self.save_manifest()
        self.assertEqual(self.run_prepare()['episodes'][0]['status'],'preflight_failed')
    def test_missing_image_reports_assets_pending_without_generation(self):
        (self.inputs/'episode-03/image.png').unlink()
        with patch('subprocess.run',side_effect=AssertionError('no generation')):
            result=self.run_prepare()
        self.assertEqual(result['episodes'][0]['status'],'assets_pending')
        self.assertEqual(result['episodes'][0]['error_codes'],['ASSET_MISSING'])
    def test_image_requirement_five_rejects_zero_four_six(self):
        self.data['requirements']['images_per_episode']=5;self.save_manifest()
        folder=self.inputs/'episode-03'
        for n in range(6):Image.new('RGB',(3,3),(n,0,0)).save(folder/f'pic-{n}.png')
        for count in (0,4,5,6):
            with self.subTest(count=count):
                (folder/'article.md').write_text('# 제목\n\n본문입니다.\n\n'+'\n\n'.join(f'![사진 {n}](pic-{n}.png)' for n in range(count)))
                result=self.run_prepare(check=True)
                self.assertEqual(result['episodes'][0]['status'],'review_pending' if count==5 else 'assets_pending')
                self.assertEqual(result['totals']['images'],count)
    def test_coherently_rehashed_report_cannot_hide_missing_requested_episode(self):
        self.approve();self.run_prepare();directory=self.outputs/'run'
        report_path=directory/'series-report.json';report=json.loads(report_path.read_text())
        report['requested_episodes']=[3,4];report_path.write_text(workflow.encoded(report))
        snapshot_path=directory/'snapshot.json';record=json.loads(snapshot_path.read_text())
        record['files']['series-report.json']=hashlib.sha256(report_path.read_bytes()).hexdigest();snapshot_path.write_text(workflow.encoded(record))
        (directory/'complete.json').write_text(workflow.encoded({'schema':'naver-series-ready/v1','snapshot_sha256':hashlib.sha256(snapshot_path.read_bytes()).hexdigest()}))
        with self.assertRaises(workflow.BuildError):workflow.status(directory)
    def test_resume_reports_reconciliation_not_later_episode(self):
        self.add_episode(4); self.data['requested_episodes']=[3,4]; self.save_manifest(); self.approve(); report=self.run_prepare()
        store=ExecutionStore(self.root/'events',environment='simulation'); key=ExecutionKey('fixture-blog','fixture-series',3,report['episodes'][0]['content_revision'])
        lease=store.acquire(key.target_blog,'fixture-run'); store.start(key,lease)
        evidence={'environment':'simulation','target_blog':key.target_blog,'content_revision':key.revision,'observed':{'title':''},'evidence_ref':'simulation-blank','checks':{'target_blog':True,'blank_editor':True,'complete_observation':True}}
        store.verify(key,lease,'editor_checked',evidence); store.begin_operation(key,lease,'upload_image',detail={'path':'fixture'})
        store.release(lease)
        result=workflow.status(self.outputs/'run',execution_root=self.root/'events',environment='simulation')
        self.assertEqual(result['next_episode'],3); self.assertEqual(result['next_action'],'reconcile_input'); self.assertEqual(result['queue'],[]); self.assertFalse(result['live_complete'])


if __name__=='__main__': unittest.main()
