#!/usr/bin/env python3
"""One-question Naver Blog workflow. No LLM, generation or browser calls."""
from __future__ import annotations
import argparse
import copy
import fcntl
import json
import os
import re
from pathlib import Path
import sys
import tempfile
import uuid
sys.dont_write_bytecode = True
SCHEMA = 'naver-blog-wizard-session/v1'
ENUMS = {
 'task_mode': ('new','rewrite','images-only','edit-existing'),
 'article_type': ('information','howto','comparison','review','place','story','checklist','auto'),
 'format_preset': ('auto','clean','magazine','review','comparison','checklist','emotional'),
 'image_action': ('none','prompt-only','generate','use-files'),
 'presentation': ('standard','info-slide','mixed'), 'reference_use': ('no','yes'),
 'article_review': ('use','revise','change'), 'image_plan_review': ('use','change'),
 'image_review': ('use','edit','pause'),
 'failure_resolution': ('change-options','use-files','pause'),
 'article_change': ('topic','source_article','audience','article_type','tone','length','format_preset'),
 'image_change': ('presentation','requested_count','additional_requirements','reference_use'),
}
TEXT_KEYS = {'topic','source_article','audience','tone','experience_basis','additional_requirements',
             'reference_path','reference_instructions','edit_target','edit_instruction','edit_slot'}
OPTION_KEYS = set(ENUMS) | TEXT_KEYS | {'length','requested_count'}
WRITE_KEYS = {'task_mode','topic','source_article','audience','article_type','tone','length','format_preset','experience_basis'}
IMAGE_KEYS = {'image_action','presentation','requested_count','additional_requirements','reference_use','reference_path','reference_instructions'}
TITLES = {
 'task_mode':'어떤 작업을 진행할까요?', 'topic':'이번 글의 주제는 무엇인가요?',
 'source_article':'사용할 원고 파일은 어디에 있나요?', 'audience':'누가 읽는 글인가요?',
 'article_type':'어떤 유형의 글로 쓸까요?', 'tone':'어떤 문체로 쓸까요?',
 'length':'어느 정도 분량으로 쓸까요?', 'format_preset':'본문 서식을 선택해 주세요.',
 'experience_basis':'후기·방문 글에 사용할 실제 경험이나 자료가 있나요?',
 'article_review':'작성한 원고를 어떻게 처리할까요?', 'article_change':'어떤 작성 조건을 변경할까요?',
 'image_action':'이미지를 어떻게 처리할까요?', 'presentation':'이미지 표현 유형을 선택해 주세요.',
 'requested_count':'표지를 포함해 몇 장으로 구성할까요?', 'additional_requirements':'이미지에 추가할 요구사항이 있나요?',
 'reference_use':'참고 이미지를 사용할까요?', 'reference_path':'참고 이미지 파일은 어디에 있나요?',
 'reference_instructions':'참고 이미지에서 무엇을 반영할까요?', 'image_plan_review':'이미지 구성을 사용할까요?',
 'image_change':'어떤 이미지 조건을 변경할까요?', 'image_review':'검수한 이미지를 어떻게 처리할까요?',
 'edit_slot':'어떤 이미지를 수정할까요?', 'edit_target':'편집할 원본 이미지 파일은 어디에 있나요?',
 'edit_instruction':'이미지를 어떻게 수정할까요?', 'failure_resolution':'이미지 처리를 이어가기 위한 방법을 선택해 주세요.',
}
CHOICES = {
 'audience': ('beginner','general','experienced'), 'tone': ('plain','friendly','professional','profile'),
 'length': ('short','medium','long'), 'requested_count': (1,3,5,'auto'),
 'additional_requirements': ('none',), 'reference_instructions': ('default',),
 'experience_basis': ('source-based',),
}
LABELS = {'new':'새 글','rewrite':'원고 재작성','images-only':'원고 유지+이미지','edit-existing':'기존 이미지 편집',
 'none':'이미지 없음','prompt-only':'프롬프트만','generate':'이미지 생성','use-files':'내 파일 사용',
 'standard':'일반 이미지','info-slide':'정보 슬라이드 / 카드뉴스','mixed':'일반 표지+정보 슬라이드',
 'auto':'자동 선택','use':'사용','revise':'원고 수정','change':'조건 변경','edit':'특정 이미지 편집','pause':'중단',
 'short':'짧게(약 800~1,200자)','medium':'보통(약 1,500~2,200자)','long':'자세히(약 2,500~3,500자)',
 'beginner':'초보 독자','general':'일반 독자','experienced':'경험 있는 독자',
 'plain':'담백하게','friendly':'친근하게','professional':'전문적으로','profile':'저장한 문체 사용',
 'information':'정보 정리','howto':'방법·순서 안내','comparison':'선택 기준 비교','review':'실제 경험 후기',
 'place':'장소 안내','story':'이야기형','checklist':'체크리스트','clean':'간결한 서식','magazine':'잡지형 서식',
 'source-based':'실제 경험 없이 자료 기반 글로 변경','yes':'참고 이미지 사용','no':'참고 이미지 없음'}

