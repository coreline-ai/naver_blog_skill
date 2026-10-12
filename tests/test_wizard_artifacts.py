from pathlib import Path
import copy,json,shutil,subprocess,sys,tempfile,unittest
from PIL import Image
SCRIPT=Path(__file__).resolve().parents[1]/'skills/naver-blog-wizard/scripts'
sys.path.insert(0,str(SCRIPT))
import wizard_session as w
import wizard_artifacts as a
from post_contract import BuildError

class WizardArtifactTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.work=Path(self.temp.name).resolve()
    def tearDown(self): self.temp.cleanup()
    def answer(self,s,v): return w.apply_answer(s,w.next_step(s)['question_id'],v,s['revision'])
    def record(self,s,kind,p): return w.record_event(s,{'type':kind,'payload':p},s['revision'])
    def plan(self,n=1,presentation='standard',action='use-files'):
        s=w.new_session(self.work,{'task_mode':'images-only','source_article':'source.md','image_action':action,
            'presentation':presentation,'requested_count':n,'additional_requirements':'none','reference_use':'no'})
        root=a.run_root(s); root.mkdir(parents=True)
        text='# 식물 관리\n\n햇빛은 잎의 상태에 맞게 조절합니다. 물은 흙이 마른 뒤 줍니다.\n\n'
        details=['빛이 닿는 방향을 확인합니다. 잎이 빛을 받도록 위치를 조절합니다.','실내 공기가 통하도록 둡니다. 찬 바람이 직접 닿지 않게 합니다.','화분 아래 배수 구멍을 확인합니다. 고인 물은 비워 줍니다.','마른 잎을 살펴봅니다. 손상된 잎을 정리합니다.']
        for i in range(1,n): text+=f'## 관리 단계 {i}\n\n{details[i-1]}\n\n'
        article=root/'article.md'; article.write_text(text)
        s=self.record(s,'article',{'path':str(article)})
        slots=[{'id':'cover' if i==0 else f'section-{i}','role':'cover' if i==0 else 'inline',
                'purpose':f'관리 설명 {i}','prompt':f'실내 화분의 관리 과정 {i}',
                'mode':'photorealistic-natural','heading_hint':'' if i==0 else f'관리 단계 {i}',
                'placement':'H1 아래' if i==0 else f'관리 단계 {i} 뒤','alt':f'식물 관리 {i}'} for i in range(n)]
        marked=text.replace('# 식물 관리\n','# 식물 관리\n<!-- naver-image:cover -->\n',1)
        for i in range(1,n):
            paragraph=details[i-1]+'\n'
            marked=marked.replace(paragraph,paragraph+f'<!-- naver-image:section-{i} -->\n',1)
        candidate=root/'article-slots.md'; candidate.write_text(marked)
        slotfile=root/'slots.json'; slotfile.write_text(json.dumps({'slots':slots},ensure_ascii=False))
        s=self.record(s,'slots',{'article_path':str(candidate),'slots_path':str(slotfile)})
        prep=a.prepare_plan(s)
        self.assertEqual(prep['status'],'planned',prep)
        s=self.record(s,'plan',prep['payload']); s=self.answer(s,'use')
        return s
    def image(self,s,provenance='user-file',color=None):
        step=w.next_step(s); ident=step['slot_id']; root=a.run_root(s)
        file=a.version_path(root,ident,'.png')
        Image.new('RGB',(40,50),color or ('red' if ident=='cover' else 'blue')).save(file)
        if provenance=='user-file': return self.record(s,'effect-result',{'slot_id':ident,'path':str(file),'provenance':provenance})
        s=self.record(s,'effect-intent',{'slot_id':ident})
        return self.record(s,'effect-result',{'slot_id':ident,'path':str(file),'provenance':provenance,'effect_id':s['effect']['id'],'tool_result':'test fixture simulates a tool return; not live generation'})
    def qa(self,s,passed=True):
        step=w.next_step(s); asset=step['asset']
        return self.record(s,'visual-review',{'slot_id':step['slot_id'],'asset_sha256':asset['inspection']['sha256'],'passed':passed,'notes':'Test fixture review metadata; live visual QA not performed.'})
    def ready(self,n=1,presentation='standard'):
        s=self.plan(n,presentation)
        for i in range(n): s=self.qa(self.image(s,color=('red','blue','green','yellow','purple')[i]))
        return self.answer(s,'use')
    def test_A02_one_slide_no_series_floor(self):
        s=self.plan(presentation='info-slide'); entries=a.plan_entries(s)
        self.assertEqual(len(entries),1); self.assertEqual(entries[0]['presentation'],'info-slide')
        self.assertEqual(w.next_step(s)['action'],'import_image')
    def test_A02_mixed_three_and_five_exact_counts(self):
        s=self.plan(3,'mixed','prompt-only'); entries=a.plan_entries(s)
        self.assertEqual([e['presentation'] for e in entries],['standard','info-slide','info-slide'])
        self.assertEqual(w.next_step(s)['kind'],'complete'); self.assertEqual(s['assets'],[])
        s=self.plan(5,'standard','prompt-only'); self.assertEqual(len(a.plan_entries(s)),5)
    def test_A03_body_marker_and_count_rejected(self):
        s=self.plan(); root=a.run_root(s); original=Path(s['article']['path']).read_bytes()
        candidate=root/'changed.md'; candidate.write_bytes(Path(s['slot_selection']['path']).read_bytes()+b'\n')
        with self.assertRaises(BuildError): a.validate_slot_article(s['article']['path'],candidate,s['slot_selection']['slots'],root)
        self.assertEqual(Path(s['article']['path']).read_bytes(),original)
        slots=copy.deepcopy(s['slot_selection']['slots']); slots[0]['id']='other'
        with self.assertRaises(BuildError): a.validate_slot_article(s['article']['path'],s['slot_selection']['path'],slots,root)
    def test_A04_slide_brief_shortage_and_duplicate_block(self):
        plan={'entries':[{'id':'a','presentation':'info-slide','brief':{'points':['한 문장']}}]}
        self.assertEqual(a.validate_slide_briefs(plan)[0]['code'],'SLIDE_BRIEF_INSUFFICIENT')
        plan['entries'][0]['brief']['points']=['첫 요점입니다.','두 번째 요점입니다.']
        plan['entries'].append({**plan['entries'][0],'id':'b'})
        self.assertEqual(a.validate_slide_briefs(plan)[0]['code'],'SLIDE_BRIEF_DUPLICATE')
    def test_A05_marker_inside_code_rejected(self):
        root=self.work; source=root/'source.md'; source.write_text('# 제목\n\n```\n내용\n```\n')
        marked=root/'marked.md'; marked.write_text('# 제목\n\n```\n<!-- naver-image:cover -->\n내용\n```\n')
        slot={'id':'cover','role':'cover','purpose':'목적','prompt':'장면','mode':'stylized-concept'}
        with self.assertRaises(BuildError): a.validate_slot_article(source,marked,[slot],root)
    def test_A06_fake_unsupported_and_symlink_assets(self):
        s=self.plan(); root=a.run_root(s)
        fake=root/'fake.png'; fake.write_text('not an image')
        bad=root/'bad.webp'; Image.new('RGB',(40,50)).save(bad)
        for path in (fake,bad):
            with self.assertRaises(BuildError): a.bind_asset(s,'cover',path,'user-file')
        target=root/'real.png'; Image.new('RGB',(40,50)).save(target); link=root/'link.png'; link.symlink_to(target)
        with self.assertRaises(BuildError): a.bind_asset(s,'cover',link,'user-file')
    def test_A07_changed_input_reference_asset_never_completes(self):
        s=self.qa(self.image(self.plan())); asset=s['assets'][0]
        Image.new('RGB',(40,50),'green').save(asset['inspection']['path'])
        self.assertEqual(w.next_step(s)['action'],'repair_artifacts')
        self.assertFalse(a.inspect_bindings(s)['ok'])
    def test_A08_actual_package_and_missing_QA_gate(self):
        s=self.plan(); s=self.image(s)
        with self.assertRaises(BuildError): a.compose_and_verify(s,a.run_root(s))
        s=self.qa(s); s=self.answer(s,'use'); payload=a.compose_and_verify(s,a.run_root(s))
        report=a.read_json(payload['completion_path']); self.assertEqual(report['status'],'package_verified')
        self.assertFalse(report['generation_verified']); self.assertFalse(report['visual_qa_verified'])
        s=self.record(s,'package',payload); self.assertEqual(w.next_step(s)['kind'],'complete')
        Path(payload['composed_article_path']).write_text('missing body')
        self.assertEqual(w.next_step(s)['action'],'repair_artifacts')
    def test_A08_duplicates_and_wrong_slide_ratio(self):
        s=self.plan(2); s=self.qa(self.image(s)); duplicate=s['assets'][0]['inspection']['path']
        with self.assertRaises(BuildError): self.record(s,'effect-result',{'slot_id':'section-1','path':duplicate,'provenance':'user-file'})
        s=self.plan(presentation='info-slide'); bad=a.run_root(s)/'ratio.png'; Image.new('RGB',(40,40)).save(bad)
        with self.assertRaises(BuildError): a.bind_asset(s,'cover',bad,'user-file')
    def test_A09_one_slot_edit_preserves_other_reviewed_assets(self):
        s=self.ready(2); other=copy.deepcopy(s['assets'][1]); s=w.apply_change(s,'image_review','edit',s['revision']); s=self.answer(s,'cover'); s=self.answer(s,'표지의 화분을 녹색으로 바꿔 주세요')
        self.assertEqual(w.next_step(s)['action'],'revise_slot_plan')
        slots=copy.deepcopy(s['slot_selection']['slots']); slots[0]['prompt']+=' '+w.value(s,'edit_instruction')
        root=a.run_root(s); slotsfile=root/'slots-edit.json'; slotsfile.write_text(json.dumps({'slots':slots},ensure_ascii=False))
        s=self.record(s,'slots',{'article_path':s['slot_selection']['path'],'slots_path':str(slotsfile)})
        prep=a.prepare_plan(s); s=self.record(s,'plan',prep['payload']); s=self.answer(s,'use')
        self.assertEqual(w.next_step(s)['action'],'edit_image'); self.assertEqual(s['assets'][1],other)
        s=self.qa(self.image(s,'edited','green')); s=self.answer(s,'use')
        self.assertEqual(w.next_step(s)['action'],'compose_article'); self.assertEqual(s['assets'][1],other)
    def test_R01_unreturned_intent_is_reconcile_not_regeneration(self):
        s=self.plan(action='generate'); s=self.record(s,'effect-intent',{'slot_id':'cover'})
        self.assertEqual(w.next_step(s)['action'],'reconcile'); ident=s['effect']['id']
        s=w.apply_control(s,'pause',s['revision']); s=w.apply_control(s,'resume',s['revision'])
        self.assertEqual(s['effect']['id'],ident); self.assertEqual(w.next_step(s)['action'],'reconcile')
    def test_R02_user_files_require_no_generated_proof(self):
        s=self.ready(); self.assertEqual(s['assets'][0]['provenance'],'user-file'); self.assertIsNone(s['effect'])
        p=a.compose_and_verify(s,a.run_root(s)); s=self.record(s,'package',p)
        self.assertEqual(w.next_step(s)['kind'],'complete')
    def test_R03_forged_plan_and_composition_record_rejected(self):
        s=self.plan(); bad=copy.deepcopy(s['image_plan']['data']); bad['generation_performed']=True
        p=a.run_root(s)/'forged.json'; a.write_json(p,bad)
        with self.assertRaises(BuildError): a.register_plan(s,{'request_path':s['image_plan']['request_path'],'plan_path':str(p)})
    def test_generated_proof_needs_current_effect(self):
        s=self.plan(action='generate'); p=a.run_root(s)/'image.png'; Image.new('RGB',(40,50)).save(p)
        with self.assertRaises(w.WizardError): self.record(s,'effect-result',{'slot_id':'cover','path':str(p),'provenance':'generated'})
        s=self.image(s,'generated'); self.assertEqual(w.next_step(s)['action'],'visual_review')
    def test_standalone_edit_without_fake_article(self):
        s=w.new_session(self.work,{'task_mode':'edit-existing','edit_instruction':'배경을 녹색으로'})
        root=a.run_root(s); root.mkdir(parents=True); original=root/'original.png'; Image.new('RGB',(40,50),'red').save(original)
        s=w.apply_change(s,'edit_target',str(original),s['revision']); self.assertEqual(w.next_step(s)['action'],'edit_image')
        s=self.image(s,'edited','green'); s=self.qa(s); s=self.answer(s,'use')
        self.assertEqual(w.next_step(s)['kind'],'complete'); self.assertIsNone(s['article']); self.assertIsNone(s['image_plan'])
    def test_correction_stops_after_one_attempt(self):
        s=self.qa(self.image(self.plan(action='generate'),'generated'),False)
        self.assertEqual(w.next_step(s)['action'],'repair_image')
        s=self.qa(self.image(s,'edited','green'),False)
        self.assertEqual(w.next_step(s)['key'],'failure_resolution')
    def test_current_options_cannot_be_hidden_by_plan(self):
        s=self.plan(); changed=copy.deepcopy(s); w._set_option(changed,'presentation','mixed')
        with self.assertRaises(BuildError): a.register_plan(changed,{'request_path':s['image_plan']['request_path'],'plan_path':s['image_plan']['path']})
    def test_external_reference_is_staged_and_preserves_slots(self):
        s=self.plan(); root=a.run_root(s); ref=self.work/'reference.png'; Image.new('RGB',(40,50),'red').save(ref)
        # Set confirmed reference while keeping a known marker selection for this test.
        w._set_option(s,'reference_use','yes'); w._set_option(s,'reference_path',str(ref)); w._set_option(s,'reference_instructions','default')
        s['image_plan']=None; w._drop(s,'image_plan_review')
        result=a.prepare_plan(s); self.assertIn('change',result)
        s=w.apply_change(s,'reference_path',result['change']['value'],s['revision']); self.assertIsNotNone(s['slot_selection'])
        result=a.prepare_plan(s); self.assertEqual(result['status'],'planned')
    def test_R04_cli_readonly_and_relocated_without_source_repo(self):
        s=self.plan(action='prompt-only'); root=a.run_root(s); path=root/'session.json'; w._atomic_save(path,s); before=path.read_bytes()
        result=subprocess.run([sys.executable,'-B',str(SCRIPT/'wizard_session.py'),'next','--session',str(path)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr); self.assertEqual(json.loads(result.stdout)['kind'],'complete'); self.assertEqual(path.read_bytes(),before)
        target=self.work/'relocated'; target.mkdir()
        for name in ('scripts','skills'): shutil.copytree(SCRIPT.parents[2]/name,target/name,ignore=shutil.ignore_patterns('__pycache__'))
        cmd=[sys.executable,'-B',str(target/'skills/naver-blog-wizard/scripts/wizard_session.py'),'next','--session',str(path)]
        result=subprocess.run(cmd,capture_output=True,text=True); self.assertEqual(result.returncode,0,result.stderr)
        (target/'scripts/build_blog_image_prompts.py').unlink()
        result=subprocess.run(cmd,capture_output=True,text=True); self.assertNotEqual(result.returncode,0); self.assertIn('DEPENDENCY_MISSING',result.stderr)


    def test_caption_changes_only_composition(self):
        s=self.ready(); asset=copy.deepcopy(s['assets'][0]); payload=a.compose_and_verify(s,a.run_root(s)); s=self.record(s,'package',payload)
        s=w.apply_change(s,'caption:cover','실내 화분 관리 예시',s['revision'])
        self.assertEqual(w.next_step(s)['action'],'compose_article')
        self.assertEqual(s['assets'][0]['qa'],asset['qa']); self.assertEqual(s['assets'][0]['inspection'],asset['inspection'])
        payload=a.compose_and_verify(s,a.run_root(s)); self.assertIn('실내 화분 관리 예시',Path(payload['composed_article_path']).read_text())
        self.assertEqual(a.read_json(payload['manifest_path'])['version'],1)
    def test_alt_changes_accessibility_without_regenerating_standard_image(self):
        s=self.ready(2); original=copy.deepcopy(s['assets'][0]); other=copy.deepcopy(s['assets'][1])
        s=w.apply_change(s,'alt:cover','햇빛을 받는 실내 화분',s['revision'])
        self.assertEqual(w.next_step(s)['action'],'revise_slot_metadata')
        slots=copy.deepcopy(s['slot_selection']['slots']); slots[0]['alt']='햇빛을 받는 실내 화분'
        p=a.run_root(s)/'slots-alt.json'; a.write_json(p,{'slots':slots})
        s=self.record(s,'slots',{'article_path':s['slot_selection']['path'],'slots_path':str(p)})
        prep=a.prepare_plan(s); s=self.record(s,'plan',prep['payload']); s=self.answer(s,'use')
        self.assertEqual(w.next_step(s)['action'],'visual_review')
        self.assertEqual(s['assets'][0]['inspection'],original['inspection']); self.assertEqual(s['assets'][1],other)
    def test_count_reduction_reuses_matching_assets_and_keeps_excluded_files(self):
        s=self.ready(5); assets=copy.deepcopy(s['assets']); selection=copy.deepcopy(s['slot_selection'])
        s=w.apply_change(s,'requested_count',3,s['revision'])
        text=Path(selection['path']).read_text()
        for ident in ('section-3','section-4'): text=text.replace(f'<!-- naver-image:{ident} -->\n','')
        root=a.run_root(s); marked=root/'three.md'; marked.write_text(text); slotfile=root/'three.json'; a.write_json(slotfile,{'slots':selection['slots'][:3]})
        s=self.record(s,'slots',{'article_path':str(marked),'slots_path':str(slotfile)})
        prep=a.prepare_plan(s); s=self.record(s,'plan',prep['payload']); s=self.answer(s,'use')
        self.assertEqual(w.next_step(s)['key'],'image_review')
        self.assertTrue(all(Path(x['inspection']['path']).exists() for x in assets)); self.assertEqual(s['assets'],assets)
        s=self.answer(s,'use'); p=a.compose_and_verify(s,root); self.assertEqual(len(a.read_json(p['manifest_path'])['slots']),3)
    def test_cached_plan_flags_cannot_override_actual_plan(self):
        s=self.plan(); s['image_plan']['data']['generation_performed']=True
        self.assertEqual(w.next_step(s)['action'],'repair_artifacts')
    def test_package_cannot_substitute_unreviewed_file(self):
        s=self.ready(); root=a.run_root(s); payload=a.compose_and_verify(s,root)
        replacement=root/'substitute.png'; Image.new('RGB',(40,50),'green').save(replacement)
        manifest=a.read_json(payload['manifest_path']); manifest['slots'][0]['path']='substitute.png'
        m=root/'substitute-manifest.json'; a.write_json(m,manifest)
        text,_=a.compose_article_data(s['slot_selection']['path'],m,root=root,absolute_image_paths=True)
        c=root/'substitute.md'; c.write_text(text); r=root/'substitute-report.json'
        report=a.run_image_helper(s['image_plan']['request_path'],root,'generate-and-compose',r,m,c)
        self.assertEqual(report['status'],'package_verified')
        with self.assertRaises(BuildError): self.record(s,'package',{'manifest_path':str(m),'composed_article_path':str(c),'completion_path':str(r)})
    def test_source_size_limit_staging_and_output_exclusive(self):
        s=self.plan(); root=a.run_root(s); huge=root/'huge.png'
        with huge.open('wb') as f: f.truncate(20*1024*1024+1)
        with self.assertRaises(BuildError): a.bind_asset(s,'cover',huge,'user-file')
        outside=self.work/'input.txt'; outside.write_text('원본')
        staged=a.stage_input(outside,root,'inputs/source.v1.txt'); self.assertEqual(staged.read_bytes(),outside.read_bytes())
        with self.assertRaises(BuildError): a.stage_input(outside,root,'inputs/source.v1.txt')
    def test_fresh_reference_bytes_are_rechecked(self):
        s=self.plan(); root=a.run_root(s); reference=root/'ref.png'; Image.new('RGB',(40,50),'red').save(reference)
        w._set_option(s,'reference_use','yes'); w._set_option(s,'reference_path',str(reference)); w._set_option(s,'reference_instructions','default'); s['image_plan']=None
        prep=a.prepare_plan(s); s=self.record(s,'plan',prep['payload'])
        Image.new('RGB',(40,50),'green').save(reference)
        self.assertEqual(w.next_step(s)['action'],'repair_artifacts')


    def test_terminal_marker_preserves_manuscript_without_final_newline(self):
        root=self.work; original=root/'plain.md'; original.write_text('# 제목\n\n첫 요점입니다. 다음 요점입니다.')
        marked=root/'marked.md'; marked.write_text(original.read_text()+'\n<!-- naver-image:cover -->\n')
        slot={'id':'cover','role':'cover','purpose':'설명','prompt':'핵심 정보','mode':'infographic-diagram','alt':'핵심 정보'}
        record=a.validate_slot_article(original,marked,[slot],root); self.assertEqual(record['source_sha256'],a.file_sha(original))
    def test_registered_article_metrics_exclude_existing_markers(self):
        root=self.work; plain=root/'plain.md'; plain.write_text('# 제목\n\n식물의 상태를 살펴봅니다.\n')
        marked=root/'marked.md'; marked.write_text(plain.read_text().replace('# 제목\n','# 제목\n<!-- naver-image:cover -->\n'))
        self.assertEqual(a.register_article(plain,root)['metrics'],a.register_article(marked,root)['metrics'])


    def test_six_realistic_requests_with_canonical_state_replay(self):
        cases=json.loads((Path(__file__).parent/'fixtures/wizard/behavior-cases.json').read_text())['cases']
        self.assertEqual(len(cases),6)
        for case in cases:
            with self.subTest(request=case['request']):
                if 'initial' in case:
                    state=w.new_session(self.work,case['initial']); self.assertEqual(w.next_step(state)['key'],case['expected_question'])
                elif case['id']=='own-files':
                    state=self.ready(case['count']); state=self.record(state,'package',a.compose_and_verify(state,a.run_root(state)))
                    self.assertEqual(w.next_step(state)['kind'],case['expected_kind']); self.assertTrue(all(x['provenance']=='user-file' for x in state['assets']))
                elif case['id']=='resume-count':
                    state=self.ready(case['count']); paths=[x['inspection']['path'] for x in state['assets']]
                    state=w.apply_control(state,'pause',state['revision']); state=w.apply_control(state,'resume',state['revision'])
                    state=w.apply_change(state,'requested_count',case['new_count'],state['revision'])
                    self.assertEqual(w.next_step(state)['action'],case['expected_action']); self.assertTrue(all(Path(path).exists() for path in paths))
                else:
                    state=self.plan(case['count'],case['presentation'],case['image_action']); step=w.next_step(state)
                    self.assertEqual(step.get('kind'),case.get('expected_kind','action')); self.assertEqual(step.get('action'),case.get('expected_action'))
    def test_profile_snapshot_is_required_and_changes_are_detected(self):
        s=w.new_session(self.work,{'task_mode':'new','topic':'식물','audience':'general','article_type':'information','tone':'profile','length':'short','format_preset':'auto'})
        root=a.run_root(s); root.mkdir(parents=True); article=root/'article.md'; article.write_text('# 식물 관리\n\n흙이 마른 뒤 물을 줍니다.\n')
        with self.assertRaises(w.WizardError): self.record(s,'article',{'path':str(article)})
        profile=root/'profile.md'; profile.write_text('담백한 문체로 작성')
        s=self.record(s,'article',{'path':str(article),'profile_path':str(profile)})
        profile.write_text('문체 변경'); self.assertEqual(w.next_step(s)['action'],'repair_artifacts')


    def test_bad_brief_returns_to_slot_design_instead_of_plan_retry_loop(self):
        s=self.plan(3,'standard','prompt-only'); selection=copy.deepcopy(s['slot_selection'])
        s=w.apply_change(s,'presentation','mixed',s['revision']); slots=copy.deepcopy(selection['slots']); slots[2]['heading_hint']=slots[1]['heading_hint']
        root=a.run_root(s); bad=root/'duplicate-slots.json'; a.write_json(bad,{'slots':slots})
        s=self.record(s,'slots',{'article_path':selection['path'],'slots_path':str(bad)})
        result=a.prepare_plan(s); self.assertEqual(result['status'],'requires_design')
        s=self.record(s,'plan',result['payload']); self.assertEqual(w.next_step(s)['action'],'design_slots'); self.assertEqual(s['assets'],[])
        good=root/'corrected-slots.json'; a.write_json(good,{'slots':selection['slots']})
        s=self.record(s,'slots',{'article_path':selection['path'],'slots_path':str(good)})
        result=a.prepare_plan(s); self.assertEqual(result['status'],'planned')
        s=self.record(s,'plan',result['payload']); s=self.answer(s,'use'); self.assertEqual(w.next_step(s)['kind'],'complete')


    def test_corrupted_user_asset_can_be_repaired_without_resetting_other_slots(self):
        s=self.ready(2); other=copy.deepcopy(s['assets'][1]); bad=s['assets'][0]['inspection']['path']; Path(bad).write_text('corrupted')
        self.assertEqual(w.next_step(s)['action'],'repair_artifacts')
        s=self.record(s,'repair',{'target':'asset','slot_id':'cover'})
        self.assertEqual(w.next_step(s)['action'],'import_image'); self.assertEqual(s['assets'][0],other)
        s=self.qa(self.image(s,color='green')); self.assertEqual(w.next_step(s)['key'],'image_review')
        self.assertTrue(Path(bad).exists()); self.assertEqual(next(x for x in s['assets'] if x['slot_id']=='section-1'),other)
    def test_corrupted_plan_and_package_recovery_recomputes_real_outputs(self):
        s=self.ready(); request=s['image_plan']['request_path']; Path(request).write_text('{}')
        self.assertEqual(w.next_step(s)['action'],'repair_artifacts')
        s=self.record(s,'repair',{'target':'plan'}); self.assertEqual(w.next_step(s)['action'],'prepare_plan')
        prep=a.prepare_plan(s); s=self.record(s,'plan',prep['payload']); s=self.answer(s,'use'); s=self.answer(s,'use')
        payload=a.compose_and_verify(s,a.run_root(s)); s=self.record(s,'package',payload)
        Path(payload['composed_article_path']).write_text('changed')
        s=self.record(s,'repair',{'target':'package'}); self.assertEqual(w.next_step(s)['action'],'compose_article')
        payload=a.compose_and_verify(s,a.run_root(s)); s=self.record(s,'package',payload); self.assertEqual(w.next_step(s)['kind'],'complete')


    def test_processing_mode_switch_requires_requested_provenance(self):
        for oldmode,newmode,provenance,expected in [('generate','use-files','generated','import_image'),('use-files','generate','user-file','generate_image')]:
            with self.subTest(mode=newmode):
                s=self.plan(action=oldmode); s=self.qa(self.image(s,provenance)); selection=copy.deepcopy(s['slot_selection'])
                s=w.apply_change(s,'image_action',newmode,s['revision'])
                s=self.record(s,'slots',{'article_path':selection['path'],'slots_path':selection['slots_path']})
                prep=a.prepare_plan(s); s=self.record(s,'plan',prep['payload']); s=self.answer(s,'use')
                self.assertEqual(w.next_step(s)['action'],expected)
    def test_new_prompt_gets_one_correction_budget(self):
        s=self.qa(self.image(self.plan(action='generate'),'generated'),False)
        s=self.qa(self.image(s,'edited','green'),False); self.assertEqual(s['assets'][0]['corrections'],1)
        selection=copy.deepcopy(s['slot_selection']); s=w.apply_change(s,'additional_requirements','차분한 색으로 바꿔 주세요',s['revision'])
        s=self.record(s,'slots',{'article_path':selection['path'],'slots_path':selection['slots_path']})
        prep=a.prepare_plan(s); s=self.record(s,'plan',prep['payload']); s=self.answer(s,'use')
        s=self.qa(self.image(s,'generated','blue'),False)
        self.assertEqual(s['assets'][0]['corrections'],0); self.assertEqual(w.next_step(s)['action'],'repair_image')

if __name__=='__main__': unittest.main()
