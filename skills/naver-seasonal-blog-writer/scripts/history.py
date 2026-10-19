#!/usr/bin/env python3
"""Atomic, blog-scoped local writing history. No network or publishing."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "seasonal-history/v1"
STATUSES = {"recommended", "selected", "drafted", "published", "needs_update"}


class HistoryError(ValueError):
    pass


def workspace_path(workspace):
    path = Path(workspace).expanduser().resolve()
    if path == ROOT or ROOT in path.parents:
        raise HistoryError("사용자 작업 공간은 스킬 폴더 밖이어야 합니다")
    return path


def safe_file(workspace, relative, must_exist=True):
    base = workspace_path(workspace)
    if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise HistoryError("작업 공간 기준 상대 파일 경로가 필요합니다")
    result = (base / relative).resolve()
    if base not in result.parents or result == ROOT or ROOT in result.parents:
        raise HistoryError("작업 공간 밖/스킬 내부 경로는 허용하지 않습니다")
    if must_exist and not result.is_file():
        raise HistoryError("등록할 파일이 없습니다")
    return result


def history_path(workspace, blog):
    if not isinstance(blog, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", blog):
        raise HistoryError("blog는 영문/숫자/_/- 1~64자로 지정하세요")
    return safe_file(workspace, f".seasonal-writer/{blog}/history.json", False)


def artifact_valid(workspace, artifact):
    if not isinstance(artifact, dict) or set(artifact) != {"path", "sha256"}:
        raise HistoryError("원고의 상대 경로와 sha256이 필요합니다")
    path = safe_file(workspace, artifact["path"])
    if hashlib.sha256(path.read_bytes()).hexdigest() != artifact["sha256"]:
        raise HistoryError("원고 내용이 등록된 버전과 달라 재검수가 필요합니다")
    return path


def load(workspace, blog):
    path = history_path(workspace, blog)
    if not path.exists():
        return {"schema": SCHEMA, "blog": blog, "revision": 0, "events": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["schema"] != SCHEMA or data["blog"] != blog or type(data["revision"]) is not int or not isinstance(data["events"], list) or data["revision"] != len(data["events"]):
            raise HistoryError("이력 schema/blog/revision 불일치")
        ids = set()
        for event in data["events"]:
            if not isinstance(event, dict) or not isinstance(event.get("event_id"), str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", event["event_id"]) or event["event_id"] in ids or event["status"] not in STATUSES or not isinstance(event["payload"], dict):
                raise HistoryError("이력 이벤트 오류")
            if not isinstance(event.get("topic_id"), str) or not isinstance(event.get("occurrence"), str) or not event["occurrence"].startswith(event["topic_id"] + ":"):
                raise HistoryError("이력 주제/회차 오류")
            datetime.fromisoformat(event["recorded_at"])
            ids.add(event["event_id"])
            if event["status"] in ("drafted", "published"):
                artifact_valid(workspace, event["payload"]["artifact"])
                for name in ("brief", "editorial", "review"):
                    if name in event["payload"]: artifact_valid(workspace, event["payload"][name])
        return data
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise HistoryError(f"이력을 읽을 수 없습니다. 기존 파일을 보존합니다: {exc}") from exc


def current(data):
    result = {}
    for event in data["events"]:
        result[event["occurrence"]] = event
    return result


def record(workspace, blog, topic_id, occurrence, status, payload, event_id, expected_revision):
    from catalog import load as catalog_load
    if status not in STATUSES or not isinstance(payload, dict):
        raise HistoryError("상태/기록 payload 오류")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,120}", event_id):
        raise HistoryError("event_id 형식 오류")
    if type(expected_revision) is not int or expected_revision < 0:
        raise HistoryError("expected_revision은 0 이상의 정수입니다")
    if topic_id not in {t["id"] for t in catalog_load()[1]} or not occurrence.startswith(topic_id + ":") or len(occurrence) > 200:
        raise HistoryError("카탈로그 주제/회차가 올바르지 않습니다")
    path = history_path(workspace, blog)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix(".lock")
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise HistoryError("다른 기록이 진행 중입니다. 잠금을 확인하세요") from exc
    temp_name = None
    try:
        os.close(descriptor)
        data = load(workspace, blog)
        body = {"event_id": event_id, "topic_id": topic_id, "occurrence": occurrence, "status": status, "payload": payload}
        for prior in data["events"]:
            if prior["event_id"] == event_id:
                if all(prior[k] == v for k, v in body.items()):
                    return data
                raise HistoryError("같은 event_id의 다른 내용은 기록할 수 없습니다")
        if data["revision"] != expected_revision:
            raise HistoryError("revision 충돌: 현재 이력을 다시 조회하세요")
        previous = current(data).get(occurrence)
        before = previous["status"] if previous else None
        allowed = {None: {"recommended", "selected", "drafted"}, "recommended": {"recommended", "selected", "drafted"},
                   "selected": {"selected", "drafted"}, "drafted": {"drafted", "published", "needs_update"},
                   "published": {"published", "needs_update", "drafted"}, "needs_update": {"needs_update", "drafted"}}
        if status not in allowed[before]:
            raise HistoryError(f"허용되지 않은 상태 전이: {before} → {status}")
        if status == "drafted":
            artifact_valid(workspace, payload.get("artifact"))
        if status == "needs_update" and not str(payload.get("reason", "")).strip():
            raise HistoryError("갱신이 필요한 실제 이유를 기록하세요")
        if status == "published":
            if not previous or before not in ("drafted", "published"):
                raise HistoryError("원고 확인 후 발행을 기록해야 합니다")
            artifact_valid(workspace, payload.get("artifact"))
            if payload["artifact"] != previous["payload"]["artifact"]:
                raise HistoryError("현재 초안과 발행 원고가 다릅니다")
            pub = payload.get("publication", {})
            if pub.get("basis") not in ("user_confirmed", "observed") or not isinstance(pub.get("evidence"), str) or not pub["evidence"].strip() or urlparse(pub.get("url", "")).scheme != "https" or not urlparse(pub.get("url", "")).netloc:
                raise HistoryError("사용자 발행 확인/관찰 근거와 https URL이 필요합니다")
            from article import verify_saved
            verify_saved(workspace, payload, require_passed=True)
            saved_brief = json.loads(safe_file(workspace, payload["brief"]["path"]).read_text(encoding="utf-8"))
            if saved_brief["blog"] != blog or saved_brief["topic_id"] != topic_id or saved_brief["occurrence"] != occurrence:
                raise HistoryError("발행 기록과 검수 원고의 블로그/주제/회차가 다릅니다")
        body["recorded_at"] = datetime.now(timezone.utc).isoformat()
        data["events"].append(body); data["revision"] += 1
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
            temp_name = handle.name
            json.dump(data, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.flush(); os.fsync(handle.fileno())
        os.replace(temp_name, path); temp_name = None
        return data
    finally:
        if temp_name and Path(temp_name).exists(): Path(temp_name).unlink()
        lock.unlink()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["show", "record"])
    parser.add_argument("--workspace", required=True); parser.add_argument("--blog", required=True)
    parser.add_argument("--topic-id"); parser.add_argument("--occurrence"); parser.add_argument("--status", choices=sorted(STATUSES))
    parser.add_argument("--payload"); parser.add_argument("--event-id"); parser.add_argument("--expected-revision", type=int)
    args = parser.parse_args()
    try:
        if args.command == "show": result = load(args.workspace, args.blog)
        else:
            if not all([args.topic_id, args.occurrence, args.status, args.payload, args.event_id]) or args.expected_revision is None:
                raise HistoryError("record의 주제·회차·상태·payload·이벤트·revision을 지정하세요")
            result = record(args.workspace, args.blog, args.topic_id, args.occurrence, args.status, json.loads(Path(args.payload).read_text(encoding="utf-8")), args.event_id, args.expected_revision)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True)); return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        import sys
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr); return 2


if __name__ == "__main__": raise SystemExit(main())