class WizardError(ValueError):
    def __init__(self, message, code='INVALID_CONTRACT'):
        super().__init__(message); self.code=code

def _int(value):
    return isinstance(value,int) and not isinstance(value,bool) and value>=0

def read_json(path):
    def pairs(items):
        obj={}
        for key,value in items:
            if key in obj: raise WizardError('duplicate JSON key')
            obj[key]=value
        return obj
    def invalid(_): raise WizardError('non-finite JSON number')
    return json.loads(Path(path).read_text(encoding='utf-8'), object_pairs_hook=pairs, parse_constant=invalid)

def value(s,key,default=None):
    return s['confirmed_options'].get(key,{}).get('value',default)

def normalize_option(key,v):
    if key.startswith(('caption:','alt:')):
        if not re.fullmatch(r'(?:caption|alt):[a-z0-9][a-z0-9-]*',key) or not isinstance(v,str) or any(c in v for c in ('\n','\r','\x00')) or (key.startswith('alt:') and not v.strip()):
            raise WizardError('invalid slot metadata','INVALID_ANSWER')
        return v.strip()
    if key not in OPTION_KEYS: raise WizardError('unknown option: '+key,'INVALID_ANSWER')
    if key in ENUMS:
        if not isinstance(v,str) or v not in ENUMS[key]: raise WizardError('unsupported option: '+key,'INVALID_ANSWER')
    elif key=='requested_count':
        if v=='auto': return 5
        if not _int(v) or v<1: raise WizardError('count must be a positive integer','INVALID_ANSWER')
    elif key=='length':
        if not ((isinstance(v,str) and v in CHOICES[key]) or (_int(v) and v>0)):
            raise WizardError('invalid length','INVALID_ANSWER')
    elif not isinstance(v,str) or not v.strip() or '\x00' in v:
        raise WizardError('nonempty text required: '+key,'INVALID_ANSWER')
    return v.strip() if isinstance(v,str) else v

def validate_session(s):
    required={'schema','id','revision','work_root','run_root','status','task_mode','phase','pending_question_id',
              'confirmed_options','article','slot_selection','image_plan','assets','effect','completion'}
    if not isinstance(s,dict) or set(s)!=required or s['schema']!=SCHEMA: raise WizardError('invalid session schema')
    if not _int(s['revision']) or s['status'] not in {'active','paused'}: raise WizardError('invalid revision/status')
    if not isinstance(s['id'],str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]*',s['id']) or not isinstance(s['work_root'],str) or not Path(s['work_root']).is_absolute():
        raise WizardError('invalid session identity/work_root')
    work=Path(s['work_root'])
    if '..' in work.parts or any(p.is_symlink() for p in (work,*work.parents)) or work.resolve().is_relative_to(Path(__file__).resolve().parents[3]): raise WizardError('unsafe work_root','UNSAFE_PATH')
    run=Path(s['run_root'])
    if run.is_absolute() or '..' in run.parts or run.as_posix()!=f"naver-blog-output/{s['id']}": raise WizardError('invalid run_root')
    if not isinstance(s['confirmed_options'],dict) or not isinstance(s['assets'],list): raise WizardError('invalid options/assets')
    for key,opt in s['confirmed_options'].items():
        if not isinstance(opt,dict) or set(opt)!={'value','origin','user_text'}: raise WizardError('invalid confirmed option')
        if opt['origin'] not in {'initial-request','answer','explicit-default'} or not isinstance(opt['user_text'],str): raise WizardError('invalid option origin')
        if normalize_option(key,opt['value'])!=opt['value']: raise WizardError('option not canonical')
    if s['task_mode']!=value(s,'task_mode'): raise WizardError('task_mode mismatch')
    if value(s,'task_mode')=='images-only' and value(s,'image_action')=='none': raise WizardError('images-only needs images','INVALID_ANSWER')
    for name in ('article','slot_selection','image_plan','effect','completion'):
        if s[name] is not None and not isinstance(s[name],dict): raise WizardError('invalid '+name)
    if any(not isinstance(a,dict) or not isinstance(a.get('slot_id'),str) for a in s['assets']): raise WizardError('invalid asset record')
    if len({a['slot_id'] for a in s['assets']})!=len(s['assets']): raise WizardError('duplicate asset slot')
    return s

