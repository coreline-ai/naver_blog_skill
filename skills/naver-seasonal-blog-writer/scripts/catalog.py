#!/usr/bin/env python3
"""Self-contained seasonal catalog. Python standard library only."""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "seasonal-catalog/v1"
NAMES = {"월별_시즌키워드.xlsx": "A", "홈페이지_1월-12월_시즌키워드_523개.xlsx": "B"}


class CatalogError(ValueError):
    pass


def normalized(text):
    if not isinstance(text, str) or not text.strip():
        raise CatalogError("키워드는 비어 있지 않은 문자열이어야 합니다")
    return re.sub(r"\s+", "", unicodedata.normalize("NFC", text))


def ident(prefix, text):
    return prefix + hashlib.sha256(text.encode("utf-8")).hexdigest()[:20]


def json_text(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CatalogError(f"JSON 입력을 읽을 수 없습니다: {path}: {exc}") from exc


def domain(topic):
    for label, words in [
        ("세금·연금", ["연말정산", "소득세", "자동차세", "재산세", "주민세", "연금저축", "IRP", "세금", "부가가치세"]),
        ("복지·교육지원", ["장려금", "장학금", "학자금", "학비", "교육비", "교육급여", "청년지원", "지원금", "문화누리", "바우처"]),
        ("건강·안전", ["한파", "한랭", "건강", "폭염", "식생활", "독감", "코로나", "미세먼지"]),
        ("여행·축제", ["축제", "여행", "스키장", "단풍", "캠핑", "계곡", "워터파크", "해수욕장", "물놀이", "핑크뮬리", "봄꽃", "해돋이", "산행"]),
    ]:
        if any(word in topic for word in words):
            return label
    return "생활·기념일"


def inspect_phrase(keyword, source, month, topic):
    flags = []
    if keyword in ("연금저축 연금저축 차이", "IRP IRP 차이"):
        flags.append("자기비교 문구")
    if "재산세" in keyword and any(x in keyword for x in ("중고차", "차량매도", "차량구매", "폐차")):
        flags.append("세목·대상 혼입")
    if re.fullmatch(r"(?:\d+월 )?(?:재산세|자동차세) (?:신청기간|신청방법|신청취소)", keyword):
        flags.append("신청·납부 의도 재확인")
    if keyword in ("종합소득세 청첩장 청년창업감면", "종합소득세 천만원 체납 출산공제", "종소세 탕감 타인납부 통장압류", "종합소득세 복식부기 부양가족 분납"):
        flags.append("서로 다른 문제 결합")
    if source == "A" and month == 0:
        flags.append("지원사업명 미특정")
    if source == "A" and "축제" in topic:
        flags.append("행사명 구체화 필요")
    return flags


def editorial_key(keyword):
    """Conservative, explainable aliases. Never strip years, rounds or places."""
    key = normalized(keyword)
    # Only these equivalent terminal expressions are merged, with the entire
    # preceding subject retained. Company refunds and national refunds stay apart.
    for pattern, replacement, reason in [
        (r"^(.*환급금)(?:언제|지급일|입금일|지급시간)$", r"\1지급일", "같은 대상의 환급 시점 질문"),
        (r"^(.*축제)(?:일정|기간|날짜)$", r"\1일정", "같은 행사의 기본 일정"),
        (r"^(.+)주차장$", r"\1주차", "같은 대상의 주차 안내"),
    ]:
        if re.fullmatch(pattern, key):
            return re.sub(pattern, replacement, key), reason
    explicit = [
        ["연말정산 미리보기", "연말정산 미리보기 조회방법", "홈택스 연말정산 미리보기"],
        ["연말정산 의료비 누락 조회", "연말정산 의료비 누락", "연말정산 간소화 의료비 누락"],
        ["연말정산 부양가족 자료제공동의", "연말정산 부양가족 자료제공 동의"],
        ["교육급여 교육비 지원 차이", "교육급여와 교육비 차이"],
        ["연금저축 IRP 차이", "IRP 연금저축 차이"],
        ["종합소득세 환급금 조회", "종소세 환급금 조회", "홈택스 종소세 환급금 조회"],
        ["연말정산 필요서류", "연말정산 준비서류", "연말정산 필요서류 미리 준비"],
    ]
    for group in explicit:
        if key in {normalized(x) for x in group}:
            return normalized(group[0]), "편집 검토한 동일 질문의 별칭"
    return key, "원문별 보수적 분리; 최종 추천 전 의미 검토"


def scope_kind(text):
    if "연말정산" in text:
        return "settlement"
    if "장려금" in text and "반기" in text:
        return "grant-half"
    if any(x in text for x in ("장학금", "학자금")):
        return "academic-term"
    if "종합소득세" in text or "종소세" in text:
        return "income-tax"
    if "재산세" in text or ("자동차세" in text and "연납" not in text):
        return "bill-round"
    if any(x in text for x in ("장려금", "자동차세 연납", "예방접종", "무료접종", "바우처", "축제")):
        return "annual"
    return "evergreen"


def extract(snapshot):
    rows = []
    if not isinstance(snapshot, list) or len(snapshot) != 2:
        raise CatalogError("두 원본의 시트 스냅샷이 필요합니다")
    seen_books = set()
    for book in snapshot:
        name = unicodedata.normalize("NFC", book["name"])
        source = NAMES.get(name)
        if not source or source in seen_books:
            raise CatalogError("원본 파일 구성이 올바르지 않습니다")
        seen_books.add(source)
        for sheet in book["sheets"]:
            sn = sheet["name"]
            if not ((source == "A" and (re.fullmatch(r"\d+월", sn) or sn == "기타")) or (source == "B" and sn == "전체 키워드")):
                continue
            for row in sheet["rows"]:
                n, cells = row["row"], row["cells"]
                if n == 1 or not cells.get(f"C{n}"):
                    continue
                keyword = cells[f"C{n}"]
                month = (0 if sn == "기타" else int(sn[:-1])) if source == "A" else cells[f"A{n}"]
                if type(month) is not int or not 0 <= month <= 12:
                    raise CatalogError("원본 월 값이 올바르지 않습니다")
                topic = cells.get(f"B{n}", "")
                source_date = cells.get(f"F{n}", "") if source == "B" else ""
                # Year-specific editorial snapshots are not silently rolled forward.
                years = [2026] if re.search(r"20\d{2}", keyword) or (source == "B" and re.search(r"20\d{2}", topic)) else []
                rows.append({"keyword": keyword, "source": source, "filename": name, "sheet": sn, "row": n, "month": month, "topic": topic,
                             "domain": domain(topic), "flags": inspect_phrase(keyword, source, month, topic),
                             "source_date": source_date, "timing": cells.get(f"D{n}", "") if source == "B" else "",
                             "urls": cells.get(f"I{n}", "").splitlines() if source == "B" else [],
                             "publication_years": years, "historical_until": "2026-10-02" if "10월 1일 2일 신청 일시 중단" in keyword else None})
    return rows


def build(snapshot_path, editorial_path=None):
    raw = extract(read_json(snapshot_path))
    groups = collections.defaultdict(list)
    for row in raw:
        groups[normalized(row["keyword"])].append(row)
    curated = collections.defaultdict(list)
    if editorial_path:
        for item in read_json(editorial_path)["candidates"]:
            if normalized(item["keyword"]) not in groups:
                raise CatalogError("편집 후보가 원본에 없습니다")
            curated[normalized(item["keyword"])].append({k: item[k] for k in ("month", "title", "why", "timing", "check")})
    keywords, topics = [], {}
    for key, sources in sorted(groups.items()):
        aliases = sorted({r["keyword"] for r in sources})
        representative = min(aliases, key=lambda x: (len(x), x))
        tkey, reason = editorial_key(representative)
        kid, tid = ident("kw-", key), ident("topic-", tkey)
        reasons = sorted({f for r in sources for f in r["flags"]})
        months = sorted({r["month"] for r in sources if r["month"]})
        entries = [dict({k: r[k] for k in ("source", "filename", "sheet", "row", "month", "topic", "source_date", "timing", "urls", "publication_years", "historical_until")}, original_keyword=r["keyword"]) for r in sources]
        entries.sort(key=lambda x: (x["source"], x["month"], x["sheet"], x["row"]))
        record = {"id": kid, "keyword": representative, "normalized": key, "aliases": aliases, "months": months,
                  "domains": sorted({r["domain"] for r in sources}), "topic_id": tid,
                  "status": "needs_review" if reasons else "candidate", "review_reasons": reasons, "sources": entries,
                  "warnings": (["개별 입금시각 단정 금지"] if "지급시간" in key else []) + (["절기별 백신 종류 확인"] if "독감4가백신" == key else []),
                  "editorial": curated[key]}
        keywords.append(record)
        topic = topics.setdefault(tid, {"id": tid, "question": tkey, "keyword_ids": [], "months": set(), "domains": set(), "scope_kind": scope_kind(tkey), "grouping_basis": reason})
        topic["keyword_ids"].append(kid)
        topic["months"].update(months)
        topic["domains"].update(record["domains"])
    for t in topics.values():
        for field in ("keyword_ids", "months", "domains"):
            t[field] = sorted(t[field])
    result = {"keywords": keywords, "topics": sorted(topics.values(), key=lambda x: x["id"])}
    stats = {"source_rows": len(raw), "by_source": dict(sorted(collections.Counter(x["source"] for x in raw).items())),
             "exact_unique": len({x["keyword"] for x in raw}), "normalized_unique": len(keywords), "topics": len(topics),
             "candidate_keywords": sum(x["status"] == "candidate" for x in keywords), "review_keywords": sum(x["status"] == "needs_review" for x in keywords),
             "source_month_rows": {s: {str(m): sum(r["source"] == s and r["month"] == m for r in raw) for m in range(13)} for s in ("A", "B")}}
    result["manifest"] = {"schema": VERSION, "data_as_of": "2026-10-19", "input_type": "worksheet_snapshot", "snapshot_sha256": hashlib.sha256(Path(snapshot_path).read_bytes()).hexdigest(),
                          "original_workbook_bytes_verified": False, "source_files": sorted(NAMES), "normalization": "NFC + whitespace removal; numbers/punctuation retained",
                          "semantic_review": "보수적 별칭 규칙만 적용; 최종 추천에서 에이전트 의미 검토 필요", "original_summary_discrepancy": {"A_month_summary": 2568, "A_month_detail": 2485, "difference": -83}, "stats": stats}
    return result


def validate_data(keywords, topics, manifest):
    kids, tids = {k["id"] for k in keywords}, {t["id"] for t in topics}
    if len(kids) != len(keywords) or len(tids) != len(topics) or len({k["normalized"] for k in keywords}) != len(keywords):
        raise CatalogError("중복 ID/정규화 문구")
    index = {k["id"]: k for k in keywords}
    assigned = []
    for t in topics:
        if t["id"] != ident("topic-", t["question"]) or t["scope_kind"] != scope_kind(t["question"]):
            raise CatalogError("주제 ID/회차 분류 불일치")
        for kid in t["keyword_ids"]:
            if kid not in kids or index[kid]["topic_id"] != t["id"]:
                raise CatalogError("주제 연결 불일치")
            assigned.append(kid)
    if collections.Counter(assigned) != collections.Counter(kids):
        raise CatalogError("누락/중복 주제 배정")
    lineage, original = [], []
    for k in keywords:
        if k["id"] != ident("kw-", normalized(k["keyword"])) or k["normalized"] != normalized(k["keyword"]):
            raise CatalogError("키워드 ID/문구 불일치")
        if not k["sources"] or k["status"] not in ("candidate", "needs_review"):
            raise CatalogError("출처/검토 상태 오류")
        if k["months"] != sorted({s["month"] for s in k["sources"] if s["month"]}):
            raise CatalogError("적용 월 누락")
        lineage.extend((s["source"], s["sheet"], s["row"]) for s in k["sources"])
        for s in k["sources"]:
            if normalized(s["original_keyword"]) != k["normalized"]:
                raise CatalogError("원문 출처와 정규화 문구 불일치")
            original.append(s["original_keyword"])
    if len(lineage) != len(set(lineage)) or len(lineage) != manifest["stats"]["source_rows"]:
        raise CatalogError("출처 행 중복/누락")
    if len(keywords) != manifest["stats"]["normalized_unique"] or len(topics) != manifest["stats"]["topics"]:
        raise CatalogError("manifest 집계 불일치")
    if len(set(original)) != manifest["stats"]["exact_unique"]:
        raise CatalogError("완전일치 집계 불일치")
    return manifest["stats"]


def load(data_dir=None):
    directory = Path(data_dir) if data_dir else ROOT / "data"
    try:
        keywords = [json.loads(x) for x in (directory / "keywords.jsonl").read_text(encoding="utf-8").splitlines() if x]
        topics = [json.loads(x) for x in (directory / "topics.jsonl").read_text(encoding="utf-8").splitlines() if x]
        manifest = read_json(directory / "source-manifest.json")
    except (OSError, ValueError) as exc:
        raise CatalogError(f"카탈로그 읽기 실패: {exc}") from exc
    validate_data(keywords, topics, manifest)
    return keywords, topics, manifest


def save_build(result, out):
    directory = Path(out)
    if directory.exists() and any(directory.iterdir()):
        raise CatalogError("기존 데이터 폴더를 덮어쓰지 않습니다")
    validate_data(result["keywords"], result["topics"], result["manifest"])
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("keywords", "topics"):
        (directory / f"{name}.jsonl").write_text("".join(json_text(x) + "\n" for x in result[name]), encoding="utf-8")
    (directory / "source-manifest.json").write_text(json_text(result["manifest"]) + "\n", encoding="utf-8")


def occurrence(topic, year, month, period=None):
    date(year, month, 1)
    if period is not None:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,63}", period):
            raise CatalogError("period 형식 오류")
        return topic["id"] + ":explicit:" + period
    kind, question = topic["scope_kind"], topic["question"]
    if kind == "settlement": value = f"tax:{year - 1 if month <= 2 else year}"
    elif kind == "income-tax": value = f"income:{year-1}"
    elif kind == "grant-half": value = f"income:{year-1}-H2" if month <= 6 else f"income:{year}-H1"
    elif kind == "academic-term":
        academic_year = year + 1 if month >= 11 else year
        term = 1 if month in (1, 2, 3, 11, 12) else 2
        explicit_term = re.search(r"([12])학기", question)
        if explicit_term: term = int(explicit_term.group(1))
        round_match = re.search(r"([12])차", question)
        value = f"academic:{academic_year}-S{term}-R{round_match.group(1) if round_match else 'unspecified'}"
    elif kind == "bill-round": value = f"bill:{year}-{month:02}"
    elif kind == "annual": value = f"year:{year}"
    else: value = "evergreen"
    return topic["id"] + ":" + value


