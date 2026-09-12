"""Check the actual Node evidence envelope against the Python event ledger."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
SCRIPTS=ROOT/'skills/naver-smarteditor-drafter/scripts'
sys.path.insert(0,str(SCRIPTS))
from execution_state import ExecutionStore,ExecutionKey,StateError

class UiEvidenceContractTests(unittest.TestCase):
    def evidence(self,environment='simulation'):
        return json.loads(subprocess.run(['node',str(SCRIPTS/'smarteditor_checks.mjs')],input=json.dumps({
            'command':'verify_blank','identity':{'environment':'simulation','target_blog':'demo-blog','content_revision':'a'*64},
            'options':{'scope':'editor_checked'},
            'observation':{'schema':'smarteditor-observation/v1','environment':environment,'target_blog':'demo-blog','evidence_ref':'mock://blank',
                           'observed_at':'2026-09-12T17:00:00+09:00','coverage':'complete','body_root_observed':True,
                           'title_fields':[{'component_id':'title','text':''}], 'components':[{'component_id':'body','kind':'paragraph','text':'','marks':[]}],
                           'unsupported_components':[],'recovery_pending':False,'inflight_operations':[]}}),text=True,capture_output=True,check=True).stdout)
    def test_passed_node_evidence_records_observed_blank(self):
        with tempfile.TemporaryDirectory() as folder:
            store=ExecutionStore(Path(folder),environment='simulation');key=ExecutionKey('demo-blog','Series-Test',3,'a'*64);lease=store.acquire('demo-blog','test')
            store.start(key,lease);evidence=self.evidence()
            store.verify(key,lease,'editor_checked',evidence)
            self.assertEqual(store.status(key)['state'],'editor_checked')
            self.assertEqual(store.events(key)[-1]['payload']['verification']['observed']['components'][0]['component_id'],'body')
    def test_failed_node_checks_cannot_be_recorded_as_success(self):
        with tempfile.TemporaryDirectory() as folder:
            store=ExecutionStore(Path(folder),environment='simulation');key=ExecutionKey('demo-blog','Series-Test',3,'a'*64);lease=store.acquire('demo-blog','test')
            store.start(key,lease);evidence=self.evidence('live')
            self.assertEqual(evidence['status'],'failed')
            evidence['status']='passed' # even a forged overall status cannot hide a failing individual check
            with self.assertRaises(StateError):store.verify(key,lease,'editor_checked',evidence)
            self.assertEqual(store.status(key)['state'],'ready')

    def test_wrong_verification_scope_is_not_interchangeable(self):
        with tempfile.TemporaryDirectory() as folder:
            store=ExecutionStore(Path(folder),environment='simulation');key=ExecutionKey('demo-blog','Series-Test',3,'a'*64);lease=store.acquire('demo-blog','test')
            store.start(key,lease);evidence=self.evidence();evidence['scope']='blank_verified'
            with self.assertRaises(StateError):store.verify(key,lease,'editor_checked',evidence)
            self.assertEqual(store.status(key)['state'],'ready')
    def test_partial_input_reconciliation_cannot_ignore_extra_failed_check(self):
        with tempfile.TemporaryDirectory() as folder:
            store=ExecutionStore(Path(folder),environment='simulation');key=ExecutionKey('demo-blog','Series-Test',3,'a'*64);lease=store.acquire('demo-blog','test')
            store.start(key,lease);store.verify(key,lease,'editor_checked',self.evidence())
            operation=store.begin_operation(key,lease,'upload_image')
            store.finish_operation(key,lease,operation,outcome='unknown',observed=None,evidence_ref=None)
            evidence={'environment':'simulation','content_revision':key.revision,'target_blog':key.target_blog,'observed':{'partial':'body'},'evidence_ref':'simulation-partial','checks':{'complete_observation':True,'partial_content_matches':True,'no_inflight_operation':True,'extra_check':False}}
            with self.assertRaises(StateError):store.reconcile_input(key,lease,evidence)
            self.assertEqual(store.status(key)['state'],'needs_reconciliation')

if __name__=='__main__':unittest.main()