def new_session(work_root,initial_options=None):
    root=Path(work_root).expanduser()
    if '..' in root.parts or any(p.is_symlink() for p in (root,*root.parents)): raise WizardError('unsafe work_root','UNSAFE_PATH')
    root=root.resolve()
    repo=Path(__file__).resolve().parents[3]
    if root.is_relative_to(repo): raise WizardError('choose a user workspace outside skill source','UNSAFE_PATH')
    options=initial_options or {}
    if not isinstance(options,dict): raise WizardError('initial options must be object')
    ident=str(uuid.uuid4())
    s={'schema':SCHEMA,'id':ident,'revision':0,'work_root':str(root),'run_root':f'naver-blog-output/{ident}',
       'status':'active','task_mode':None,'phase':'setup','pending_question_id':None,'confirmed_options':{},
       'article':None,'slot_selection':None,'image_plan':None,'assets':[],'effect':None,'completion':None}
    for k,v in options.items(): _set_option(s,k,v,'initial-request')
    _cache(s); return validate_session(s)

def _set_option(s,key,v,origin='answer'):
    normalized=normalize_option(key,v)
    s['confirmed_options'][key]={'value':normalized,'origin':'explicit-default' if key=='requested_count' and v=='auto' else origin,'user_text':str(v)}
    if key=='task_mode': s['task_mode']=normalized
    if key=='experience_basis' and normalized=='source-based': _set_option(s,'article_type','information',origin)

def _question(s,key,options=None):
    vals=list(options if options is not None else ENUMS.get(key,CHOICES.get(key,())))[:5]
    if key=='image_action' and s['task_mode']=='images-only': vals=[v for v in vals if v!='none']
    return {'kind':'question','revision':s['revision'],'question_id':f"{key}:r{s['revision']}",'key':key,
            'title':TITLES[key],'options':[{'value':v,'label':('추천 구성(5장)' if key=='requested_count' and v=='auto' else '추가 요구 없음' if key=='additional_requirements' and v=='none' else LABELS.get(v,str(v)))} for v in vals],'accepts_custom':True}

def _action(s,name,**data):
    return {'kind':'action','revision':s['revision'],'action':name,**data}

def _complete(s,mode):
    return {'kind':'complete','revision':s['revision'],'mode':mode,'article':s['article'],'completion':s['completion'],
            'assets':s['assets'] if mode!='prompt-only' else []}

