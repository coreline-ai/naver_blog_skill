from pathlib import Path
import copy,json,os,subprocess,sys,tempfile,unittest
from unittest.mock import patch
SCRIPT=Path(__file__).resolve().parents[1]/'skills/naver-blog-wizard/scripts'
sys.path.insert(0,str(SCRIPT))
import wizard_session as w
import wizard_artifacts as a

class WizardSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name).resolve()
    def tearDown(self): self.temp.cleanup()
    def new(self,**opts): return w.new_session(self.root,opts)
    def answer(self,s,v): return w.apply_answer(s,w.next_step(s)['question_id'],v,s['revision'])
    def writing(self,**extra):
        return self.new(task_mode='new',topic='식물 관리',audience='general',article_type='information',tone='plain',length='short',format_preset='auto',**extra)
    def article(self,s):
        root=a.run_root(s); root.mkdir(parents=True,exist_ok=True); p=root/'article.md'
        p.write_text('# 식물 관리\n\n식물의 흙 상태를 확인합니다. 과한 물주기를 피합니다.\n')
        return w.record_event(s,{'type':'article','payload':{'path':str(p)}},s['revision'])
    def test_Q01_initial_fixture_and_invalid_answers(self):
        cases=json.loads((Path(__file__).parent/'fixtures/wizard/question-cases.json').read_text())['cases']
        for case in cases:
            step=w.next_step(self.new(**case['initial']))
            self.assertEqual(step.get('key'),case.get('question'))
            self.assertEqual(step.get('action'),case.get('action'))
        s=self.new(); before=copy.deepcopy(s)
        for v in (None,'','unknown',False):
            with self.assertRaises(w.WizardError): self.answer(s,v)
        self.assertEqual(s,before)
    def test_Q02_supplied_values_not_reasked(self):
        s=self.new(task_mode='new',topic='식물',tone='plain',requested_count=1,presentation='info-slide')
        self.assertEqual(w.next_step(s)['key'],'audience')
        s=self.answer(s,'general'); self.assertEqual(w.next_step(s)['key'],'article_type')
        s=self.answer(s,'information'); self.assertEqual(w.next_step(s)['key'],'length')

    def test_optional_aspect_ratios_validate_initial_change_and_pause_resume(self):
        ratios={'cover':'1:1','inline':'16:9'}
        s=self.new(task_mode='images-only',source_article='article.md',aspect_ratios=ratios)
        self.assertEqual(w.value(s,'aspect_ratios'),ratios)
        self.assertEqual(w.next_step(s)['action'],'use_source_article')
        paused=w.apply_control(s,'pause',s['revision'])
        resumed=w.apply_control(paused,'resume',paused['revision'])
        self.assertEqual(w.value(resumed,'aspect_ratios'),ratios)
        changed=w.apply_change(resumed,'aspect_ratios',{'cover':'4:5'},resumed['revision'])
        self.assertEqual(w.value(changed,'aspect_ratios'),{'cover':'4:5'})
        for invalid in (None,[],True,{'body':'16:9'},{'inline':'2:3'},{'cover':False}):
            with self.subTest(invalid=invalid):
                with self.assertRaises(w.WizardError) as exc:
                    self.new(aspect_ratios=invalid)
                self.assertEqual(exc.exception.code,'INVALID_ANSWER')
                with self.assertRaises(w.WizardError):
                    w.apply_change(s,'aspect_ratios',invalid,s['revision'])
    def test_Q03_modes_skip_irrelevant_questions(self):
        self.assertEqual(w.next_step(self.new(task_mode='images-only',source_article='article.md'))['action'],'use_source_article')
        self.assertEqual(w.next_step(self.new(task_mode='edit-existing'))['key'],'edit_target')
        s=self.article(self.writing(image_action='none')); s=self.answer(s,'use')
        self.assertEqual(w.next_step(s)['kind'],'complete')
        self.assertGreater(s['article']['metrics']['body_char_count'],0); self.assertLess(s['article']['metrics']['body_char_count'],3000)
    def test_A01_no_experience_requires_answer_and_source_based_switch(self):
        s=self.writing(); s=w.apply_change(s,'article_type','review',s['revision'])
        self.assertEqual(w.next_step(s)['key'],'experience_basis')
        s=self.answer(s,'source-based')
        self.assertEqual(w.value(s,'article_type'),'information')
        self.assertEqual(w.next_step(s)['action'],'write_article')
    def test_original_source_is_accepted_without_draft_review(self):
        s=self.article(self.new(task_mode='images-only',source_article='article.md'))
        self.assertEqual(w.next_step(s)['key'],'image_action')
    def test_new_article_blocks_images_until_use(self):
        s=self.article(self.writing(image_action='generate'))
        self.assertEqual(w.next_step(s)['key'],'article_review')
        self.assertIsNone(s['image_plan'])
    def test_Q04_next_is_readonly_and_stale_answer_rejected(self):
        s=self.new(); before=copy.deepcopy(s); first=w.next_step(s)
        self.assertEqual(first,w.next_step(s)); self.assertEqual(s,before)
        new=self.answer(s,'new')
        with self.assertRaises(w.WizardError): w.apply_answer(new,first['question_id'],'rewrite',new['revision'])
        with self.assertRaises(w.WizardError): w.apply_answer(new,first['question_id'],'new',0)
    def test_Q04_CAS_busy_duplicate_and_noop(self):
        s=self.new(); p=a.run_root(s)/'session.json'; p.parent.mkdir(parents=True); w._atomic_save(p,s)
        new=w.update_session(p,0,lambda x:self.answer(x,'new'))
        with self.assertRaises(w.WizardError): w.update_session(p,0,lambda x:x)
        noop=w.apply_change(new,'task_mode','new',new['revision']); self.assertEqual(new,noop)
        lock=p.with_name('session.json.lock'); lock.write_text(str(os.getpid()))
        with self.assertRaises(w.WizardError) as e: w.update_session(p,new['revision'],lambda x:x)
        self.assertEqual(e.exception.code,'SESSION_BUSY'); self.assertTrue(lock.exists())
    def test_Q04_write_failure_preserves_session_and_unlocks(self):
        s=self.new(); p=a.run_root(s)/'session.json'; p.parent.mkdir(parents=True); w._atomic_save(p,s); before=p.read_bytes()
        with patch.object(w.os,'replace',side_effect=OSError('write failed')):
            with self.assertRaises(OSError): w.update_session(p,0,lambda x:self.answer(x,'new'))
        self.assertEqual(p.read_bytes(),before); self.assertFalse(p.with_name('session.json.lock').exists())
    def test_Q05_change_invalidates_article_and_preserves_file(self):
        s=self.article(self.writing()); p=Path(s['article']['path']); before=p.read_bytes()
        s=self.answer(s,'use'); s=w.apply_change(s,'tone','friendly',s['revision'])
        self.assertIsNone(s['article']); self.assertEqual(p.read_bytes(),before)
        self.assertEqual(w.next_step(s)['action'],'write_article')
    def test_pause_resume_preserves_options(self):
        s=self.writing(); paused=w.apply_control(s,'pause',0)
        self.assertEqual(w.next_step(paused)['kind'],'paused')
        resumed=w.apply_control(paused,'resume',1)
        self.assertEqual(w.next_step(resumed)['action'],'write_article')
        self.assertEqual(resumed['confirmed_options'],s['confirmed_options'])
    def test_stale_article_never_completes(self):
        s=self.article(self.writing(image_action='none')); s=self.answer(s,'use')
        Path(s['article']['path']).write_text('# 변조\n\n원고 변경\n')
        self.assertEqual(w.next_step(s)['action'],'repair_artifacts')
    def test_review_change_only_reasks_selected_option(self):
        s=self.article(self.writing()); s=self.answer(s,'change'); s=self.answer(s,'tone')
        self.assertEqual(w.next_step(s)['key'],'tone'); self.assertEqual(w.value(s,'length'),'short')
    def test_count_validation_and_explicit_auto(self):
        for v in (0,-1,True,1.5,'5'):
            with self.assertRaises(w.WizardError): self.new(requested_count=v)
        s=self.new(requested_count='auto'); self.assertEqual(w.value(s,'requested_count'),5)
        self.assertEqual(s['confirmed_options']['requested_count']['origin'],'explicit-default')
    def test_untyped_phase_patch_and_forged_completion_rejected(self):
        s=self.new()
        with self.assertRaises(w.WizardError): w.record_event(s,{'type':'patch','payload':{'phase':'complete'}},0)
        with self.assertRaises(w.WizardError): w.record_event(s,{'type':'package','payload':{'manifest_path':'x','composed_article_path':'y','completion_path':'z'}},0)
    def test_skill_work_root_and_symlink_session_rejected(self):
        with self.assertRaises(w.WizardError): w.new_session(SCRIPT,{})
        target=self.root/'target'; target.write_text('{}'); alias=self.root/'link'; alias.symlink_to(target)
        with self.assertRaises(w.WizardError): w.session_path(alias)


    def test_redirected_session_root_is_rejected(self):
        s=self.new(); p=a.run_root(s)/'session.json'; p.parent.mkdir(parents=True); w._atomic_save(p,s)
        s['work_root']=str(self.root/'other'); w._atomic_save(p,s)
        with self.assertRaises(w.WizardError): w.load_session(p)
    def test_dead_pid_lock_recovers_under_os_guard(self):
        s=self.new(); p=a.run_root(s)/'session.json'; p.parent.mkdir(parents=True); w._atomic_save(p,s)
        lock=p.with_name('session.json.lock'); lock.write_text('123456789')
        with patch.object(w.os,'kill',side_effect=ProcessLookupError):
            new=w.update_session(p,0,lambda x:self.answer(x,'new'))
        self.assertEqual(new['revision'],1); self.assertFalse(lock.exists())
    def test_guard_symlink_does_not_write_outside_session(self):
        s=self.new(); p=a.run_root(s)/'session.json'; p.parent.mkdir(parents=True); w._atomic_save(p,s)
        outside=self.root/'outside'; outside.write_text('unchanged'); p.with_name('session.json.guard').symlink_to(outside)
        with self.assertRaises(w.WizardError): w.update_session(p,0,lambda x:self.answer(x,'new'))
        self.assertEqual(outside.read_text(),'unchanged')


    def test_actual_competing_process_cannot_lose_a_revision(self):
        s=self.new(); path=a.run_root(s)/'session.json'; path.parent.mkdir(parents=True); w._atomic_save(path,s)
        script="import sys,time; sys.path.insert(0,sys.argv[1]); import wizard_session as w\ndef mutate(s):\n print('READY',flush=True); time.sleep(0.15); return w.apply_answer(s,w.next_step(s)['question_id'],'new',0)\nw.update_session(sys.argv[2],0,mutate)"
        with subprocess.Popen([sys.executable,'-B','-c',script,str(SCRIPT),str(path)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) as process:
            self.assertEqual(process.stdout.readline().strip(),'READY')
            with self.assertRaises(w.WizardError) as exc: w.update_session(path,0,lambda x:x)
            self.assertEqual(exc.exception.code,'SESSION_BUSY')
            _,err=process.communicate(timeout=5); self.assertEqual(process.returncode,0,err)
        self.assertEqual(w.load_session(path)['revision'],1)
    def test_real_cli_initial_answer_and_stale_delivery(self):
        initial=self.root/'initial.json'; initial.write_text(json.dumps({'task_mode':'new','topic':'식물','tone':'plain'}))
        script=str(SCRIPT/'wizard_session.py')
        init=subprocess.run([sys.executable,'-B',script,'init','--work-root',str(self.root),'--initial-options',str(initial)],capture_output=True,text=True)
        self.assertEqual(init.returncode,0,init.stderr); result=json.loads(init.stdout); path=Path(result['session']); q=result['step']
        self.assertEqual(q['key'],'audience')
        args=[sys.executable,'-B',script,'answer','--session',str(path),'--question-id',q['question_id'],'--value-json',json.dumps('general'),'--expected-revision','0']
        first=subprocess.run(args,capture_output=True,text=True); self.assertEqual(first.returncode,0,first.stderr)
        before=path.read_bytes(); again=subprocess.run(args,capture_output=True,text=True)
        self.assertEqual(again.returncode,2); self.assertEqual(json.loads(again.stderr)['code'],'REVISION_CONFLICT'); self.assertEqual(path.read_bytes(),before)

if __name__=='__main__': unittest.main()
