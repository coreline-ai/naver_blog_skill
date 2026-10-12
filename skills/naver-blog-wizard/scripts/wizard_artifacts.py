#!/usr/bin/env python3
"""Local article/image adapters. Never runs image models or Naver UI."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path
import sys
sys.dont_write_bytecode=True

def resolve_repo():
    repo=Path(__file__).resolve().parents[3]
    for relative in ('scripts/build_blog_image_prompts.py','scripts/insert_article_images.py',
                     'skills/naver-smarteditor-drafter/scripts/build_naver_post.py',
                     'skills/naver-series-workflow/scripts/content_metrics.py'):
        if not (repo/relative).is_file(): raise ValueError('DEPENDENCY_MISSING: '+relative)
    return repo
REPO=resolve_repo()
for relative in ('scripts','skills/naver-smarteditor-drafter/scripts','skills/naver-series-workflow/scripts'):
    sys.path.insert(0,str(REPO/relative))
from build_naver_post import build_post
from content_metrics import body_metrics
from post_contract import load_json_object, BuildError
from asset_integrity import inspect_asset,verify_asset

def read_json(path):
    # Existing loader also rejects duplicate keys and non-finite values.
    return load_json_object(Path(path))

def file_sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def local_path(value,root,output=False):
    if not isinstance(value,(str,Path)): raise BuildError('file path required','UNSAFE_PATH')
    p=Path(value); root=Path(root).resolve()
    if '..' in p.parts: raise BuildError('path contains ..','UNSAFE_PATH')
    p=p if p.is_absolute() else root/p
    if any(x.is_symlink() for x in (p,*p.parents)): raise BuildError('symlink path','UNSAFE_PATH')
    p=p.resolve()
    if not p.is_relative_to(root) or (not output and not p.is_file()): raise BuildError('file outside root or missing','UNSAFE_PATH')
    return p

def run_root(s):
    root=Path(s['work_root'])/s['run_root']
    if any(p.is_symlink() for p in (root,*root.parents)): raise BuildError('unsafe work directory','UNSAFE_PATH')
    return root.resolve()

def register_article(path,root,profile_path=None):
    path=local_path(path,root)
    if path.suffix!='.md': raise BuildError('wizard article must be Markdown')
    digest=file_sha(path); post,warnings=build_post(path,Path(root),markdown_text=RAW_MARKER_RE.sub('',path.read_text(encoding='utf-8')))
    record={'path':str(path),'sha256':digest,'metrics':body_metrics(post),'warnings':warnings}
    if record['metrics']['body_char_count']==0: raise BuildError('substantive article required','BODY_REQUIRED')
    if profile_path:
        profile=local_path(profile_path,root); record['profile']={'path':str(profile),'sha256':file_sha(profile)}
    if file_sha(path)!=digest: raise BuildError('article changed','STALE_ARTICLE')
    return record

# Image/slot functions deliberately delegate calculations to existing project code.
import argparse
import copy
import os
import re
import subprocess
import shutil
import tempfile
import uuid
from insert_article_images import RAW_MARKER_RE, _extract_marker_ids, compose_article_data
from build_blog_image_prompts import normalize_slots

def _atomic_publish(path,data):
    path=Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    if path.exists(): raise BuildError('choose a new output version','OUTPUT_EXISTS')
    fd,name=tempfile.mkstemp(prefix='.wizard-artifact-',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.link(name,path)
    finally: Path(name).unlink(missing_ok=True)
    return path

def version_path(root,stem,suffix):
    root=Path(root); n=1
    while (root/f'{stem}.v{n}{suffix}').exists(): n+=1
    return local_path(root/f'{stem}.v{n}{suffix}',root,output=True)

def write_json(path,data):
    return _atomic_publish(path,(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode())

def stage_input(source,root,versioned_name):
    source=Path(source).expanduser()
    if '..' in source.parts or any(p.is_symlink() for p in (source,*source.parents)) or not source.is_file():
        raise BuildError('source must be a real nonsymlink file','UNSAFE_PATH')
    if source.suffix.lower() in {'.png','.jpg','.jpeg'}: inspect_asset(source,source.parent.resolve())
    destination=local_path(versioned_name,root,output=True); destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.exists(): raise BuildError('choose a new input version','OUTPUT_EXISTS')
    fd,name=tempfile.mkstemp(prefix='.wizard-input-',dir=destination.parent)
    try:
        with source.open('rb') as original, os.fdopen(fd,'wb') as stream:
            shutil.copyfileobj(original,stream); stream.flush(); os.fsync(stream.fileno())
        os.link(name,destination)
    finally: Path(name).unlink(missing_ok=True)
    return destination

def stage_edit_target(s):
    """Freeze an external original inside the run before recording an edit intent."""
    if s['task_mode']!='edit-existing': raise BuildError('standalone edit target required')
    root=run_root(s); source=Path(_option(s,'edit_target'))
    if '..' in source.parts or any(p.is_symlink() for p in (source,*source.parents)):
        raise BuildError('unsafe edit target','UNSAFE_PATH')
    if not source.is_absolute():
        # Relative paths remain run-local; never interpret them against cwd.
        return inspect_asset(local_path(source,root),root)
    if source.resolve().is_relative_to(root):
        return inspect_asset(local_path(source,root),root)
    original=inspect_asset(source,source.parent.resolve())
    destination=local_path(f"inputs/edit-original.{original['sha256']}{source.suffix.lower()}",root,output=True)
    if not destination.exists(): stage_input(source,root,destination)
    staged=inspect_asset(destination,root)
    if any(staged[key]!=original[key] for key in ('sha256','bytes','format','width','height')):
        raise BuildError('staged edit copy differs from the original; preserve both files','ASSET_CHANGED')
    verify_asset(original,source.parent.resolve())
    return staged

def _without_markers(text):
    # Only remove entire marker lines (including their own inserted newline).
    standalone=re.compile(r'^<!--\s*naver-image:[a-z0-9][a-z0-9-]*\s*-->\r?\n',re.M)
    for line in text.splitlines():
        if 'naver-image:' in line and not re.fullmatch(r'<!--\s*naver-image:[a-z0-9][a-z0-9-]*\s*-->',line):
            raise BuildError('marker must be a standalone line','INVALID_SLOT_MARKER')
    fenced=False
    for line in text.splitlines():
        if re.match(r'^\s*(```|~~~)',line): fenced=not fenced
        if fenced and 'naver-image:' in line: raise BuildError('marker inside code block','INVALID_SLOT_MARKER')
    return standalone.sub('',text)

def validate_slot_article(source,candidate,slots,root):
    source=local_path(source,root); candidate=local_path(candidate,root)
    if candidate==source: raise BuildError('keep original article separate','OUTPUT_EXISTS')
    slots=normalize_slots(slots)
    original=source.read_bytes(); marked=candidate.read_bytes()
    original_body=_without_markers(original.decode()); candidate_body=_without_markers(marked.decode())
    # A terminal marker may need exactly one separator after a no-newline input.
    eof_separator=(not original_body.endswith(('\n','\r')) and re.fullmatch(r'<!--\s*naver-image:[a-z0-9][a-z0-9-]*\s*-->',marked.decode().splitlines()[-1]) and candidate_body in (original_body+'\n',original_body+'\r\n'))
    if original_body!=candidate_body and not eof_separator:
        raise BuildError('slot article changes original body or whitespace','ARTICLE_CHANGED')
    if _extract_marker_ids(marked.decode())!=[slot['id'] for slot in slots]: raise BuildError('ordered marker mismatch','SLOT_MARKER_MISMATCH')
    build_post(candidate,Path(root),markdown_text=RAW_MARKER_RE.sub('',marked.decode()))
    return {'path':str(candidate),'sha256':hashlib.sha256(marked).hexdigest(),'source_sha256':hashlib.sha256(original).hexdigest(),'slots':slots}

def _option(s,key,default=None): return s['confirmed_options'].get(key,{}).get('value',default)

def compile_image_request(s,slot_article,slots):
    root=run_root(s); article=local_path(slot_article['path'],root)
    if file_sha(article)!=slot_article['sha256']: raise BuildError('slot article changed','STALE_ARTICLE')
    count=_option(s,'requested_count')
    if isinstance(count,bool) or not isinstance(count,int) or count<1 or len(slots)!=count: raise BuildError('exact N slots needed','SLOT_SHORTAGE')
    if not slots or slots[0]['role']!='cover' or sum(x['role']=='cover' for x in slots)!=1: raise BuildError('one first cover is included in N','COMPLETION_ROLES_NOT_MET')
    result={'schema':'naver-blog-image-request/v1','article':{'path':str(article),'expected_sha256':slot_article['sha256']},
            'presentation':_option(s,'presentation'),'language':'ko','requested_count':count,
            'article_type':_option(s,'article_type','information'),'format_preset':_option(s,'format_preset','auto'),
            'additional_requirements':'' if _option(s,'additional_requirements')=='none' else _option(s,'additional_requirements',''),
            'slots':normalize_slots(slots)}
    if _option(s,'reference_use')=='yes':
        path=local_path(_option(s,'reference_path'),root); inspect_asset(path,root)
        result['reference']={'path':str(path),'instructions':'' if _option(s,'reference_instructions')=='default' else _option(s,'reference_instructions','')}
    return result

def run_image_helper(request_path,root,operation,output_path=None,manifest=None,composed=None):
    root=Path(root); request=local_path(request_path,root)
    args=[sys.executable,'-B',str(REPO/'scripts/build_blog_image_prompts.py'),'--input',str(request),'--project-root',str(root),'--operation',operation]
    if output_path: args+=['--output',str(local_path(output_path,root,output=True))]
    else: args+=['--check']
    if manifest or composed:
        if not manifest or not composed: raise BuildError('paired completion arguments required')
        args+=['--manifest',str(local_path(manifest,root)),'--composed-article',str(local_path(composed,root))]
    result=subprocess.run(args,capture_output=True,text=True,shell=False)
    if result.returncode not in (0,1): raise BuildError(result.stderr.strip() or 'helper failed','HELPER_INVALID')
    data=json.loads(result.stdout)
    return data

def validate_slide_briefs(plan):
    issues=[]; seen=set()
    for e in plan.get('entries',[]):
        if e['presentation']!='info-slide': continue
        brief=e.get('brief') or {}; points=brief.get('points',[])
        if len(points) not in (2,3): issues.append({'code':'SLIDE_BRIEF_INSUFFICIENT','slot_id':e['id']})
        signature=tuple(sorted(re.sub(r'\s+','',p).casefold() for p in points))
        if signature and signature in seen: issues.append({'code':'SLIDE_BRIEF_DUPLICATE','slot_id':e['id']})
        seen.add(signature)
    return issues

def register_plan(s,payload):
    root=run_root(s); request_path=local_path(payload['request_path'],root); plan_path=local_path(payload['plan_path'],root)
    req=read_json(request_path)
    expected=compile_image_request(s,s['slot_selection'],s['slot_selection']['slots'])
    if req!=expected: raise BuildError('request differs from current options','STALE_PLAN')
    operation='plan-only' if _option(s,'image_action')=='prompt-only' else 'generate-and-compose'
    fresh=run_image_helper(request_path,root,operation)
    if fresh!=read_json(plan_path): raise BuildError('plan differs from actual helper','STALE_PLAN')
    issues=fresh['diagnostics'] if fresh['status']!='planned' else validate_slide_briefs(fresh)
    return {'validation_issues':issues,'request_path':str(request_path),'request_sha256':file_sha(request_path),'path':str(plan_path),
            'sha256':file_sha(plan_path),'operation':operation,'data':fresh}

def plan_entries(s): return (s.get('image_plan') or {}).get('data',{}).get('entries',[])

def _binding(s,entry=None):
    if s['task_mode']=='edit-existing':
        target=local_path(_option(s,'edit_target'),run_root(s)); original=inspect_asset(target,run_root(s))
        return {'article_sha256':None,'prompt_sha256':hashlib.sha256(_option(s,'edit_instruction').encode()).hexdigest(),
                'role':'standalone','presentation':'edit','reference_sha256':original['sha256']}
    entry=entry or {}; plan=s['image_plan']['data']
    return {'image_action':_option(s,'image_action'),'article_sha256':s['article']['sha256'],'prompt_sha256':hashlib.sha256(entry['prompt'].encode()).hexdigest(),
            'role':entry['role'],'presentation':entry['presentation'],
            'reference_sha256':(plan.get('reference') or {}).get('sha256')}

def asset_matches(s,asset):
    if s['task_mode']=='edit-existing': return asset['slot_id']=='edit-target' and asset.get('binding')==_binding(s)
    entry=next((e for e in plan_entries(s) if e['id']==asset['slot_id']),None)
    return entry is not None and asset.get('binding')==_binding(s,entry)

def prepare_effect(s,step,tool_prompt=None):
    slot=step['slot_id']; standalone=s['task_mode']=='edit-existing'
    entry=None if standalone else next(e for e in plan_entries(s) if e['id']==slot)
    prompt=tool_prompt or (_option(s,'edit_instruction') if standalone else entry['prompt'])
    if not isinstance(prompt,str) or not prompt.strip(): raise BuildError('tool prompt required')
    effect={'id':str(uuid.uuid4()),'status':'intent','slot_id':slot,'action':step['action'],
            'binding':_binding(s,entry),'tool_prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'tool_prompt':prompt}
    if step['action'] in {'edit_image','repair_image'}:
        target=_option(s,'edit_target') if standalone else next(a['inspection']['path'] for a in s['assets'] if a['slot_id']==slot)
        effect['target']=inspect_asset(local_path(target,run_root(s)),run_root(s))
    return effect

def bind_asset(s,slot_id,path,provenance):
    root=run_root(s)
    if provenance not in {'generated','user-file','edited'}: raise BuildError('invalid provenance')
    inspection=inspect_asset(local_path(path,root),root)
    entry=next((e for e in plan_entries(s) if e['id']==slot_id),None)
    if s['task_mode']!='edit-existing' and entry is None: raise BuildError('slot missing from plan')
    binding=_binding(s,entry)
    if provenance!='user-file':
        effect=s.get('effect')
        if not effect or effect['binding']!=binding: raise BuildError('effect inputs changed','STALE_PLAN')
        if effect.get('target'): verify_asset(effect['target'],root)
    for other in s['assets']:
        if other['slot_id']!=slot_id and asset_matches(s,other) and other['inspection']['sha256']==inspection['sha256']:
            raise BuildError('different slots need unique actual files','DUPLICATE_ASSET')
    if binding['presentation']=='info-slide':
        error=abs(inspection['width']*5-inspection['height']*4)
        if error>4 or error*1000>inspection['height']*4: raise BuildError('slide must have 4:5 ratio','SLIDE_ASPECT_MISMATCH')
    return {'slot_id':slot_id,'inspection':inspection,'binding':binding,'provenance':provenance,
            'origin_plan':(s.get('image_plan') or {}).get('sha256'),'qa':None,'caption':'','corrections':0}

def inspect_bindings(s):
    diagnostics=[]; root=run_root(s)
    records=[s.get('article'),(s.get('article') or {}).get('profile'),s.get('slot_selection'),s.get('image_plan')]
    for record in records:
        if not record: continue
        pairs=[('path','sha256')]
        if record.get('slots_path'): pairs.append(('slots_path','slots_sha256'))
        if record.get('request_path'): pairs.append(('request_path','request_sha256'))
        for pathkey,hashkey in pairs:
            try:
                p=local_path(record[pathkey],root)
                if file_sha(p)!=record[hashkey]: raise BuildError('input bytes changed','STALE_ARTIFACT')
            except (BuildError,OSError,KeyError) as exc: diagnostics.append({'code':getattr(exc,'code','INVALID_RECORD'),'path':record.get(pathkey),'detail':str(exc)})
    try:
        if s.get('slot_selection'):
            selection=s['slot_selection']
            if selection['source_sha256']!=s['article']['sha256'] or read_json(selection['slots_path'])!={'slots':selection['slots']}: raise BuildError('slot cache differs from source','STALE_PLAN')
        if s.get('image_plan'):
            record=s['image_plan']
            if read_json(record['path'])!=record['data'] or read_json(record['request_path'])!=compile_image_request(s,s['slot_selection'],s['slot_selection']['slots']): raise BuildError('plan cache differs from actual current request','STALE_PLAN')
            issues=record['data']['diagnostics'] if record['data']['status']!='planned' else validate_slide_briefs(record['data'])
            if record.get('validation_issues')!=issues: raise BuildError('invalid plan validation cache','STALE_PLAN')
            ref=s['image_plan']['data'].get('reference')
            if ref: verify_asset({k:v for k,v in ref.items() if k!='instructions'},root)
        if s.get('effect') and s['effect']['status']=='intent' and s['effect'].get('target'): verify_asset(s['effect']['target'],root)
        for asset in s['assets']:
            if asset_matches(s,asset):
                verify_asset(asset['inspection'],root)
                if asset.get('qa') and asset['qa']['asset_sha256']!=asset['inspection']['sha256']: raise BuildError('stale visual QA','ASSET_CHANGED')
        if s.get('completion'):
            p={'manifest_path':s['completion']['manifest'],'composed_article_path':s['completion']['composed_article'],'completion_path':s['completion']['report']}
            if register_package(s,p)!=s['completion']: raise BuildError('completion cache differs from package','PACKAGE_CHANGED')
            for key in ('manifest','composed_article','report'):
                p=local_path(s['completion'][key],root)
                if file_sha(p)!=s['completion'][key+'_sha256']: raise BuildError('completion file changed','PACKAGE_CHANGED')
    except (BuildError,OSError,KeyError,ValueError,TypeError) as exc: diagnostics.append({'code':getattr(exc,'code','INVALID_RECORD'),'detail':str(exc)})
    return {'ok':not diagnostics,'diagnostics':diagnostics}

def _adopted(s):
    result=[]
    for entry in plan_entries(s):
        asset=next((a for a in s['assets'] if a['slot_id']==entry['id'] and asset_matches(s,a)),None)
        if not asset or not asset.get('qa',{} ) or not asset['qa']['passed']: raise BuildError('actual files and visual QA required','QA_REQUIRED')
        verify_asset(asset['inspection'],run_root(s)); result.append((entry,asset))
    if len(result)!=_option(s,'requested_count'): raise BuildError('exact N approved assets required')
    return result

def compose_and_verify(s,root):
    from wizard_session import next_step
    if next_step(s).get('action')!='compose_article': raise BuildError('composition not current action')
    root=Path(root)
    if root.resolve()!=run_root(s): raise BuildError('wrong run_root','UNSAFE_PATH')
    slots=[]
    for e,a in _adopted(s):
        slots.append({'id':e['id'],'role':e['role'],'placement':e['placement'],'purpose':e['purpose'],
                      'mode':e['mode'],'prompt':e['manifest_prompt'],'alt':e['alt'],'caption':a.get('caption',''),
                      'path':str(Path(a['inspection']['path']).relative_to(root)),'status':'approved'})
    manifest=version_path(root,'manifest','.json'); write_json(manifest,{'version':1,'asset_root':'.','slots':slots})
    composed=version_path(root,'article-with-images','.md')
    text,_=compose_article_data(s['slot_selection']['path'],manifest,root=root,absolute_image_paths=True)
    _atomic_publish(composed,text.encode())
    report_path=version_path(root,'completion','.json')
    report=run_image_helper(s['image_plan']['request_path'],root,'generate-and-compose',report_path,manifest,composed)
    if report['status']!='package_verified': raise BuildError(json.dumps(report['diagnostics']),'PACKAGE_INCOMPLETE')
    return {'manifest_path':str(manifest),'composed_article_path':str(composed),'completion_path':str(report_path)}

def register_package(s,p):
    root=run_root(s); _adopted(s)
    fresh=run_image_helper(s['image_plan']['request_path'],root,'generate-and-compose',manifest=p['manifest_path'],composed=p['composed_article_path'])
    report_path=local_path(p['completion_path'],root)
    if fresh['status']!='package_verified' or fresh!=read_json(report_path): raise BuildError('package does not match current actual files','PACKAGE_INCOMPLETE')
    expected={e['id']:a['inspection']['sha256'] for e,a in _adopted(s)}
    manifest=read_json(local_path(p['manifest_path'],root))
    for slot in manifest['slots']:
        current=inspect_asset(local_path(slot['path'],root),root)
        if current['sha256']!=expected[slot['id']]: raise BuildError('manifest substitutes reviewed asset','ASSET_CHANGED')
    record={'manifest':str(local_path(p['manifest_path'],root)),'composed_article':str(local_path(p['composed_article_path'],root)),'report':str(report_path)}
    for key in tuple(record): record[key+'_sha256']=file_sha(record[key])
    return record

def prepare_plan(s):
    from wizard_session import next_step
    if next_step(s).get('action')!='prepare_plan': raise BuildError('plan preparation not current action')
    root=run_root(s)
    # The user supplied path is copied before it enters the strict helper root.
    ref=_option(s,'reference_path')
    if _option(s,'reference_use')=='yes':
        try: local_path(ref,root)
        except BuildError:
            path=version_path(root,'reference',Path(ref).suffix)
            stage_input(ref,root,path)
            # Return a change event rather than silently altering confirmed options.
            return {'change':{'key':'reference_path','value':str(path)},'next_action':'record_reference_path'}
    request=compile_image_request(s,s['slot_selection'],s['slot_selection']['slots'])
    request_path=version_path(root,'image-request','.json'); write_json(request_path,request)
    operation='plan-only' if _option(s,'image_action')=='prompt-only' else 'generate-and-compose'
    plan_path=version_path(root,'image-plan','.json'); plan=run_image_helper(request_path,root,operation,plan_path)
    issues=plan['diagnostics'] if plan['status']!='planned' else validate_slide_briefs(plan)
    if issues: return {'status':'requires_design','diagnostics':issues,'payload':{'request_path':str(request_path),'plan_path':str(plan_path)}}
    return {'status':'planned','payload':{'request_path':str(request_path),'plan_path':str(plan_path)}}

def main(argv=None):
    from wizard_session import load_session
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['inspect','prepare-plan','compose']); parser.add_argument('--session',required=True)
    args=parser.parse_args(argv)
    try:
        s=load_session(args.session)
        result=inspect_bindings(s) if args.command=='inspect' else prepare_plan(s) if args.command=='prepare-plan' else {'payload':compose_and_verify(s,run_root(s))}
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 1 if result.get('status')=='requires_design' or result.get('ok') is False else 0
    except (BuildError,ValueError,OSError,KeyError,TypeError) as exc:
        print(json.dumps({'code':getattr(exc,'code','INVALID_INPUT'),'message':str(exc)},ensure_ascii=False),file=sys.stderr); return 2

if __name__=='__main__': raise SystemExit(main())