def next_step(s,artifact_report=None):
    validate_session(s)
    if s['status']=='paused': return {'kind':'paused','revision':s['revision']}
    if artifact_report is None:
        from wizard_artifacts import inspect_bindings
        artifact_report=inspect_bindings(s)
    if not artifact_report.get('ok',False): return _action(s,'repair_artifacts',diagnostics=artifact_report.get('diagnostics',[]))
    if s['effect'] and s['effect']['status']=='intent': return _action(s,'reconcile',effect=s['effect'])
    if s['effect'] and s['effect']['status']=='failed': return _question(s,'failure_resolution')
    mode=s['task_mode']
    if mode is None: return _question(s,'task_mode')
    if mode=='edit-existing':
        for key in ('edit_target','edit_instruction'):
            if key not in s['confirmed_options']: return _question(s,key)
        return _asset_steps(s,standalone=True)
    input_key='topic' if mode=='new' else 'source_article'
    if input_key not in s['confirmed_options']: return _question(s,input_key)
    if mode!='images-only':
        for key in ('audience','article_type','tone','length','format_preset'):
            if key not in s['confirmed_options']: return _question(s,key)
        if value(s,'article_type') in {'review','place'} and 'experience_basis' not in s['confirmed_options']:
            return _question(s,'experience_basis')
    if not s['article']: return _action(s,'use_source_article' if mode=='images-only' else 'rewrite_article' if mode=='rewrite' else 'write_article',options=s['confirmed_options'])
    review=value(s,'article_review')
    if review=='revise': return _action(s,'rewrite_article',article=s['article'],options=s['confirmed_options'])
    if review=='change': return _question(s,'article_change')
    if review!='use': return _question(s,'article_review')
    if 'image_action' not in s['confirmed_options']: return _question(s,'image_action')
    if value(s,'image_action')=='none': return _complete(s,'text-only')
    for key in ('presentation','requested_count','additional_requirements','reference_use'):
        if key not in s['confirmed_options']: return _question(s,key)
    if value(s,'reference_use')=='yes':
        for key in ('reference_path','reference_instructions'):
            if key not in s['confirmed_options']: return _question(s,key)
    if not s['slot_selection']: return _action(s,'design_slots',requested_count=value(s,'requested_count'),article=s['article'])
    if value(s,'edit_slot') and not s['slot_selection'].get('edit_instruction')==value(s,'edit_instruction'):
        return _action(s,'revise_slot_plan',slot_id=value(s,'edit_slot'),instruction=value(s,'edit_instruction'))
    for key,opt in s['confirmed_options'].items():
        if key.startswith('alt:'):
            ident=key.split(':',1)[1]
            slot=next((x for x in s['slot_selection']['slots'] if x['id']==ident),None)
            if slot and slot.get('alt')!=opt['value']: return _action(s,'revise_slot_metadata',slot_id=ident,alt=opt['value'])
    if not s['image_plan']: return _action(s,'prepare_plan')
    if s['image_plan'].get('validation_issues'): return _action(s,'design_slots',diagnostics=s['image_plan']['validation_issues'],requested_count=value(s,'requested_count'))
    if value(s,'image_plan_review')=='change': return _question(s,'image_change')
    if value(s,'image_plan_review')!='use': return _question(s,'image_plan_review')
    if value(s,'image_action')=='prompt-only': return _complete(s,'prompt-only')
    return _asset_steps(s)

def _asset_steps(s,standalone=False):
    from wizard_artifacts import asset_matches, plan_entries
    entries=[{'id':'edit-target'}] if standalone else plan_entries(s)
    for entry in entries:
        a=next((a for a in s['assets'] if a['slot_id']==entry['id'] and asset_matches(s,a)),None)
        if not a:
            action='edit_image' if standalone or value(s,'edit_slot')==entry['id'] else 'import_image' if value(s,'image_action')=='use-files' else 'generate_image'
            return _action(s,action,slot_id=entry['id'],entry=entry)
        qa=a.get('qa')
        if not qa: return _action(s,'visual_review',slot_id=entry['id'],asset=a)
        if not qa['passed']:
            if a.get('corrections',0)>=1: return _question(s,'failure_resolution')
            return _action(s,'repair_image',slot_id=entry['id'],asset=a,notes=qa['notes'])
    if value(s,'image_review')=='edit':
        if not value(s,'edit_slot'): return _question(s,'edit_slot',[e['id'] for e in entries])
        if not value(s,'edit_instruction'): return _question(s,'edit_instruction')
    if value(s,'image_review')!='use': return _question(s,'image_review')
    if standalone: return _complete(s,'edit-existing')
    if not s['completion']: return _action(s,'compose_article')
    return _complete(s,value(s,'image_action'))

def _revision(s,expected):
    validate_session(s)
    if not _int(expected) or expected!=s['revision']: raise WizardError('stale revision','REVISION_CONFLICT')

