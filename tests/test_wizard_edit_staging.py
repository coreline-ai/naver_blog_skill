from pathlib import Path
import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

SCRIPT = Path(__file__).resolve().parents[1] / 'skills/naver-blog-wizard/scripts'
sys.path.insert(0, str(SCRIPT))
import wizard_session as w
import wizard_artifacts as a
from post_contract import BuildError


class WizardEditStagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.work = Path(self.temp.name).resolve()
        self.original = self.work / 'external-original.png'
        Image.new('RGBA', (40, 50), (23, 80, 112, 90)).save(self.original)

    def tearDown(self):
        self.temp.cleanup()

    def session(self, target=None):
        s = w.new_session(self.work, {'task_mode': 'edit-existing',
            'edit_target': str(target or self.original), 'edit_instruction': '배경만 밝게 변경'})
        a.run_root(s).mkdir(parents=True)
        return s

    def intent(self, s):
        return w.record_event(s, {'type': 'effect-intent',
            'payload': {'slot_id': 'edit-target'}}, s['revision'])

    def copies(self, s):
        return list((a.run_root(s) / 'inputs').glob('edit-original.*'))

    def test_external_original_is_staged_and_normalized_in_one_transition(self):
        s = self.session()
        before = self.original.read_bytes()
        original_state = copy.deepcopy(s)
        n = self.intent(s)
        target = Path(w.value(n, 'edit_target'))
        self.assertTrue(target.is_relative_to(a.run_root(s)))
        self.assertEqual(target.read_bytes(), before)
        self.assertEqual(self.original.read_bytes(), before)
        self.assertEqual(s, original_state)
        self.assertEqual(n['revision'], s['revision'] + 1)
        self.assertEqual(n['confirmed_options']['edit_target']['user_text'], str(self.original))
        self.assertEqual(n['confirmed_options']['edit_target']['origin'], 'initial-request')
        self.assertEqual(n['effect']['target']['path'], str(target))
        self.assertEqual(n['effect']['binding']['reference_sha256'], hashlib.sha256(before).hexdigest())
        with Image.open(target) as im:
            self.assertEqual(im.mode, 'RGBA')
            self.assertEqual(im.getpixel((0, 0))[3], 90)
        self.assertEqual(w.next_step(n)['action'], 'reconcile')

    def test_internal_original_is_not_copied_or_rewritten(self):
        s = self.session()
        original = a.run_root(s) / 'local.png'
        original.write_bytes(self.original.read_bytes())
        s = w.apply_change(s, 'edit_target', str(original), s['revision'])
        n = self.intent(s)
        self.assertEqual(w.value(n, 'edit_target'), str(original))
        self.assertEqual(self.copies(n), [])
        self.assertEqual(original.read_bytes(), self.original.read_bytes())

    def test_readonly_cli_does_not_stage_and_write_cli_does(self):
        s = self.session()
        path = a.run_root(s) / 'session.json'
        w._atomic_save(path, s)
        before = path.read_bytes()
        for command in ('next', 'status'):
            proc = subprocess.run([sys.executable, '-B', str(SCRIPT / 'wizard_session.py'),
                command, '--session', str(path)], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.copies(s), [])
        payload = self.work / 'intent.json'
        payload.write_text(json.dumps({'slot_id': 'edit-target'}))
        proc = subprocess.run([sys.executable, '-B', str(SCRIPT / 'wizard_session.py'),
            'record', '--session', str(path), '--type', 'effect-intent', '--payload', str(payload),
            '--expected-revision', '0'], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        state = json.loads(proc.stdout)['state']
        self.assertTrue(Path(w.value(state, 'edit_target')).is_relative_to(a.run_root(s)))
        self.assertEqual(len(self.copies(state)), 1)

    def test_bad_external_files_and_symlinks_are_rejected_before_copy(self):
        fake = self.work / 'fake.png'; fake.write_text('not an image')
        unsupported = self.work / 'original.webp'
        Image.new('RGB', (40, 50)).save(unsupported)
        huge = self.work / 'huge.png'
        with huge.open('wb') as stream: stream.truncate(20 * 1024 * 1024 + 1)
        alias = self.work / 'alias.png'; alias.symlink_to(self.original)
        folder_alias = self.work / 'linked-folder'; folder_alias.symlink_to(self.work, target_is_directory=True)
        targets = [fake, unsupported, huge, alias, folder_alias / self.original.name,
            self.work / 'missing.png', self.work, str(self.work / 'child' / '..' / self.original.name)]
        for target in targets:
            with self.subTest(target=str(target)):
                s = self.session(target); before = copy.deepcopy(s)
                with self.assertRaises(BuildError): self.intent(s)
                self.assertEqual(s, before)
                self.assertEqual(self.copies(s), [])

    def test_relative_path_is_never_imported_from_cwd(self):
        s = self.session(self.original.name)
        old = Path.cwd()
        try:
            os.chdir(self.work)
            with self.assertRaises(BuildError): self.intent(s)
        finally:
            os.chdir(old)
        self.assertEqual(self.copies(s), [])

    def test_changed_original_during_copy_stops_and_preserves_snapshots(self):
        s = self.session(); stage = a.stage_input
        def changed(*args, **kwargs):
            result = stage(*args, **kwargs)
            Image.new('RGBA', (40, 50), (100, 20, 70, 80)).save(self.original)
            return result
        with patch.object(a, 'stage_input', side_effect=changed):
            with self.assertRaises(BuildError) as caught: self.intent(s)
        self.assertEqual(caught.exception.code, 'ASSET_CHANGED')
        self.assertIsNone(s['effect'])
        old_copy = self.copies(s)[0]; before = old_copy.read_bytes()
        n = self.intent(s)
        self.assertEqual(len(self.copies(n)), 2)
        self.assertEqual(old_copy.read_bytes(), before)

    def test_changed_or_symlinked_cached_copy_is_never_overwritten(self):
        for symlink in (False, True):
            with self.subTest(symlink=symlink):
                s = self.session(); staged = Path(a.stage_edit_target(s)['path'])
                if symlink:
                    staged.unlink(); staged.symlink_to(self.original)
                else:
                    Image.new('RGBA', (40, 50), (100, 20, 70, 80)).save(staged)
                before = self.original.read_bytes(); cache_before = staged.read_bytes()
                with self.assertRaises(BuildError): self.intent(s)
                self.assertEqual(staged.read_bytes(), cache_before)
                self.assertEqual(self.original.read_bytes(), before)

    def test_atomic_save_failure_reuses_copy_and_stale_or_pending_intent_does_not_recopy(self):
        s = self.session(); path = a.run_root(s) / 'session.json'; w._atomic_save(path, s)
        before = path.read_bytes()
        with patch.object(w, '_atomic_save', side_effect=OSError('simulated save failure')):
            with self.assertRaises(OSError): w.update_session(path, 0, self.intent)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(len(self.copies(s)), 1)
        n = w.update_session(path, 0, self.intent)
        self.assertEqual(len(self.copies(n)), 1)
        self.assertEqual(w.next_step(n)['action'], 'reconcile')
        with self.assertRaises(w.WizardError): w.update_session(path, 0, self.intent)
        with self.assertRaises(w.WizardError): w.update_session(path, n['revision'], self.intent)
        self.assertEqual(w.load_session(path), n)
        self.assertEqual(len(self.copies(n)), 1)

    def test_original_change_or_removal_after_intent_does_not_change_frozen_target(self):
        s = self.intent(self.session()); frozen = Path(s['effect']['target']['path']).read_bytes()
        self.original.unlink()
        self.assertTrue(a.inspect_bindings(s)['ok'])
        self.assertEqual(w.next_step(s)['action'], 'reconcile')
        self.assertEqual(Path(s['effect']['target']['path']).read_bytes(), frozen)

    def test_changed_staged_target_while_binding_intent_is_rejected(self):
        s = self.session(); prepare = a.prepare_effect
        def changed(state, *args, **kwargs):
            Image.new('RGBA', (40, 50), (90, 20, 80, 70)).save(w.value(state, 'edit_target'))
            return prepare(state, *args, **kwargs)
        with patch.object(a, 'prepare_effect', side_effect=changed):
            with self.assertRaises(w.WizardError) as caught: self.intent(s)
        self.assertEqual(caught.exception.code, 'ASSET_CHANGED')
        self.assertIsNone(s['effect'])

    def test_external_edit_result_qa_and_use_complete_without_a_fake_article(self):
        s = self.intent(self.session()); original = self.original.read_bytes()
        result = a.run_root(s) / 'edited.png'
        Image.new('RGBA', (40, 50), (90, 150, 160, 90)).save(result)
        s = w.record_event(s, {'type': 'effect-result', 'payload': {'slot_id': 'edit-target',
            'path': str(result), 'provenance': 'edited', 'effect_id': s['effect']['id'],
            'tool_result': 'synthetic test fixture; no actual image model invocation'}}, s['revision'])
        self.assertEqual(w.next_step(s)['action'], 'visual_review')
        s = w.record_event(s, {'type': 'visual-review', 'payload': {'slot_id': 'edit-target',
            'asset_sha256': s['assets'][0]['inspection']['sha256'], 'passed': True,
            'notes': 'Simulation metadata only; not live visual QA.'}}, s['revision'])
        s = w.apply_answer(s, w.next_step(s)['question_id'], 'use', s['revision'])
        self.assertEqual(w.next_step(s)['kind'], 'complete')
        self.assertIsNone(s['article']); self.assertIsNone(s['image_plan'])
        self.assertEqual(self.original.read_bytes(), original)


if __name__ == '__main__': unittest.main()
