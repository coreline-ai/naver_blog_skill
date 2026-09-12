"""Durable, fail-closed draft event ledger. No browser access or publication API."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
import re
from pathlib import Path
import socket
import subprocess
from typing import Any
import uuid

from post_contract import BuildError, require_int, require_text, safe_segment


class StateError(BuildError):
    pass


def _encoded(value: Any) -> bytes:
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash(value: Any) -> str:
    return hashlib.sha256(_encoded(value)).hexdigest()


def process_identity(pid: int) -> dict[str, Any]:
    """OS liveness, never inferred merely from lock age."""
    try:
        os.kill(pid,0)
    except ProcessLookupError:
        return {'status':'dead','start':None}
    except (PermissionError,OSError):
        return {'status':'unknown','start':None}
    try:
        result=subprocess.run(['ps','-p',str(pid),'-o','lstart='],capture_output=True,text=True,
                              env={**os.environ,'LC_ALL':'C'},timeout=5)
        start=result.stdout.strip()
        if result.returncode==0 and start:
            return {'status':'alive','start':start}
    except (OSError,subprocess.TimeoutExpired):
        pass
    return {'status':'unknown','start':None}


@dataclass(frozen=True)
class ExecutionKey:
    target_blog: str
    series_id: str
    episode: int
    revision: str

    def __post_init__(self):
        safe_segment(self.target_blog,'target blog')
        safe_segment(self.series_id,'series id')
        require_int(self.episode,'episode',minimum=1)
        if not isinstance(self.revision,str) or len(self.revision)!=64 or any(c not in '0123456789abcdef' for c in self.revision):
            raise StateError('revision must be a lowercase SHA-256','INVALID_REVISION')

    def as_dict(self):
        return {'target_blog':self.target_blog,'series_id':self.series_id,'episode':self.episode,'revision':self.revision}


@dataclass(frozen=True)
class Lease:
    target_blog: str
    token: str
    run_id: str


CHECKS = {
    'editor_checked': {'target_blog','blank_editor','complete_observation'},
    'input_verified': {'title','body_order','image_order','image_anchors','tags','formatting','complete_observation'},
    'reopened_verified': {'draft_identity','title','body_order','image_order','image_anchors','tags','formatting','complete_observation','no_inflight_operation'},
    'blank_verified': {'blank_editor','complete_observation'},
}
VERIFY_FROM = {'editor_checked':{'ready'},'input_verified':{'inserting'},
               'reopened_verified':{'save_acknowledged'},'blank_verified':{'reopened_verified'}}
OPERATIONS = {
    'insert_block': {'editor_checked','inserting'}, 'upload_image': {'editor_checked','inserting'},
    'apply_quote': {'inserting'}, 'open_tag_settings': {'inserting'}, 'input_tags': {'inserting'}, 'close_tag_settings': {'inserting'},
    'save': {'input_verified'}, 'open_saved': {'save_acknowledged'}, 'new_editor': {'reopened_verified'},
}
STATES = {'ready','editor_checked','inserting','input_verified','save_requested','save_acknowledged',
          'reopened_verified','blank_verified','needs_reconciliation','save_unknown','legacy_saved_reported'}


class ExecutionStore:
    def __init__(self, root: Path, *, environment: str = 'live'):
        raw=Path(root).expanduser()
        if raw.is_symlink() or '..' in raw.parts:
            raise StateError('unsafe execution root','UNSAFE_PATH')
        self.root=raw.resolve()
        if environment not in ('live','simulation'):
            raise StateError('environment must be live or simulation')
        self.environment=environment

    def _guard(self, path: Path) -> Path:
        if not path.is_relative_to(self.root):
            raise StateError('path escapes execution root','UNSAFE_PATH')
        for current in (path,*path.parents):
            if current.is_symlink():
                raise StateError('execution paths must not contain symlinks','UNSAFE_PATH')
            if current==self.root: break
        if not path.resolve().is_relative_to(self.root):
            raise StateError('resolved path escapes execution root','UNSAFE_PATH')
        return path

    def _blog(self, blog: str) -> Path:
        safe_segment(blog,'target blog')
        return self._guard(self.root/hashlib.sha256(blog.encode()).hexdigest()[:24])

    def _directory(self,key: ExecutionKey) -> Path:
        return self._guard(self._blog(key.target_blog)/key.series_id/f'episode-{key.episode:02d}'/key.revision)

    def _read_json(self,path: Path) -> dict[str, Any]:
        self._guard(path)
        try:
            data=json.loads(path.read_text())
        except (OSError,ValueError) as exc:
            raise StateError(f'unreadable state: {path.name}','CORRUPT_STATE') from exc
        if not isinstance(data,dict): raise StateError('state must be an object','CORRUPT_STATE')
        return data

    def _new_json(self,path: Path,value: Any) -> None:
        self._guard(path)
        path.parent.mkdir(parents=True,exist_ok=True)
        self._guard(path)
        temp=path.parent/('.pending-'+uuid.uuid4().hex)
        try:
            fd=os.open(temp,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'wb') as stream:
                stream.write(_encoded(value));stream.flush();os.fsync(stream.fileno())
            # Hard link publishes a fully flushed file exclusively; never overwrite an event.
            os.link(temp,path)
            descriptor=os.open(path.parent,os.O_RDONLY)
            try:os.fsync(descriptor)
            finally:os.close(descriptor)
        finally:
            temp.unlink(missing_ok=True)

    def acquire(self,blog: str,run_id: str) -> Lease:
        safe_segment(run_id,'run id')
        lease=Lease(blog,uuid.uuid4().hex,run_id)
        lock=self._blog(blog)/'writer.lock'
        owner={'schema':'naver-writer-lock/v1','target_blog':blog,'token':lease.token,'run_id':run_id,
               'host':socket.gethostname(),'pid':os.getpid(),'process':process_identity(os.getpid()),'created_at':_now()}
        try:self._new_json(lock,owner)
        except FileExistsError as exc:
            raise StateError('blog writer already locked; do not clear by age','WRITER_LOCKED') from exc
        return lease

    def _require_lease(self,lease: Lease,blog: str) -> dict[str, Any]:
        lock=self._read_json(self._blog(blog)/'writer.lock')
        if lease.target_blog!=blog or lock.get('target_blog')!=blog or lock.get('token')!=lease.token or lock.get('run_id')!=lease.run_id:
            raise StateError('writer lease does not match','INVALID_LEASE')
        return lock

    def release(self,lease: Lease) -> None:
        self._require_lease(lease,lease.target_blog)
        (self._blog(lease.target_blog)/'writer.lock').unlink()

    def recover_lock(self,blog: str,*,expected_token: str,reconciliation: dict[str, Any]) -> None:
        """Explicit conservative recovery; no timeout/TTL takeover."""
        path=self._blog(blog)/'writer.lock';owner=self._read_json(path)
        if owner.get('token')!=expected_token or owner.get('host')!=socket.gethostname():
            raise StateError('cannot establish stale local owner','LOCK_RECOVERY_DENIED')
        pid=owner.get('pid');require_int(pid,'owner pid',minimum=1)
        current=process_identity(pid)
        old=owner.get('process',{})
        known_gone=current['status']=='dead' or (current['status']=='alive' and old.get('start') and current['start']!=old['start'])
        if not known_gone:
            raise StateError('owner is alive or liveness is unknown','LOCK_RECOVERY_DENIED')
        if not isinstance(reconciliation,dict) or reconciliation.get('observed_complete') is not True or reconciliation.get('pending_operations_reviewed') is not True or not reconciliation.get('evidence_ref'):
            raise StateError('UI/pending operation reconciliation evidence required','LOCK_RECOVERY_DENIED')
        # Retain the old lock and recovery evidence rather than deleting history.
        archived={**owner,'recovery':reconciliation,'recovered_at':_now()}
        self._new_json(path.parent/'lock-history'/f'{uuid.uuid4().hex}.json',archived)
        if self._read_json(path).get('token')!=expected_token:
            raise StateError('owner changed during recovery','LOCK_RECOVERY_DENIED')
        path.unlink()

    def events(self,key: ExecutionKey) -> list[dict[str, Any]]:
        directory=self._directory(key)/'events'
        if not directory.exists():return []
        self._guard(directory)
        entries=sorted(directory.iterdir());events=[];previous=None
        if any(p.is_symlink() or not p.is_file() or not p.name.endswith('.json') for p in entries):
            raise StateError('unexpected or partial event file','CORRUPT_STATE')
        event_ids=set();sequence=1
        for path in entries:
            event=self._read_json(path)
            expected={'schema','sequence','event_id','operation_id','event_type','state','timestamp','previous_hash','payload','event_hash','key','environment'}
            if set(event)!=expected or event.get('schema')!='naver-draft-event/v1' or event.get('sequence')!=sequence or type(event.get('sequence')) is not int:
                raise StateError('event shape or sequence mismatch','CORRUPT_STATE')
            if not isinstance(event['event_id'],str) or not re.fullmatch(r'[a-f0-9]{32}',event['event_id']) or not isinstance(event['state'],str) or (event['operation_id'] is not None and not isinstance(event['operation_id'],str)):
                raise StateError('invalid event identifiers','CORRUPT_STATE')
            try:
                if not isinstance(event['timestamp'],str) or datetime.fromisoformat(event['timestamp']).tzinfo is None:
                    raise ValueError('timestamp must be timezone-aware')
            except (TypeError,ValueError) as exc:
                raise StateError('invalid event timestamp','CORRUPT_STATE') from exc
            digest=event['event_hash'];without={k:v for k,v in event.items() if k!='event_hash'}
            if (digest!=_hash(without) or event['previous_hash']!=previous or event['key']!=key.as_dict()
                    or event['environment']!=self.environment or event['event_id'] in event_ids
                    or path.name!=f"{sequence:06d}.json" or event['state'] not in STATES):
                raise StateError('event chain, identity or environment mismatch','CORRUPT_STATE')
            if not isinstance(event['payload'],dict):raise StateError('event payload must be object','CORRUPT_STATE')
            self._check_event_semantics(events,event)
            events.append(event);previous=digest;event_ids.add(event['event_id']);sequence+=1
        return events

    def _check_event_semantics(self,events: list[dict],event: dict) -> None:
        previous=events[-1]['state'] if events else None
        kind=event['event_type'];payload=event['payload'];state=event['state']
        if kind=='started':
            valid=not events and state=='ready'
        elif kind=='legacy_imported':
            valid=not events and state=='legacy_saved_reported' and payload.get('reported_state')=='saved_verified'
        elif kind=='verification':
            valid=previous in VERIFY_FROM.get(state,set()) and not self._pending(events)
            if valid:self._verification(ExecutionKey(**event['key']),state,payload.get('verification'))
        elif kind=='operation_intent':
            operation=payload.get('operation');pending=self._pending(events)
            valid=not pending and previous in OPERATIONS.get(operation,set())
            target='save_requested' if operation=='save' else ('inserting' if operation in ('insert_block','upload_image') else previous)
            valid=valid and state==target and isinstance(event['operation_id'],str) and bool(event['operation_id'])
            valid=valid and all(e['operation_id']!=event['operation_id'] for e in events)
        elif kind=='operation_result':
            pending=self._pending(events);intent=pending.get(event['operation_id']);valid=intent is not None
            if valid:
                outcome=payload.get('outcome');operation=intent['payload']['operation']
                target=('save_acknowledged' if operation=='save' else previous) if outcome=='observed' else ('save_unknown' if operation=='save' else 'needs_reconciliation')
                valid=outcome in ('observed','failed','unknown') and state==target
                if outcome=='observed':
                    valid=valid and isinstance(payload.get('observed'),dict) and bool(payload['observed']) and bool(payload.get('evidence_ref'))
                    if operation=='save':valid=valid and payload.get('observed',{}).get('save_acknowledged') is True
        elif kind=='reconciled_saved':
            valid=bool(events) and previous in {'inserting','save_requested','save_acknowledged','save_unknown','needs_reconciliation','legacy_saved_reported'} and state=='reopened_verified'
            if valid:self._verification(ExecutionKey(**event['key']),'reopened_verified',payload.get('verification'))
        elif kind=='reconciled_input':
            valid=bool(events) and previous in {'editor_checked','inserting','needs_reconciliation'} and state=='inserting'
            if valid:self._input_evidence(ExecutionKey(**event['key']),payload.get('verification'))
        elif kind=='reconciled_not_saved':
            valid=bool(events) and previous in {'save_requested','save_unknown'} and state=='input_verified'
            if valid:self._not_saved_evidence(ExecutionKey(**event['key']),payload.get('verification'))
        else:valid=False
        if not valid:raise StateError('invalid event transition','INVALID_TRANSITION')

    def _pending(self,events: list[dict]) -> dict[str, dict]:
        pending={}
        for event in events:
            if event['event_type']=='operation_intent':pending[event['operation_id']]=event
            elif event['event_type']=='operation_result':pending.pop(event['operation_id'],None)
            elif event['event_type'] in ('reconciled_saved','reconciled_input','reconciled_not_saved'):pending.clear()
        return pending

    def _append(self,key: ExecutionKey,lease: Lease,kind: str,state: str,payload: dict,operation_id: str | None = None) -> dict:
        self._require_lease(lease,key.target_blog)
        events=self.events(key)
        event={'schema':'naver-draft-event/v1','sequence':len(events)+1,'event_id':uuid.uuid4().hex,
               'operation_id':operation_id,'event_type':kind,'state':state,'timestamp':_now(),
               'previous_hash':events[-1]['event_hash'] if events else None,'payload':payload,
               'key':key.as_dict(),'environment':self.environment}
        self._check_event_semantics(events,event)
        event['event_hash']=_hash(event)
        try:self._new_json(self._directory(key)/'events'/f"{event['sequence']:06d}.json",event)
        except FileExistsError as exc:
            raise StateError('event sequence already committed by another writer','EVENT_CONFLICT') from exc
        return event

    def status(self,key: ExecutionKey) -> dict:
        events=self.events(key);pending=self._pending(events)
        state=events[-1]['state'] if events else 'not_started'
        other=[];parent=self._directory(key).parent
        if parent.exists():
            for path in parent.iterdir():
                self._guard(path)
                if path.name!=key.revision and path.is_dir() and any(path.rglob('*.json')):other.append(path.name)
        if other:decision='revision_conflict'
        elif pending:decision='reconcile_save' if any(e['payload']['operation']=='save' for e in pending.values()) else 'reconcile_input'
        elif state=='blank_verified':decision='skip'
        elif state=='reopened_verified':decision='verify_blank_only'
        elif state in ('save_acknowledged','save_unknown','legacy_saved_reported'):decision='reconcile_save'
        elif state in ('inserting','editor_checked','input_verified','needs_reconciliation'):decision='reconcile_input'
        else:decision='start'
        return {'key':key.as_dict(),'environment':self.environment,'state':state,'resume_decision':decision,
                'pending_operations':list(pending),'conflicting_revisions':sorted(other),'event_count':len(events),
                'last_event_hash':events[-1]['event_hash'] if events else None}

    def start(self,key: ExecutionKey,lease: Lease) -> dict:
        status=self.status(key)
        if status['resume_decision']=='revision_conflict':raise StateError('another revision has execution history','REVISION_CONFLICT')
        if status['state']!='not_started':return status
        self._append(key,lease,'started','ready',{})
        return self.status(key)

    def _verification(self,key: ExecutionKey,state: str,evidence: Any) -> None:
        if not isinstance(evidence,dict) or evidence.get('environment')!=self.environment or evidence.get('content_revision')!=key.revision:
            raise StateError('verification environment/revision mismatch','INSUFFICIENT_EVIDENCE')
        if evidence.get('target_blog')!=key.target_blog or not evidence.get('evidence_ref') or not isinstance(evidence.get('observed'),dict) or not evidence['observed']:
            raise StateError('actual observations and evidence reference required','INSUFFICIENT_EVIDENCE')
        checks=evidence.get('checks',{})
        if (not isinstance(checks,dict) or any(checks.get(c) is not True for c in CHECKS[state])
                or any(value is not True for value in checks.values()) or evidence.get('status','passed')!='passed'
                or evidence.get('scope',state)!=state):
            raise StateError('verification checks incomplete','INSUFFICIENT_EVIDENCE')

    def verify(self,key: ExecutionKey,lease: Lease,state: str,evidence: dict) -> dict:
        if state not in VERIFY_FROM:raise StateError('unsupported verification target','INVALID_TRANSITION')
        if self._pending(self.events(key)):raise StateError('pending operation needs reconciliation','PENDING_OPERATION')
        self._verification(key,state,evidence)
        return self._append(key,lease,'verification',state,{'verification':evidence})

    def begin_operation(self,key: ExecutionKey,lease: Lease,operation: str,*,detail: dict | None = None,operation_id: str | None = None) -> str:
        if operation not in OPERATIONS:raise StateError('operation not allowed; publication is unsupported','OPERATION_DENIED')
        status=self.status(key)
        if status['conflicting_revisions']:raise StateError('revision conflict','REVISION_CONFLICT')
        oid=operation_id or uuid.uuid4().hex
        safe_segment(oid,'operation id')
        state='save_requested' if operation=='save' else ('inserting' if operation in ('insert_block','upload_image') else status['state'])
        self._append(key,lease,'operation_intent',state,{'operation':operation,'detail':detail or {}},oid)
        return oid

    def finish_operation(self,key: ExecutionKey,lease: Lease,operation_id: str,*,outcome: str,observed: dict | None,evidence_ref: str | None) -> dict:
        events=self.events(key);intent=self._pending(events).get(operation_id)
        if not intent:raise StateError('operation is not pending; duplicate results are not accepted','INVALID_OPERATION')
        operation=intent['payload']['operation']
        if outcome=='observed':
            if not isinstance(observed,dict) or not observed or not evidence_ref:
                raise StateError('operation completion needs an actual observation','INSUFFICIENT_EVIDENCE')
            if operation=='save' and observed.get('save_acknowledged') is not True:
                raise StateError('save acknowledgment not observed','INSUFFICIENT_EVIDENCE')
            state='save_acknowledged' if operation=='save' else events[-1]['state']
        else:state='save_unknown' if operation=='save' else 'needs_reconciliation'
        return self._append(key,lease,'operation_result',state,{'outcome':outcome,'observed':observed,'evidence_ref':evidence_ref},operation_id)

    def reconcile_saved(self,key: ExecutionKey,lease: Lease,evidence: dict) -> dict:
        self._verification(key,'reopened_verified',evidence)
        return self._append(key,lease,'reconciled_saved','reopened_verified',{'verification':evidence})

    def _input_evidence(self,key: ExecutionKey,evidence: Any) -> None:
        if not isinstance(evidence,dict) or evidence.get('content_revision')!=key.revision or evidence.get('environment')!=self.environment or evidence.get('target_blog')!=key.target_blog:
            raise StateError('input reconciliation identity mismatch','INSUFFICIENT_EVIDENCE')
        checks=evidence.get('checks',{})
        if (not isinstance(checks,dict) or any(checks.get(k) is not True for k in ('complete_observation','partial_content_matches','no_inflight_operation'))
                or any(value is not True for value in checks.values()) or evidence.get('status','passed')!='passed'
                or not isinstance(evidence.get('observed'),dict) or not evidence['observed'] or not evidence.get('evidence_ref')):
            raise StateError('partial input and operation outcome must be reconciled','INSUFFICIENT_EVIDENCE')

    def reconcile_input(self,key: ExecutionKey,lease: Lease,evidence: dict) -> dict:
        self._input_evidence(key,evidence)
        return self._append(key,lease,'reconciled_input','inserting',{'verification':evidence})

    def _not_saved_evidence(self,key: ExecutionKey,evidence: Any) -> None:
        self._verification(key,'input_verified',evidence)
        if evidence.get('user_confirmed_retry') is not True or any(evidence['checks'].get(c) is not True for c in ('no_saved_match','no_inflight_operation','current_input_matches')):
            raise StateError('explicit retry approval and complete not-saved reconciliation required','INSUFFICIENT_EVIDENCE')

    def reconcile_not_saved(self,key: ExecutionKey,lease: Lease,evidence: dict) -> dict:
        self._not_saved_evidence(key,evidence)
        return self._append(key,lease,'reconciled_not_saved','input_verified',{'verification':evidence})

    def write_summary(self,key: ExecutionKey,lease: Lease) -> Path:
        self._require_lease(lease,key.target_blog)
        summary=self.status(key)
        directory=self._directory(key)
        if not summary['event_count']:raise StateError('no event history to summarize')
        path=self._guard(directory/'execution-summary.json')
        temp=directory/('.summary-'+uuid.uuid4().hex+'.json')
        try:
            self._new_json(temp,summary)
            self._guard(path)
            os.replace(temp,path)
        finally:temp.unlink(missing_ok=True)
        return path

    def import_legacy(self,key: ExecutionKey,lease: Lease,path: Path) -> dict:
        """Read an explicit old per-episode report; never alter it or infer reopen."""
        raw=Path(path).read_bytes()
        try:record=json.loads(raw)
        except ValueError as exc:raise StateError('invalid legacy report','INVALID_LEGACY') from exc
        if not isinstance(record,dict) or record.get('status')!='saved_verified' or record.get('episode',key.episode)!=key.episode:
            raise StateError('legacy report does not establish saved status for this episode','INVALID_LEGACY')
        identities=[]
        if 'episode' in record:identities.append(record['episode'])
        for name in (Path(path).stem,Path(path).parent.name):
            match=re.fullmatch(r'episode-(\d+)',name)
            if match:identities.append(int(match.group(1)))
        if not identities or any(type(n) is not int or n!=key.episode for n in identities):
            raise StateError('legacy episode identity is missing or conflicting','INVALID_LEGACY')
        if self.status(key)['conflicting_revisions']:
            raise StateError('legacy revision conflict','REVISION_CONFLICT')
        self._append(key,lease,'legacy_imported','legacy_saved_reported',
                     {'source':str(Path(path).resolve()),'source_sha256':hashlib.sha256(raw).hexdigest(),
                      'reported_state':'saved_verified','observed_reopened':None})
        return self.status(key)