def _cache(s):
    step=next_step(s)
    s['pending_question_id']=step.get('question_id')
    if step['kind']=='question':
        key=step['key']
        s['phase']=('setup' if key in {'task_mode','topic','source_article','edit_target'} else
                    'writing-options' if key in {'audience','article_type','tone','length','format_preset','experience_basis','article_change'} else
                    'article-review' if key=='article_review' else 'plan-review' if key=='image_plan_review' else
                    'image-options' if key in IMAGE_KEYS|{'image_change'} else 'image-review')
    elif step['kind']=='action':
        action=step['action']
        s['phase']=('writing' if action in {'write_article','rewrite_article','use_source_article'} else
                    'planning' if action in {'design_slots','revise_slot_plan','revise_slot_metadata','prepare_plan'} else
                    'composition' if action=='compose_article' else 'recovery' if action=='repair_artifacts' else 'assets')
    else: s['phase']=step['kind']

def _finish(s):
    s['revision']+=1; _cache(s); return validate_session(s)

def _drop(s,*keys):
    for key in keys: s['confirmed_options'].pop(key,None)

def _invalidate(s,key):
    s['completion']=None
    if key in WRITE_KEYS:
        s['article']=None; s['slot_selection']=None; s['image_plan']=None; s['effect']=None
        _drop(s,'article_review','image_plan_review','image_review','edit_slot','edit_instruction')
    elif key in IMAGE_KEYS:
        s['slot_selection']=None; s['image_plan']=None; s['effect']=None
        _drop(s,'image_plan_review','image_review','edit_slot','edit_instruction')
    elif key=='edit_target':
        s['assets']=[]; s['effect']=None; _drop(s,'image_review')


def apply_answer(s,question_id,v,expected_revision):
    _revision(s,expected_revision)
    step=next_step(s)
    if step['kind']!='question' or question_id!=step['question_id']: raise WizardError('question is no longer current','STALE_QUESTION')
    key=step['key']; n=copy.deepcopy(s)
    if key in {'article_change','image_change'}:
        selected=normalize_option(key,v)
        _drop(n,selected,'article_review' if key=='article_change' else 'image_plan_review'); _invalidate(n,selected)
    else:
        _set_option(n,key,v)
        if key=='edit_slot':
            from wizard_artifacts import plan_entries
            if v not in [e['id'] for e in plan_entries(n)]: raise WizardError('unknown edit slot','INVALID_ANSWER')
        if key=='failure_resolution':
            n['effect']=None
            if v=='pause': n['status']='paused'
            elif v=='use-files':
                _set_option(n,'image_action','use-files'); _invalidate(n,'image_action')
            else:
                _drop(n,'presentation'); _invalidate(n,'presentation')
            _drop(n,'failure_resolution')
        if key=='image_review' and v=='pause': n['status']='paused'
        if key=='image_review' and v=='edit':
            if n['task_mode']=='edit-existing':
                _set_option(n,'edit_target',n['assets'][0]['inspection']['path'])
            _drop(n,'edit_slot','edit_instruction')
    return _finish(n)

def apply_change(s,key,v,expected_revision):
    _revision(s,expected_revision)
    normalized=normalize_option(key,v)
    if key.startswith(('caption:','alt:')):
        ident=key.split(':',1)[1]
        if ident not in [a['slot_id'] for a in s['assets']]: raise WizardError('unknown metadata slot')
        n=copy.deepcopy(s)
        if key.startswith('caption:'):
            asset=next(a for a in n['assets'] if a['slot_id']==ident)
            if asset.get('caption','')==normalized: return n
            asset['caption']=normalized
        else:
            if next(x for x in s['slot_selection']['slots'] if x['id']==ident).get('alt')==normalized: return n
            _set_option(n,key,v)
        n['completion']=None; return _finish(n)
    if value(s,key)==normalized: return copy.deepcopy(s)
    n=copy.deepcopy(s); _set_option(n,key,v)
    # Moving a not-yet-planned reference to a verified local copy keeps slots.
    if not (key=='reference_path' and s['image_plan'] is None): _invalidate(n,key)
    if key=='image_review' and normalized=='edit':
        if n['task_mode']=='edit-existing': _set_option(n,'edit_target',n['assets'][0]['inspection']['path'])
        _drop(n,'edit_slot','edit_instruction')
    if key=='image_review' and normalized=='pause': n['status']='paused'
    return _finish(n)

def apply_control(s,control,expected_revision):
    _revision(s,expected_revision)
    if control not in {'pause','resume'}: raise WizardError('invalid control')
    status='paused' if control=='pause' else 'active'
    if s['status']==status: return copy.deepcopy(s)
    n=copy.deepcopy(s); n['status']=status; return _finish(n)