DOMAIN_ALIASES = {"세금": ["세금·연금"], "직장인세금": ["세금·연금"], "연금": ["세금·연금"], "지원": ["복지·교육지원"],
                  "교육": ["복지·교육지원"], "복지": ["복지·교육지원"], "여행": ["여행·축제"], "건강": ["건강·안전"],
                  "생활": ["생활·기념일"], "생활정보": ["생활·기념일", "건강·안전"]}


def recommend(year, month, as_of, count=8, domain_filter=None, workspace=None, blog=None, data_dir=None, period=None, mode="recommend"):
    from history import current, load as history_load
    asof = date.fromisoformat(as_of)
    if type(year) is not int or type(month) is not int or not 1 <= month <= 12 or year < 2 or year > 9998:
        raise CatalogError("연도(2~9998)와 월(1~12)을 확인하세요")
    if type(count) is not int or count <= 0:
        raise CatalogError("count는 양의 정수입니다")
    if bool(workspace) != bool(blog): raise CatalogError("workspace와 blog를 함께 지정하세요")
    if mode not in ("recommend", "plan"): raise CatalogError("추천 모드 오류")
    keywords, topics, manifest = load(data_dir)
    domains = sorted({d for k in keywords for d in k["domains"]})
    selected_domains = DOMAIN_ALIASES.get(domain_filter, [domain_filter]) if domain_filter else domains
    if any(d not in domains for d in selected_domains): raise CatalogError("분야를 확인하세요: " + ", ".join(domains))
    history = history_load(workspace, blog) if workspace else {"revision": 0, "events": []}
    states = current(history)
    ti = {t["id"]: t for t in topics}
    grouped = collections.defaultdict(list)
    reasons = collections.Counter()
    for k in keywords:
        if month not in k["months"] or not set(k["domains"]) & set(selected_domains): continue
        if k["status"] != "candidate": reasons["검토 대기"] += 1; continue
        eligible = [s for s in k["sources"] if s["month"] == month and (not s["publication_years"] or year in s["publication_years"]) and (not s["historical_until"] or asof <= date.fromisoformat(s["historical_until"]))]
        if not eligible: reasons["연도/과거 공지 조건 불일치"] += 1; continue
        grouped[k["topic_id"]].append((k, eligible))
    candidates, updates = [], []
    for tid, members in grouped.items():
        def priority(pair):
            k = pair[0]
            return (not any(e["month"] == month for e in k["editorial"]), len(k["warnings"]), k["keyword"])
        members.sort(key=priority)
        k, sources = members[0]; topic = ti[tid]; occ = occurrence(topic, year, month, period)
        prior = states.get(occ)
        if prior and prior["status"] in ("drafted", "selected", "published"):
            reasons["같은 회차 기존 " + prior["status"]] += 1; continue
        editorial = next((e for e in k["editorial"] if e["month"] == month), None)
        candidate = {"topic_id": tid, "keyword_id": k["id"], "keyword": k["keyword"], "domains": k["domains"], "occurrence": occ,
                     "aliases": sorted({a for pair in members for a in pair[0]["aliases"]}), "title_suggestion": editorial["title"] if editorial else k["keyword"],
                     "title_status": "editorial_proposal" if editorial else "agent_title_needed", "reason": editorial["why"] if editorial else "해당 원문 월·분야에 포함된 후보. 독자의 질문과 차별점 검토 필요",
                     "writing_window": editorial["timing"] if editorial else "원문 월은 기획 배치. 해당 연도 실제 일정 확인 필요",
                     "verification_needed": editorial["check"] if editorial else "대상·일정·최신 공식 자료·독자의 질문을 확인",
                     "search_volume": None, "facts_status": "unverified", "semantic_review_required": True,
                     "grouping_basis": topic["grouping_basis"], "warnings": sorted({w for pair in members for w in pair[0]["warnings"]}),
                     "sources": sources, "action": "update" if prior and prior["status"] == "needs_update" else "new", "_curated": bool(editorial)}
        if candidate["action"] == "update": candidate["update_reason"] = prior["payload"]["reason"]; updates.append(candidate)
        else: candidates.append(candidate)
    def ordered(items):
        # Round robin across subjects prevents one source's lexical ordering from
        # filling the list. These are editorial selection rules, not SEO scores.
        buckets = collections.defaultdict(list)
        for item in sorted(items, key=lambda x: (not x["_curated"], len(x["warnings"]), x["keyword"])):
            family = next((f for f in ("연말정산", "연금저축", "IRP", "국가장학금", "근로장려금", "한파", "겨울", "종합소득세") if f in item["keyword"]), item["domains"][0])
            buckets[family].append(item)
        out = []
        while buckets:
            for family in list(buckets):
                item = buckets[family].pop(0); item.pop("_curated"); out.append(item)
                if not buckets[family]: del buckets[family]
        return out
    available = len(candidates)
    result = {"schema": "seasonal-recommendation/v1", "year": year, "month": month, "as_of": as_of, "period": period, "mode": mode,
              "requested_count": count, "available_topics": available, "history_revision": history["revision"], "history_checked": bool(workspace),
              "domains": selected_domains, "candidates": ordered(candidates)[:count], "updates": ordered(updates)[:count], "exclusions": dict(reasons),
              "limitations": ["검색량·경쟁도 미측정", "순서는 편집 기준이며 성과 예측이 아님", "최종 추천 전 의미 중복·사실 검토 필요", "이력 조회 범위는 지정 블로그/작업 공간만 해당" if workspace else "이력 없음: 요청 안의 중복만 제외"],
              "catalog_version": manifest["schema"]}
    if available < count: result["shortfall"] = count - available
    if mode == "plan":
        for i, c in enumerate(result["candidates"], 1): c["sequence"] = i
        result["planning_note"] = "작성 순서 제안. 발행 날짜와 공식 일정은 확정하지 않음"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build"); b.add_argument("--snapshot", required=True); b.add_argument("--editorial"); b.add_argument("--out", required=True)
    v = sub.add_parser("validate"); v.add_argument("--data-dir")
    for command in ("recommend", "plan"):
        r = sub.add_parser(command); r.add_argument("--as-of", help="확인 기준일 YYYY-MM-DD (기본: 실행 환경의 오늘)"); r.add_argument("--year", type=int); r.add_argument("--month", type=int)
        r.add_argument("--count", type=int, default=8); r.add_argument("--domain"); r.add_argument("--workspace"); r.add_argument("--blog"); r.add_argument("--period"); r.add_argument("--data-dir")
    args = parser.parse_args()
    try:
        if args.command == "build":
            result = build(args.snapshot, args.editorial); save_build(result, args.out); output = result["manifest"]
        elif args.command == "validate":
            output = load(args.data_dir)[2]
        else:
            today = date.fromisoformat(args.as_of) if args.as_of is not None else date.today()
            output = recommend(args.year if args.year is not None else today.year, args.month if args.month is not None else today.month, today.isoformat(), args.count, args.domain, args.workspace, args.blog, args.data_dir, args.period, args.command)
        print(json_text(output))
        return 0
    except (CatalogError, KeyError, TypeError, ValueError, OSError) as exc:
        print(json_text({"error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
