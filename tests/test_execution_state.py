from __future__ import annotations
import json
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'skills/naver-smarteditor-drafter/scripts'))
from execution_state import ExecutionStore,ExecutionKey,StateError,CHECKS,Lease,PRESENTATION_CHECKS,RENDER_POLICY


class ExecutionStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name).resolve()
        self.store=ExecutionStore(self.root/'ledger',environment='simulation')
        self.key=ExecutionKey('demo-blog','Series-Test',3,'a'*64)
        self.lease=self.store.acquire('demo-blog','run-one')
    def tearDown(self):self.tmp.cleanup()
    def evidence(self,state):
        return {'environment':'simulation','content_revision':self.key.revision,'target_blog':self.key.target_blog,
                'evidence_ref':'mock://fixture-1','expected':{'title':'Test','render_policy':RENDER_POLICY},'observed':{'title':'Test'},
                'checks':{check:True for check in (CHECKS[state] | (PRESENTATION_CHECKS if state in ('input_verified','reopened_verified') else set()))}}
    def input_ready(self):
        self.store.start(self.key,self.lease)
        self.store.verify(self.key,self.lease,'editor_checked',self.evidence('editor_checked'))
        oid=self.store.begin_operation(self.key,self.lease,'insert_block',detail={'block_id':'b1'})
        self.store.finish_operation(self.key,self.lease,oid,outcome='observed',observed={'block_id':'b1'},evidence_ref='mock://b1')
    def save_pending(self):
        self.input_ready()
        self.store.verify(self.key,self.lease,'input_verified',self.evidence('input_verified'))
        return self.store.begin_operation(self.key,self.lease,'save')
    def complete(self):
        oid=self.save_pending()
        self.store.finish_operation(self.key,self.lease,oid,outcome='observed',observed={'save_acknowledged':True},evidence_ref='mock://save')
        self.store.verify(self.key,self.lease,'reopened_verified',self.evidence('reopened_verified'))
        self.store.verify(self.key,self.lease,'blank_verified',self.evidence('blank_verified'))
    def saved_ready(self):
        oid=self.save_pending()
        self.store.finish_operation(self.key,self.lease,oid,outcome='observed',observed={'save_acknowledged':True},evidence_ref='mock://save')
    def tag_proof(self):
        return {'read_only':True,'tags_observed':True,'tags':['테스트'],'settings_closed':True,
                'content_unchanged':True,'before_content_sha256':'b'*64,'after_content_sha256':'b'*64}
    def inspect_tags(self):
        return self.store.begin_operation(self.key,self.lease,'inspect_saved_tags',detail={'read_only':True,'draft_reference':'Test|timestamp'})
    def test_saved_tags_readonly_preserves_state_history_and_write_restrictions(self):
        self.saved_ready()
        before={p:p.read_bytes() for p in (self.root/'ledger').rglob('events/*.json')}
        for phase in ('before','pending','after'):
            if phase=='pending':oid=self.inspect_tags()
            if phase=='after':self.store.finish_operation(self.key,self.lease,oid,outcome='observed',observed=self.tag_proof(),evidence_ref='mock://tags')
            for op in ('open_tag_settings','input_tags','close_tag_settings','insert_block','insert_table','upload_image','apply_quote','save','publish','new_editor'):
                with self.subTest(phase=phase,op=op),self.assertRaises(StateError):self.store.begin_operation(self.key,self.lease,op)
        self.assertEqual(self.store.status(self.key)['state'],'save_acknowledged')
        self.assertEqual(before,{p:p.read_bytes() for p in before})
        with self.assertRaises(StateError):self.store.verify(self.key,self.lease,'blank_verified',self.evidence('blank_verified'))
        self.store.verify(self.key,self.lease,'reopened_verified',self.evidence('reopened_verified'))
    def test_saved_tags_requires_explicit_readonly_intent_and_complete_proof(self):
        self.saved_ready()
        for detail in ({},{'read_only':False,'draft_reference':'draft'},{'read_only':True}):
            with self.subTest(detail=detail),self.assertRaises(StateError):
                self.store.begin_operation(self.key,self.lease,'inspect_saved_tags',detail=detail)
        oid=self.inspect_tags()
        for change in ({'read_only':False},{'settings_closed':False},{'tags_observed':False},{'content_unchanged':False},
                       {'tags':None},{'tags':[1]},{'after_content_sha256':'c'*64},{'before_content_sha256':'x'*64,'after_content_sha256':'x'*64}):
            with self.subTest(change=change),self.assertRaises(StateError):
                self.store.finish_operation(self.key,self.lease,oid,outcome='observed',observed={**self.tag_proof(),**change},evidence_ref='mock://invalid')
        self.assertEqual(self.store.status(self.key)['pending_operations'],[oid])
    def test_saved_tags_pending_or_unknown_never_resumes_insertion(self):
        self.saved_ready();oid=self.inspect_tags()
        self.assertEqual(self.store.status(self.key)['resume_decision'],'reconcile_save')
        self.store.finish_operation(self.key,self.lease,oid,outcome='unknown',observed=None,evidence_ref=None)
        self.assertEqual(self.store.status(self.key)['state'],'save_unknown')
        self.assertEqual(self.store.status(self.key)['resume_decision'],'reconcile_save')
        ev={'environment':'simulation','content_revision':self.key.revision,'target_blog':'demo-blog','observed':{'title':'Test'},'evidence_ref':'mock://partial','checks':{'complete_observation':True,'partial_content_matches':True,'no_inflight_operation':True}}
        with self.assertRaises(StateError):self.store.reconcile_input(self.key,self.lease,ev)
        with self.assertRaises(StateError):self.store.begin_operation(self.key,self.lease,'input_tags')
    def test_saved_tags_is_not_allowed_during_insertion_or_after_completion(self):
        self.input_ready()
        with self.assertRaises(StateError):self.inspect_tags()
        self.store.verify(self.key,self.lease,'input_verified',self.evidence('input_verified'))
        oid=self.store.begin_operation(self.key,self.lease,'save')
        self.store.finish_operation(self.key,self.lease,oid,outcome='observed',observed={'save_acknowledged':True},evidence_ref='mock://save')
        self.store.verify(self.key,self.lease,'reopened_verified',self.evidence('reopened_verified'))
        with self.assertRaises(StateError):self.inspect_tags()
    def test_full_lifecycle_deduplicates_replay(self):
        self.complete();before=self.store.events(self.key)
        status=self.store.start(self.key,self.lease)
        self.assertEqual(status['resume_decision'],'skip');self.assertEqual(before,self.store.events(self.key))
        with self.assertRaises(StateError):self.store.begin_operation(self.key,self.lease,'insert_block')
        with self.assertRaises(StateError):self.store.begin_operation(self.key,self.lease,'publish')
    def test_native_table_intent_preserves_write_ahead_and_inserting_state(self):
        self.store.start(self.key,self.lease)
        self.store.verify(self.key,self.lease,'editor_checked',self.evidence('editor_checked'))
        oid=self.store.begin_operation(self.key,self.lease,'insert_table',detail={'block_id':'t1'})
        self.assertEqual(self.store.status(self.key)['state'],'inserting')
        self.assertEqual(self.store.status(self.key)['resume_decision'],'reconcile_input')
        self.store.finish_operation(self.key,self.lease,oid,outcome='observed',observed={'native_table':True},evidence_ref='mock://table')
        self.store.verify(self.key,self.lease,'input_verified',self.evidence('input_verified'))
    def test_new_content_evidence_cannot_drop_policy_or_presentation_checks(self):
        self.input_ready()
        for field in ('tables','links','line_breaks','paragraph_spacing'):
            bad=self.evidence('input_verified');del bad['checks'][field]
            with self.subTest(field=field),self.assertRaises(StateError):self.store.verify(self.key,self.lease,'input_verified',bad)
        old=self.evidence('input_verified');old['expected']['render_policy']='smarteditor-subset/v1'
        with self.assertRaises(StateError):self.store.verify(self.key,self.lease,'input_verified',old)
    def test_immutable_legacy_event_is_readable_but_not_new_verification(self):
        self.input_ready();old=self.evidence('input_verified')
        old['expected']['render_policy']='smarteditor-subset/v1';old['checks']={c:True for c in CHECKS['input_verified']}
        # Historical fixture authored as an old envelope; public verify refuses it.
        self.store._append(self.key,self.lease,'verification','input_verified',{'verification':old})
        before={p:p.read_bytes() for p in (self.root/'ledger').rglob('events/*.json')}
        fresh=ExecutionStore(self.root/'ledger',environment='simulation')
        self.assertEqual(fresh.status(self.key)['state'],'input_verified')
        self.assertEqual(before,{p:p.read_bytes() for p in before})
    def test_save_after_click_before_local_ack_requires_reconciliation(self):
        self.save_pending()
        resumed=ExecutionStore(self.root/'ledger',environment='simulation')
        self.assertEqual(resumed.status(self.key)['resume_decision'],'reconcile_save')
        with self.assertRaises(StateError):resumed.begin_operation(self.key,self.lease,'save')
        resumed.reconcile_saved(self.key,self.lease,self.evidence('reopened_verified'))
        self.assertEqual(resumed.status(self.key)['resume_decision'],'verify_blank_only')
        self.assertEqual(resumed.status(self.key)['pending_operations'],[])
        self.assertEqual(sum(e['event_type']=='operation_intent' and e['payload']['operation']=='save' for e in resumed.events(self.key)),1)
    def test_late_recovery_prompt_can_recheck_navigation_not_reinsert(self):
        self.complete()
        oid=self.store.begin_operation(self.key,self.lease,'new_editor',detail={'reason':'late recovery prompt'})
        with self.assertRaises(StateError):
            self.store.verify(self.key,self.lease,'blank_verified',self.evidence('blank_verified'))
        self.store.finish_operation(self.key,self.lease,oid,outcome='observed',observed={'blank':True},evidence_ref='mock://fresh-blank')
        bad=self.evidence('blank_verified');bad['checks']['blank_editor']=False
        with self.assertRaises(StateError):
            self.store.verify(self.key,self.lease,'blank_verified',bad)
        self.store.verify(self.key,self.lease,'blank_verified',self.evidence('blank_verified'))
        with self.assertRaises(StateError):self.store.begin_operation(self.key,self.lease,'insert_block')
        with self.assertRaises(StateError):self.store.begin_operation(self.key,self.lease,'save')
        with self.assertRaises(StateError):self.store.begin_operation(self.key,self.lease,'publish')
        self.assertEqual(self.store.status(self.key)['resume_decision'],'skip')
    def test_unknown_save_is_not_complete(self):
        oid=self.save_pending()
        self.store.finish_operation(self.key,self.lease,oid,outcome='unknown',observed=None,evidence_ref=None)
        status=self.store.status(self.key);self.assertEqual(status['state'],'save_unknown')
        with self.assertRaises(StateError):self.store.verify(self.key,self.lease,'blank_verified',self.evidence('blank_verified'))
        self.assertIsNone(self.store.events(self.key)[-1]['payload']['observed'])
    def test_partial_upload_requires_matching_ui_and_no_inflight(self):
        self.input_ready()
        for index in range(3):
            op=self.store.begin_operation(self.key,self.lease,'upload_image',detail={'block_id':f'i{index}'})
            if index<2:self.store.finish_operation(self.key,self.lease,op,outcome='observed',observed={'image':index},evidence_ref=f'mock://image{index}')
        self.assertEqual(self.store.status(self.key)['resume_decision'],'reconcile_input')
        with self.assertRaises(StateError):self.store.begin_operation(self.key,self.lease,'upload_image')
        ev={'environment':'simulation','content_revision':'a'*64,'target_blog':'demo-blog','observed':{'images':['i0','i1','i2']},'evidence_ref':'mock://actual-ui','checks':{'complete_observation':True,'partial_content_matches':True,'no_inflight_operation':True}}
        self.store.reconcile_input(self.key,self.lease,ev)
        self.assertEqual(self.store.status(self.key)['pending_operations'],[])
    def test_write_ahead_failure_prevents_side_effect(self):
        self.input_ready();actions=[]
        with patch.object(self.store,'_new_json',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                self.store.begin_operation(self.key,self.lease,'upload_image')
                actions.append('would upload')
        self.assertEqual(actions,[])
    def test_duplicate_operation_id_cannot_reexecute(self):
        self.input_ready();oid=self.store.begin_operation(self.key,self.lease,'apply_quote',operation_id='same-op')
        self.store.finish_operation(self.key,self.lease,oid,outcome='observed',observed={'quote':'bubble'},evidence_ref='mock://quote')
        with self.assertRaises(StateError):self.store.begin_operation(self.key,self.lease,'apply_quote',operation_id='same-op')
        with self.assertRaises(StateError):self.store.finish_operation(self.key,self.lease,oid,outcome='observed',observed={'quote':'bubble'},evidence_ref='mock://quote')
    def test_another_revision_conflicts(self):
        self.complete();new=ExecutionKey('demo-blog','Series-Test',3,'b'*64)
        self.assertEqual(self.store.status(new)['resume_decision'],'revision_conflict')
        with self.assertRaises(StateError):self.store.start(new,self.lease)
    def test_second_writer_fails_and_wrong_lease_cannot_release(self):
        with self.assertRaises(StateError):self.store.acquire('demo-blog','another-run')
        with self.assertRaises(StateError):self.store.release(Lease('demo-blog','wrong','run-one'))
        self.store.release(self.lease)
        self.assertIsInstance(self.store.acquire('demo-blog','another-run'),Lease)
    def test_stale_lock_is_not_released_by_age(self):
        with patch('execution_state.process_identity',return_value={'status':'alive','start':None}),self.assertRaises(StateError):
            self.store.recover_lock('demo-blog',expected_token=self.lease.token,reconciliation={})
        with patch('execution_state.process_identity',return_value={'status':'dead','start':None}),self.assertRaises(StateError):
            self.store.recover_lock('demo-blog',expected_token=self.lease.token,reconciliation={})
        with patch('execution_state.process_identity',return_value={'status':'dead','start':None}):
            self.store.recover_lock('demo-blog',expected_token=self.lease.token,reconciliation={'observed_complete':True,'pending_operations_reviewed':True,'evidence_ref':'mock://reconciliation'})
        self.assertEqual(len(list((self.root/'ledger').rglob('lock-history/*.json'))),1)
        self.assertIsInstance(self.store.acquire('demo-blog','new'),Lease)
    def test_tampered_or_missing_event_fails_closed(self):
        self.input_ready();files=sorted((self.root/'ledger').rglob('events/*.json'))
        last=files[-1];original=last.read_bytes();event=json.loads(original);event['state']='blank_verified';last.write_text(json.dumps(event))
        with self.assertRaises(StateError):self.store.status(self.key)
        last.write_bytes(original);files[1].unlink()
        with self.assertRaises(StateError):self.store.status(self.key)
    def test_mock_history_cannot_be_used_as_live(self):
        self.complete();live=ExecutionStore(self.root/'ledger',environment='live')
        with self.assertRaises(StateError):live.status(self.key)
    def test_observations_required_not_expected_only(self):
        self.store.start(self.key,self.lease)
        for change in [{'observed':None},{'observed':{}},{'environment':'live'},{'content_revision':'b'*64},{'checks':{}}]:
            ev={**self.evidence('editor_checked'),**change}
            with self.subTest(change=change),self.assertRaises(StateError):self.store.verify(self.key,self.lease,'editor_checked',ev)
    def test_ack_is_not_reopen_and_blank_requires_reopen(self):
        oid=self.save_pending()
        with self.assertRaises(StateError):self.store.finish_operation(self.key,self.lease,oid,outcome='observed',observed={'toast':False},evidence_ref='mock://not-saved')
        self.store.finish_operation(self.key,self.lease,oid,outcome='observed',observed={'save_acknowledged':True},evidence_ref='mock://ack')
        self.assertEqual(self.store.status(self.key)['state'],'save_acknowledged')
        with self.assertRaises(StateError):self.store.verify(self.key,self.lease,'blank_verified',self.evidence('blank_verified'))
    def test_legacy_import_readonly_not_upgraded(self):
        p=self.root/'legacy.json';p.write_text('{"episode":3,"status":"saved_verified"}')
        before=hashlib.sha256(p.read_bytes()).hexdigest()
        status=self.store.import_legacy(self.key,self.lease,p)
        self.assertEqual(status['state'],'legacy_saved_reported');self.assertEqual(status['resume_decision'],'reconcile_save')
        self.assertEqual(before,hashlib.sha256(p.read_bytes()).hexdigest())
        self.assertIsNone(self.store.events(self.key)[0]['payload']['observed_reopened'])
    def test_summary_is_rebuildable_not_authoritative(self):
        self.complete();path=self.store.write_summary(self.key,self.lease)
        path.write_text('{"state":"made-up"}')
        self.assertEqual(self.store.status(self.key)['state'],'blank_verified')
        self.store.write_summary(self.key,self.lease)
        self.assertEqual(json.loads(path.read_text())['state'],'blank_verified')
    def test_status_readonly_and_symlink_guard(self):
        clean=ExecutionStore(self.root/'missing',environment='simulation')
        self.assertEqual(clean.status(self.key)['state'],'not_started');self.assertFalse((self.root/'missing').exists())
        self.store.start(self.key,self.lease);events=next((self.root/'ledger').rglob('events'))
        (events/'evil.json').symlink_to(self.root/'missing-file')
        with self.assertRaises(StateError):self.store.status(self.key)

    def test_reprepare_cannot_change_execution_events_or_summary(self):
        import argparse
        from build_naver_post import run
        self.complete();summary=self.store.write_summary(self.key,self.lease)
        before={str(p):p.read_bytes() for p in (self.root/'ledger').rglob('*') if p.is_file()}
        source=self.root/'episode-03.md';source.write_text('# 제목\n\n본문')
        args=argparse.Namespace(input=str(source),input_root=None,project_root=str(self.root),output_root=str(self.root/'prepared'),run_id='run',batch=False,check=False,force=False,episode_min=None,episode_max=None,expected_images=0,expected_tags=0)
        run(args);args.force=True;run(args)
        self.assertEqual(before,{str(p):p.read_bytes() for p in (self.root/'ledger').rglob('*') if p.is_file()})
        self.assertEqual(json.loads(summary.read_text())['state'],'blank_verified')
    def test_forged_rehashed_verification_with_no_observation_rejected(self):
        self.store.start(self.key,self.lease)
        self.store.verify(self.key,self.lease,'editor_checked',self.evidence('editor_checked'))
        path=sorted((self.root/'ledger').rglob('events/*.json'))[-1]
        event=json.loads(path.read_text());event['payload']['verification']['observed']=None
        from execution_state import _hash
        event['event_hash']=_hash({k:v for k,v in event.items() if k!='event_hash'})
        path.write_text(json.dumps(event))
        with self.assertRaises(StateError):self.store.status(self.key)
    def test_sequence_commit_is_exclusive(self):
        self.store.start(self.key,self.lease)
        from execution_state import _hash
        path=next((self.root/'ledger').rglob('events/*.json'));original=path.read_bytes()
        # Simulate two writers having read the same empty ledger before publishing.
        with patch.object(self.store,'events',return_value=[]),self.assertRaises(StateError) as ctx:
            self.store._append(self.key,self.lease,'started','ready',{})
        self.assertEqual(ctx.exception.code,'EVENT_CONFLICT');self.assertEqual(path.read_bytes(),original)
    def test_save_intent_disk_failure_never_allows_click(self):
        self.input_ready();self.store.verify(self.key,self.lease,'input_verified',self.evidence('input_verified'))
        actions=[]
        with patch.object(self.store,'_new_json',side_effect=OSError('disk failure')),self.assertRaises(OSError):
            self.store.begin_operation(self.key,self.lease,'save')
            actions.append('save click')
        self.assertEqual(actions,[]);self.assertEqual(self.store.status(self.key)['state'],'input_verified')

    def test_not_saved_retry_needs_explicit_approval_and_ui_reconciliation(self):
        oid=self.save_pending()
        self.store.finish_operation(self.key,self.lease,oid,outcome='unknown',observed=None,evidence_ref=None)
        ev=self.evidence('input_verified')
        ev['checks'].update(no_saved_match=True,no_inflight_operation=True,current_input_matches=True)
        with self.assertRaises(StateError):self.store.reconcile_not_saved(self.key,self.lease,ev)
        ev['user_confirmed_retry']=True
        self.store.reconcile_not_saved(self.key,self.lease,ev)
        self.assertEqual(self.store.status(self.key)['state'],'input_verified')
        second=self.store.begin_operation(self.key,self.lease,'save')
        self.assertNotEqual(second,oid)

if __name__=='__main__':unittest.main()