def _fields(p,required,optional=()):
    if not isinstance(p,dict) or set(p)-set(required)-set(optional) or set(required)-set(p): raise WizardError('invalid record payload')

def record_event(s,event,expected_revision):
    _revision(s,expected_revision)
    _fields(event,{'type','payload'})
    import wizard_artifacts as a
    kind=event['type']; p=event['payload']; n=copy.deepcopy(s)
    step=next_step(s); action=step.get('action')
    repair=action=='repair_artifacts'
    if kind=='repair':
        _fields(p,{'target'},{'slot_id'})
        if not repair: raise WizardError('no invalid artifacts to repair')
        if s['effect'] and s['effect']['status']=='intent': raise WizardError('resolve uncertain tool result before invalidating it')
        target=p['target']; root=a.run_root(s)
        if target=='asset':
            asset=next((x for x in s['assets'] if x['slot_id']==p.get('slot_id')),None)
            if not asset: raise WizardError('unknown repair slot')
            try: a.verify_asset(asset['inspection'],root)
            except (ValueError,OSError): pass
            else: raise WizardError('asset bytes are valid; use image edit instead')
            n['assets']=[x for x in n['assets'] if x['slot_id']!=p['slot_id']]
            n['effect']=None; n['completion']=None; _drop(n,'image_review')
        elif target in {'article','slots','plan','package'}:
            field={'article':'article','slots':'slot_selection','plan':'image_plan','package':'completion'}[target]
            if not s[field]: raise WizardError('repair record is missing')
            n[field]=None; n['completion']=None
            if target=='article':
                n['slot_selection']=None; n['image_plan']=None; _drop(n,'article_review')
            if target=='slots': n['image_plan']=None
            if target in {'article','slots','plan'}:
                n['effect']=None; _drop(n,'image_plan_review','image_review')
        else: raise WizardError('unsupported repair target')
    elif kind=='article':
        _fields(p,{'path'},{'profile_path'})
        if not repair and action not in {'write_article','rewrite_article','use_source_article'}: raise WizardError('article not expected')
        n['article']=a.register_article(p['path'],a.run_root(s),p.get('profile_path'))
        if value(s,'tone')=='profile' and not n['article'].get('profile'): raise WizardError('profile snapshot required')
        n['slot_selection']=None; n['image_plan']=None; n['completion']=None
        _drop(n,'article_review','image_plan_review','image_review')
        if n['task_mode']=='images-only': _set_option(n,'article_review','use','initial-request')
    elif kind=='slots':
        _fields(p,{'article_path','slots_path'})
        if not repair and action not in {'design_slots','revise_slot_plan','revise_slot_metadata'}: raise WizardError('slots not expected')
        slots_data=a.read_json(a.local_path(p['slots_path'],a.run_root(s)))
        _fields(slots_data,{'slots'})
        slots=slots_data['slots']
        if len(slots)!=value(s,'requested_count'): raise WizardError('slot count must match N','SLOT_SHORTAGE')
        if action=='revise_slot_plan':
            old=s['slot_selection']['slots']; target=value(s,'edit_slot'); instruction=value(s,'edit_instruction')
            for oldslot,newslot in zip(old,slots):
                if oldslot['id']!=newslot['id'] or (oldslot['id']!=target and oldslot!=newslot): raise WizardError('edit changed other slots')
                if oldslot['id']==target and instruction not in newslot['prompt']: raise WizardError('edit instruction missing from slot')
        if action=='revise_slot_metadata':
            target=step['slot_id']
            for before,after in zip(s['slot_selection']['slots'],slots):
                expected={**before,'alt':step['alt']} if before['id']==target else before
                if after!=expected: raise WizardError('metadata update changed other slot fields')
        n['slot_selection']=a.validate_slot_article(s['article']['path'],p['article_path'],slots,a.run_root(s))
        n['slot_selection']['slots_path']=str(a.local_path(p['slots_path'],a.run_root(s)))
        n['slot_selection']['slots_sha256']=a.file_sha(n['slot_selection']['slots_path'])
        if action=='revise_slot_metadata':
            for asset in n['assets']:
                if asset['slot_id']==step['slot_id']: asset['qa']=None
        if value(s,'edit_instruction'): n['slot_selection']['edit_instruction']=value(s,'edit_instruction')
        n['image_plan']=None; n['completion']=None; _drop(n,'image_plan_review','image_review')
    elif kind=='plan':
        _fields(p,{'request_path','plan_path'})
        if not repair and action!='prepare_plan': raise WizardError('plan not expected')
        n['image_plan']=a.register_plan(s,p); n['completion']=None; n['effect']=None
        _drop(n,'image_plan_review','image_review')
    elif kind=='effect-intent':
        _fields(p,{'slot_id'},{'tool_prompt'})
        if action not in {'generate_image','edit_image','repair_image'} or p['slot_id']!=step['slot_id']: raise WizardError('effect not expected')
        staged=None
        if s['task_mode']=='edit-existing':
            staged=a.stage_edit_target(n)
            # Preserve the user's original path and origin while normalizing the
            # executable path in this same locked/CAS state transition.
            n['confirmed_options']['edit_target']={**n['confirmed_options']['edit_target'],'value':staged['path']}
        n['effect']=a.prepare_effect(n,step,p.get('tool_prompt'))
        if staged and (n['effect'].get('target')!=staged or n['effect']['binding']['reference_sha256']!=staged['sha256']):
            raise WizardError('edit target changed while recording intent','ASSET_CHANGED')
    elif kind=='effect-result':
        _fields(p,{'slot_id'},{'path','provenance','effect_id','tool_result','failed'})
        effect=s['effect']
        if p.get('failed') is not None and not isinstance(p['failed'],bool): raise WizardError('failed must be bool')
        if p.get('provenance')!='user-file' or p.get('failed'):
            if not effect or effect['status']!='intent' or effect['id']!=p.get('effect_id') or effect['slot_id']!=p['slot_id']: raise WizardError('effect binding mismatch')
            if not isinstance(p.get('tool_result'),str) or not p['tool_result'].strip(): raise WizardError('actual tool result record required')
            if p.get('failed'):
                n['effect']['status']='failed'; n['effect']['tool_result']=p['tool_result']; return _finish(n)
            expected='generated' if effect['action']=='generate_image' else 'edited'
            if p.get('provenance')!=expected: raise WizardError('wrong result provenance')
        elif action!='import_image' or p['slot_id']!=step['slot_id']: raise WizardError('user image not expected')
        asset=a.bind_asset(s,p['slot_id'],p.get('path'),p.get('provenance'))
        previous=next((x for x in n['assets'] if x['slot_id']==p['slot_id']),None)
        asset['corrections']=(previous or {}).get('corrections',0) if previous and previous.get('binding')==asset['binding'] else 0
        asset['corrections']+=(1 if effect and effect['action']=='repair_image' else 0)
        if effect:
            asset['effect']={**effect,'status':'result-recorded','tool_result':p.get('tool_result')}
            n['effect']={**asset['effect']}
        n['assets']=[asset if x['slot_id']==p['slot_id'] else x for x in n['assets']] if previous else n['assets']+[asset]
        n['completion']=None; _drop(n,'image_review','edit_slot')
        if n['task_mode']!='edit-existing': _drop(n,'edit_instruction')
    elif kind=='visual-review':
        _fields(p,{'slot_id','asset_sha256','passed','notes'})
        if action!='visual_review' or p['slot_id']!=step['slot_id']: raise WizardError('review not expected')
        if not isinstance(p['passed'],bool) or not isinstance(p['notes'],str) or not p['notes'].strip(): raise WizardError('observed QA notes and bool required')
        asset=next(x for x in n['assets'] if x['slot_id']==p['slot_id'])
        if p['asset_sha256']!=asset['inspection']['sha256']: raise WizardError('QA asset mismatch','ASSET_CHANGED')
        asset['qa']={'asset_sha256':p['asset_sha256'],'passed':p['passed'],'notes':p['notes']}
        n['completion']=None
    elif kind=='package':
        _fields(p,{'manifest_path','composed_article_path','completion_path'})
        if not repair and action!='compose_article': raise WizardError('composition not expected')
        n['completion']=a.register_package(s,p)
    else: raise WizardError('unknown record type')
    return _finish(n)

