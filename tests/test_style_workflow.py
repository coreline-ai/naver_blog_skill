from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
for relative in ('scripts', 'skills/naver-blog-wizard/scripts', 'skills/naver-series-workflow/scripts'):
    sys.path.insert(0, str(ROOT / relative))
import select_article_style as style
import wizard_session as wizard
import wizard_artifacts as artifacts
import prepare_series as workflow
import test_prepare_series_v2 as series_tests


def selection(title, kind, *, requested='auto', basis=None):
    return style.select_style(title, requested_type=requested,
        intent={'article_type': kind, 'reason': f'독자의 질문에 {kind} 구조의 기준과 적용 순서로 답하는 제목'},
        experience_basis=basis)


class WizardStyleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()

    def tearDown(self):
        self.temp.cleanup()

    def session(self, **kw):
        return wizard.new_session(self.root, {'task_mode': 'new', 'topic': '무료 vs 유료 차이',
            'article_type': 'auto', 'audience': 'general', 'tone': 'friendly',
            'length': 'short', 'format_preset': 'auto', **kw})

    def article(self, session, title, selected=None):
        root = artifacts.run_root(session); root.mkdir(parents=True, exist_ok=True)
        path = root / 'article.md'; path.write_text(f'# {title}\n\n확인한 조건을 구분해 정리합니다.\n')
        payload = {'path': str(path)}
        if selected is not None: payload['style_selection'] = selected
        return wizard.record_event(session, {'type': 'article', 'payload': payload}, session['revision'])

    def test_auto_action_candidate_and_final_semantics(self):
        s = self.session()
        action = wizard.next_step(s)
        self.assertEqual(action['action'], 'write_article')
        self.assertEqual(action['writing_style']['article_type'], 'comparison')
        with self.assertRaises(style.StyleError) as caught: self.article(s, '무료 vs 유료 차이')
        self.assertEqual(caught.exception.code, 'STYLE_INTENT_REQUIRED')
        s = self.article(s, '무료 vs 유료 차이', selection('무료 vs 유료 차이', 'comparison'))
        self.assertEqual(s['article']['style_selection']['primary_style'], 'comparison')
        self.assertEqual(wizard.next_step(s)['key'], 'article_review')
        self.assertEqual(wizard.value(s, 'tone'), 'friendly')

    def test_explicit_type_wins_and_missing_experience_asks(self):
        s = self.session(article_type='expert')
        self.assertEqual(wizard.next_step(s)['writing_style']['article_type'], 'expert')
        s = self.article(s, '무료 vs 유료 차이')
        self.assertEqual(s['article']['style_selection']['article_type'], 'expert')
        review = self.session(topic='내돈내산 사용 후기')
        self.assertEqual(wizard.next_step(review)['key'], 'experience_basis')
        q = wizard.next_step(review)
        review = wizard.apply_answer(review, q['question_id'], 'source-based', review['revision'])
        self.assertEqual(wizard.next_step(review)['writing_style']['status'], 'needs_title_revision')
        with self.assertRaises(style.StyleError): self.article(review, '내돈내산 사용 후기')

    def test_stale_and_option_mismatch_rejected(self):
        s = self.session()
        with self.assertRaises(style.StyleError): self.article(s, '다른 최종 제목', selection('이전 제목', 'information'))
        with self.assertRaises(ValueError): self.article(s, '최종 제목', selection('최종 제목', 'information', requested='information'))

    def test_images_only_and_legacy_article_are_not_reclassified(self):
        s = wizard.new_session(self.root, {'task_mode':'images-only', 'source_article':'article.md'})
        s = self.article(s, '내돈내산 후기')
        self.assertNotIn('style_selection', s['article'])
        self.assertEqual(wizard.next_step(s)['key'], 'image_action')
        old = self.session(article_type='information')
        root = artifacts.run_root(old); root.mkdir(parents=True)
        path = root/'old.md'; path.write_text('# 예전 제목\n\n예전 본문입니다.\n')
        old['article'] = artifacts.register_article(path, root)
        self.assertTrue(artifacts.inspect_bindings(old)['ok'])
        self.assertNotIn('style_selection', old['article'])

    def test_legacy_auto_and_story_sessions_are_not_reopened_for_experience(self):
        for kind in ['auto', 'story']:
            old=self.session(article_type=kind, topic='남이섬 방문 후기')
            root=artifacts.run_root(old); root.mkdir(parents=True)
            path=root/'old.md'; path.write_text('# 예전 방문 후기\n\n기존에 작성된 원고입니다.\n')
            old['article']=artifacts.register_article(path, root)
            self.assertEqual(wizard.next_step(old)['key'], 'article_review')
            self.assertNotIn('style_selection', old['article'])

    def test_image_adapter_receives_resolved_type_and_explicit_format(self):
        s = self.session(requested_count=1, presentation='info-slide', format_preset='magazine')
        s = self.article(s, '무료 vs 유료 차이', selection('무료 vs 유료 차이', 'comparison'))
        path = Path(s['article']['path'])
        slots=[{'id':'cover','role':'cover','placement':'cover','purpose':'두 선택의 차이','mode':'infographic-diagram',
                'prompt':'상황별로 다른 두 선택','alt':'두 선택'}]
        request=artifacts.compile_image_request(s, {'path':str(path),'sha256':artifacts.file_sha(path)}, slots)
        self.assertEqual(request['article_type'], 'comparison')
        self.assertEqual(request['format_preset'], 'magazine')
        self.assertEqual(request['requested_count'], 1)
        self.assertEqual(request['presentation'], 'info-slide')

    def test_style_record_tampering_is_not_ready(self):
        s = self.session()
        s = self.article(s, '무료 vs 유료 차이', selection('무료 vs 유료 차이', 'comparison'))
        s['article']['style_selection']['article_type'] = 'review'
        self.assertEqual(wizard.next_step(s)['action'], 'repair_artifacts')

    def test_illustrative_story_never_becomes_user_experience(self):
        evidence='가정 사례임을 공개한 초보자의 준비 과정'
        basis={'type':'illustrative','evidence':[evidence]}
        for answer in [basis, evidence]:
            s=self.session(article_type='story',topic='초보자의 준비 과정',experience_basis=answer)
            s=self.article(s,'초보자의 준비 과정',selection('초보자의 준비 과정','story',requested='story',basis=basis))
            self.assertEqual(s['article']['style_selection']['experience_basis']['type'], 'illustrative')
        s=self.session(article_type='story',topic='초보자의 준비 과정',experience_basis=evidence)
        s=self.article(s,'초보자의 준비 과정')
        self.assertEqual(s['article']['style_selection']['experience_basis']['type'], 'illustrative')
        review=self.session(article_type='review',topic='사용 후기',experience_basis=basis)
        with self.assertRaises(style.StyleError): self.article(review,'사용 후기')

    def test_absent_experience_text_is_not_evidence(self):
        s=self.session(article_type='review',topic='내돈내산 후기',experience_basis='경험 없음')
        with self.assertRaises(style.StyleError): self.article(s,'내돈내산 후기')


