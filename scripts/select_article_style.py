#!/usr/bin/env python3
"""Resolve a writing structure, not a voice, fact check, image template or UI action.

The current agent may supply a semantic intent with a reason. Title patterns are
only a deterministic fallback; they cannot establish experience or credentials.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
import re

SCHEMA = 'naver-article-style/v1'
_UNSET = object()
# article type -> existing series profiles, existing image adapter type, outline
RECIPES = {
    'information': ('expert', 'friendly', 'information', ['먼저 답하기', '항목별 정보와 조건', '예외와 확인 방법', '핵심 정리']),
    'expert': ('expert', 'friendly', 'information', ['핵심 질문', '근거와 작동 원리', '해석과 적용 범위', '한계와 확인 사항']),
    'comparison': ('comparison', 'friendly', 'comparison', ['같은 비교 조건', '공통 평가 축의 실제 표', '상황별 차이', '독자별 선택 기준']),
    'howto': ('friendly', 'expert', 'howto', ['완료 목표와 준비물', '순서별 실행', '단계별 확인과 예외', '완료 체크']),
    'troubleshooting': ('troubleshooting', 'friendly', 'howto', ['증상과 중단 조건', '가능 원인과 진단', '안전한 조치 순서', '재확인과 도움 조건']),
    'review': ('review', 'friendly', 'review', ['사용 조건과 기간', '제공된 실제 관찰', '장점과 불편', '사양과 경험 구분', '맞는 사람과 한계']),
    'place': ('review', 'friendly', 'place', ['방문 일시와 조건', '실제 방문 동선', '관찰과 공식 정보 구분', '불편과 방문 전 확인']),
    'story': ('story', 'friendly', 'story', ['구체적 상황', '전환점과 선택', '결과', '독자에게 적용할 교훈']),
    'checklist': ('friendly', 'expert', 'checklist', ['확인 목적', '우선 확인 항목', '항목별 판단과 조치', '마지막 점검']),
}
ARTICLE_TYPES = frozenset(RECIPES)
STYLE_CHECKS = {
    'information': ['항목별 적용 조건', '확인 시점과 공식 근거'],
    'expert': ['주장과 원문 근거 연결', '한계·반례·불확실성', '전문가 자격 사칭 금지'],
    'comparison': ['동일 평가 축의 대칭 비교', '근거 없는 종합 승자 금지'],
    'howto': ['준비→실행→확인 순서', '예외·실패 시 다음 행동'],
    'troubleshooting': ['증상→원인 후보→확인→조치 연결', '중단·전문가 도움 조건'],
    'review': ['실제 경험 근거', '직접 관찰과 사양 분리'],
    'place': ['실제 방문 근거', '방문 시점·동선과 공식 정보 분리'],
    'story': ['실제 경험 또는 공개적으로 표시한 가정', '변화와 교훈 연결'],
    'checklist': ['체크 항목마다 판단·조치', '우선순위와 적용 조건'],
}


class StyleError(ValueError):
    def __init__(self, message, code='INVALID_STYLE_SELECTION'):
        super().__init__(message)
        self.code = code


def _text(value, label):
    if not isinstance(value, str) or not value.strip() or '\x00' in value:
        raise StyleError(f'{label}: nonempty text required')
    return value


def normalize_basis(basis=None):
    if basis is None:
        return {'type': 'source_based', 'evidence': []}
    if (not isinstance(basis, dict) or set(basis) != {'type', 'evidence'}
            or not isinstance(basis['type'], str)
            or basis['type'] not in {'source_based', 'user_provided', 'verified_records', 'illustrative'}
            or not isinstance(basis['evidence'], list)
            or any(not isinstance(x, str) or not x.strip() for x in basis['evidence'])):
        raise StyleError('structured experience basis required')
    if basis['type'] != 'source_based' and not basis['evidence']:
        raise StyleError('experience/illustration needs concrete evidence or scenario notes')
    return copy.deepcopy(basis)


def implies_firsthand(title):
    # Reading other people's reviews is not the author's own experience.
    if re.search(r'실사용\s*(?:없이|아닌|대신)|실사용\s*비교\s*대신', title):
        return bool(re.search(r'내돈내산|써\s*보니|사용해\s*보니|다녀|방문해\s*보니', title))
    if re.search(r'(후기|리뷰)(?:를|가|만|는)?\s*(읽|믿|분석|비교|참고|확인|고르|쓰는\s*법|작성법|작성하는\s*법)', title):
        return bool(re.search(r'(직접|내돈내산|써\s*보니|사용해\s*보니|다녀|방문해\s*보니)', title))
    return bool(re.search(r'후기|내돈내산|실사용|사용해\s*보니|써\s*보니|다녀|방문기|방문해\s*보니|체험기', title))


def infer_intent(title):
    """Fallback hints only; semantic intent is supplied separately by the agent."""
    if implies_firsthand(title):
        return ('place' if re.search(r'방문|다녀|여행|맛집', title) else 'review'), '제목이 실제 사용·방문 관찰을 약속함'
    if re.search(r'오류|고장|작동.*않|안\s*(켜|되|나오)|해결|복구|먹통', title):
        return 'troubleshooting', '증상에서 확인·조치로 이어지는 질문'
    if re.search(r'\bvs\b|차이|비교|어느\s*쪽|뭐가\s*(더|다를)|무엇이\s*다를', title, re.I):
        return 'comparison', '대상 간 차이와 선택을 묻는 제목'
    if re.search(r'체크리스트|점검|확인할|놓치.*않|챙길', title):
        return 'checklist', '행동 전에 확인할 항목을 약속함'
    if re.search(r'신청|설치|등록|개통|바르는|보관|대피|보내|쓰는\s*순서|이용\s*방법|단계|순서', title):
        return 'howto', '준비·행동·완료 확인이 필요한 제목'
    if re.search(r'연구|근거|원리|왜|이유|정말|의미|전문|분석', title):
        return 'expert', '근거와 해석·한계를 설명해야 하는 질문'
    if re.search(r'시행착오|도전기|변화.*과정|실패.*배운', title):
        return 'story', '경과와 선택·변화가 중심인 제목'
    return 'information', '정보와 적용 조건을 먼저 정리하는 보수적 기본 구조'


def select_style(title, *, requested_type='auto', intent=None, experience_basis=None):
    _text(title, 'title')
    if not isinstance(requested_type, str) or requested_type not in ARTICLE_TYPES | {'auto'}:
        raise StyleError('unsupported requested article type')
    basis = normalize_basis(experience_basis)
    if intent is not None:
        if (not isinstance(intent, dict) or set(intent) != {'article_type', 'reason'}
                or not isinstance(intent['article_type'], str)
                or intent['article_type'] not in ARTICLE_TYPES):
            raise StyleError('semantic intent needs article_type and reason')
        _text(intent['reason'], 'semantic reason')
    if requested_type != 'auto':
        chosen, reason, method = requested_type, '이번 요청의 명시 글 유형을 우선 적용', 'explicit'
    elif intent is not None:
        chosen, reason, method = intent['article_type'], intent['reason'], 'semantic'
    else:
        chosen, reason = infer_intent(title)
        method = 'title_hint'

    firsthand = basis['type'] in {'user_provided', 'verified_records'} and bool(basis['evidence'])
    status = 'ready'
    if chosen in {'review', 'place'} and not firsthand:
        status = 'needs_experience'
    elif implies_firsthand(title) and not firsthand:
        status = 'needs_title_revision'
    elif chosen == 'story' and not firsthand and basis['type'] != 'illustrative':
        status = 'needs_experience'
    primary, secondary, image_type, outline = RECIPES[chosen]
    return {
        'schema': SCHEMA, 'title': title,
        'title_sha256': hashlib.sha256(title.encode('utf-8')).hexdigest(),
        'requested_type': requested_type, 'intent': copy.deepcopy(intent),
        'experience_basis': basis, 'method': method, 'article_type': chosen,
        'primary_style': primary, 'secondary_style': secondary,
        'image_article_type': image_type, 'status': status, 'reason': reason,
        'outline': list(outline), 'required_checks': list(STYLE_CHECKS[chosen]),
    }


def validate_selection(record, title, *, experience_basis=_UNSET, require_ready=True, require_semantic=False):
    if not isinstance(record, dict) or record.get('schema') != SCHEMA or record.get('title') != title:
        raise StyleError('style selection does not match the final title', 'STALE_STYLE_SELECTION')
    fresh = select_style(title, requested_type=record.get('requested_type'),
                         intent=record.get('intent'), experience_basis=record.get('experience_basis'))
    if record != fresh:
        raise StyleError('style selection differs from its inputs')
    if experience_basis is not _UNSET and fresh['experience_basis'] != normalize_basis(experience_basis):
        raise StyleError('style selection and editorial experience basis disagree')
    if require_semantic and fresh['method'] == 'title_hint':
        raise StyleError('final automatic selection needs a semantic intent and reason', 'STYLE_INTENT_REQUIRED')
    if require_ready and fresh['status'] != 'ready':
        raise StyleError('experience evidence or an honest title is required', fresh['status'].upper())
    return fresh


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--title')
    group.add_argument('--request', type=Path, help='JSON title/requested_type/intent/experience_basis')
    parser.add_argument('--type', default='auto', choices=sorted(ARTICLE_TYPES | {'auto'}))
    args = parser.parse_args(argv)
    try:
        if args.request:
            def pairs(items):
                result = {}
                for key, value in items:
                    if key in result: raise StyleError('duplicate JSON key')
                    result[key] = value
                return result
            request = json.loads(args.request.read_text(encoding='utf-8'), object_pairs_hook=pairs)
            if not isinstance(request, dict) or 'title' not in request or set(request) - {'title', 'requested_type', 'intent', 'experience_basis'}:
                raise StyleError('unsupported request fields')
        else:
            request = {'title': args.title, 'requested_type': args.type}
        result = select_style(**request)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result['status'] == 'ready' else 1
    except (StyleError, OSError, ValueError) as exc:
        print(json.dumps({'error': str(exc), 'code': getattr(exc, 'code', 'INVALID_STYLE_SELECTION')}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