def _atomic_save(path,s):
    fd,name=tempfile.mkstemp(prefix='.wizard-state-',dir=path.parent)
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as stream:
            json.dump(s,stream,ensure_ascii=False,indent=2,allow_nan=False); stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
        os.replace(name,path)
    finally: Path(name).unlink(missing_ok=True)

def session_path(path):
    p=Path(path).expanduser()
    if '..' in p.parts or any(x.is_symlink() for x in (p,*p.parents)): raise WizardError('unsafe session path','UNSAFE_PATH')
    return p.resolve()

def load_session(path):
    path=session_path(path); s=validate_session(read_json(path))
    if path!=Path(s['work_root'])/s['run_root']/'session.json': raise WizardError('session path and declared workspace differ','UNSAFE_PATH')
    return s

def update_session(path,expected_revision,mutation):
    path=session_path(path); lock=path.with_name(path.name+'.lock'); owned=False
    guard=path.with_name(path.name+'.guard')
    if lock.is_symlink() or guard.is_symlink(): raise WizardError('unsafe lock path','UNSAFE_PATH')
    guard_fd=os.open(guard,os.O_RDWR|os.O_CREAT|getattr(os,'O_NOFOLLOW',0),0o600)
    try:
        try: fcntl.flock(guard_fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError: raise WizardError('another writer is active','SESSION_BUSY')
        for attempt in range(2):
            try:
                fd=os.open(lock,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                owned=True
                with os.fdopen(fd,'w') as stream: stream.write(str(os.getpid()))
                break
            except FileExistsError:
                try:
                    pid=int(lock.read_text()); os.kill(pid,0)
                except ProcessLookupError:
                    if attempt==0: lock.unlink(); continue
                except (ValueError,OSError,OverflowError): pass
                raise WizardError('session writer is active or unknown','SESSION_BUSY')
        s=load_session(path); _revision(s,expected_revision)
        new=validate_session(mutation(s))
        if new!=s: _atomic_save(path,new)
        return new
    finally:
        if owned: lock.unlink(missing_ok=True)
        os.close(guard_fd)

def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__); sub=parser.add_subparsers(dest='command',required=True)
    init=sub.add_parser('init'); init.add_argument('--work-root',required=True); init.add_argument('--initial-options')
    for cmd in ('next','status','answer','change','record','pause','resume'):
        p=sub.add_parser(cmd); p.add_argument('--session',required=True)
        if cmd not in {'next','status'}: p.add_argument('--expected-revision',required=True,type=int)
        if cmd=='answer': p.add_argument('--question-id',required=True); p.add_argument('--value-json',required=True)
        if cmd=='change': p.add_argument('--key',required=True); p.add_argument('--value-json',required=True)
        if cmd=='record': p.add_argument('--type',required=True); p.add_argument('--payload',required=True)
    args=parser.parse_args(argv)
    try:
        if args.command=='init':
            s=new_session(args.work_root,read_json(args.initial_options) if args.initial_options else None)
            path=Path(s['work_root'])/s['run_root']/'session.json'; path.parent.mkdir(parents=True,exist_ok=False)
            _atomic_save(path,s); result={'session':str(path),'state':s,'step':next_step(s)}
        else:
            path=session_path(args.session)
            if args.command in {'next','status'}:
                s=load_session(path); result=next_step(s) if args.command=='next' else {'state':s,'step':next_step(s)}
            else:
                def mutate(s):
                    if args.command=='answer': return apply_answer(s,args.question_id,json.loads(args.value_json),args.expected_revision)
                    if args.command=='change': return apply_change(s,args.key,json.loads(args.value_json),args.expected_revision)
                    if args.command=='record': return record_event(s,{'type':args.type,'payload':read_json(args.payload)},args.expected_revision)
                    return apply_control(s,args.command,args.expected_revision)
                s=update_session(path,args.expected_revision,mutate); result={'state':s,'step':next_step(s)}
        print(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False))
        step=result.get('step',result)
        return 1 if step.get('action')=='repair_artifacts' else 0
    except (WizardError,OSError,ValueError,TypeError,KeyError) as exc:
        print(json.dumps({'code':getattr(exc,'code','INVALID_INPUT'),'message':str(exc)},ensure_ascii=False),file=sys.stderr); return 2

if __name__=='__main__': raise SystemExit(main())