class SeriesStyleTests(unittest.TestCase):
    def setUp(self):
        self.f = series_tests.SeriesPreparationV2Tests()
        self.f.setUp()

    def tearDown(self):
        self.f.tearDown()

    def set_style(self, ep=1, kind='comparison', basis=None):
        folder = self.f.inputs / f'episode-{ep:02d}'
        title = '비교 제목' if kind == 'comparison' else '실제 사용 후기' if kind == 'review' else '정보 제목'
        article=folder/'article.md'
        article.write_text(article.read_text().replace('# 제목\n', f'# {title}\n'))
        data=json.loads((folder/'editorial.json').read_text())
        data['style_selection']=selection(title, kind, basis=basis)
        if basis is not None: data['experience_basis']=basis
        (folder/'editorial.json').write_text(workflow.encoded(data))
        return folder

    def approve_from_templates(self, run='pending'):
        result=self.f.prepare(run)
        for item in result['episodes']:
            ep=item['episode']
            template=json.loads((self.f.outputs/run/f'episode-{ep:02d}'/'review-template.json').read_text())
            template.update(status='passed', reviewed_by='synthetic-regression', reviewed_at='2026-10-17T00:00:00+09:00')
            for check in template['checks']:
                check.update(status='passed', evidence=[{'location':f'{ep}편 본문 검수 위치',
                    'finding':f'{ep}편의 {check["id"]} 조건을 이 회차 기준으로 확인한 테스트 근거입니다.', 'source_refs':[]}])
            (self.f.inputs/f'episode-{ep:02d}'/'review.json').write_text(workflow.encoded(template))
        return result

    def test_per_episode_profiles_and_unchanged_counts(self):
        self.set_style()
        self.f.add_episode(2)
        self.f.data['requested_episodes']=[1,2]; self.f.save()
        self.set_style(2, 'information')
        result=self.approve_from_templates()
        one=json.loads((self.f.outputs/'pending/episode-01/review-template.json').read_text())
        two=json.loads((self.f.outputs/'pending/episode-02/review-template.json').read_text())
        self.assertIn('symmetric_decision_criteria', {x['id'] for x in one['checks']})
        self.assertIn('expert_information_assets', {x['id'] for x in two['checks']})
        self.assertEqual(result['requirements']['target_images_per_episode'], 5)
        self.assertEqual(result['requirements']['min_body_chars'], 3000)
        ready=self.f.prepare('ready')
        self.assertEqual(ready['queue'], [1,2])
        self.assertEqual(workflow.read_snapshot(self.f.outputs/'ready'), ready)
        status=workflow.status(self.f.outputs/'ready')
        self.assertEqual(status['integrity'], 'passed')
        self.assertFalse(status['live_complete'])
        self.assertFalse(status['ui_authorized'])

    def test_legacy_snapshot_does_not_get_style_record(self):
        result=self.f.prepare('legacy')
        self.assertNotIn('style_selection', result['episodes'][0])
        self.assertEqual(workflow.read_snapshot(self.f.outputs/'legacy'), result)

    def test_missing_experience_and_stale_title_block(self):
        folder=self.set_style(kind='review')
        result=self.f.prepare(check=True)
        self.assertIn('NEEDS_EXPERIENCE', result['episodes'][0]['error_codes'])
        self.assertEqual(result['queue'], [])
        data=json.loads((folder/'editorial.json').read_text())
        data['style_selection']=selection('이전 제목', 'information')
        (folder/'editorial.json').write_text(workflow.encoded(data))
        self.assertIn('STALE_STYLE_SELECTION', self.f.prepare(check=True)['episodes'][0]['error_codes'])

    def test_real_experience_and_editorial_agreement(self):
        basis={'type':'user_provided','evidence':['사용자 제공 실제 사용 메모']}
        folder=self.set_style(kind='review', basis=basis)
        self.assertEqual(self.f.prepare(check=True)['episodes'][0]['status'], 'review_pending')
        data=json.loads((folder/'editorial.json').read_text()); data.pop('experience_basis')
        (folder/'editorial.json').write_text(workflow.encoded(data))
        self.assertIn('INVALID_STYLE_SELECTION', self.f.prepare(check=True)['episodes'][0]['error_codes'])

    def test_explicit_null_cannot_skip_experience_binding(self):
        folder=self.set_style(kind='review',basis={'type':'user_provided','evidence':['실제 사용 기록']})
        data=json.loads((folder/'editorial.json').read_text())
        data['experience_basis']=None
        # Even a non-review profile must not bypass the title's experience promise.
        data['style_selection']=selection('실제 사용 후기','information',basis={'type':'user_provided','evidence':['실제 사용 기록']})
        (folder/'editorial.json').write_text(workflow.encoded(data))
        result=self.f.prepare(check=True)
        self.assertIn('INVALID_STYLE_SELECTION',result['episodes'][0]['error_codes'])
        self.assertEqual(result['queue'],[])

    def test_structure_change_invalidates_review_even_with_same_profile_checks(self):
        folder=self.set_style(kind='information')
        self.approve_from_templates()
        ready=self.f.prepare('ready'); self.assertEqual(ready['queue'],[1])
        data=json.loads((folder/'editorial.json').read_text())
        data['style_selection']=selection('정보 제목','checklist')
        (folder/'editorial.json').write_text(workflow.encoded(data))
        changed=self.f.prepare('changed')
        self.assertEqual(changed['episodes'][0]['content_revision'],ready['episodes'][0]['content_revision'])
        self.assertEqual(changed['episodes'][0]['status'],'stale_review')
        self.assertEqual(changed['queue'],[])
        self.assertEqual(workflow.read_snapshot(self.f.outputs/'changed'),changed)
        self.assertFalse(workflow.status(self.f.outputs/'ready')['integrity']=='passed')

    def test_three_sibling_legacy_install_works_without_common_helper(self):
        isolated=self.f.root/'isolated'
        for name in ['naver-series-workflow','naver-smarteditor-drafter','seo-series-writer']:
            shutil.copytree(ROOT/'skills'/name,isolated/name,ignore=shutil.ignore_patterns('__pycache__'))
        cli=isolated/'naver-series-workflow/scripts/prepare_series.py'
        helped=subprocess.run([sys.executable,'-B',str(cli),'--help'],capture_output=True,text=True)
        self.assertEqual(helped.returncode,0,helped.stderr)
        self.f.data['requirements']={'visual_mode':'none'}
        self.f.data['episodes'][0].pop('image_slots')
        self.f.save()
        article=self.f.inputs/'episode-01/article.md';article.write_text('# 제목\n\n'+'정보 문장입니다. '*400)
        args=[sys.executable,'-B',str(cli),'prepare','--manifest',str(self.f.manifest),
              '--input-root',str(self.f.inputs),'--output-root',str(self.f.outputs),'--run-id','isolated','--check']
        prepared=subprocess.run(args,capture_output=True,text=True)
        self.assertNotIn('ModuleNotFoundError',prepared.stderr)
        report=json.loads(prepared.stdout)
        self.assertEqual(report['episodes'][0]['status'],'review_pending')
        self.set_style(kind='information')
        new=subprocess.run(args,capture_output=True,text=True)
        self.assertIn('DEPENDENCY_MISSING',json.loads(new.stdout)['episodes'][0]['error_codes'])

    def test_hint_only_cannot_be_finalized(self):
        folder=self.set_style()
        data=json.loads((folder/'editorial.json').read_text())
        data['style_selection']=style.select_style('비교 제목')
        (folder/'editorial.json').write_text(workflow.encoded(data))
        self.assertIn('STYLE_INTENT_REQUIRED', self.f.prepare(check=True)['episodes'][0]['error_codes'])

    def test_rehashed_snapshot_summary_tampering_rejected(self):
        self.set_style(); self.approve_from_templates(); self.f.prepare('ready')
        run=self.f.outputs/'ready'
        report=json.loads((run/'series-report.json').read_text())
        report['episodes'][0]['style_selection']['primary_style']='expert'
        (run/'series-report.json').write_text(workflow.encoded(report))
        self.f.rehash_snapshot(run, 'series-report.json', ready=True)
        with self.assertRaises(workflow.BuildError): workflow.read_snapshot(run)

    def test_removing_required_per_style_review_rejected(self):
        self.set_style(); self.approve_from_templates(); self.f.prepare('ready')
        run=self.f.outputs/'ready'; path=run/'episode-01/review.json'
        review=json.loads(path.read_text())
        review['checks']=[x for x in review['checks'] if x['id']!='symmetric_decision_criteria']
        path.write_text(workflow.encoded(review))
        self.f.rehash_snapshot(run, 'episode-01/review.json', ready=True)
        with self.assertRaises(workflow.BuildError): workflow.read_snapshot(run)


if __name__ == '__main__':
    unittest.main()
