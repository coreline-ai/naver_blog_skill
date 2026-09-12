# 실행 이벤트·중단·복구

준비 CLI는 저장 이력을 쓰지 않는다. UI 이력은 `scripts/execution_state.py`의 별도 `ExecutionStore`를 사용한다. 이 모듈에는 브라우저 연결·입력·발행 API가 없으며, Codex가 현재 지원 도구로 실제 관찰한 결과를 기록하는 저장소다.

## 상태와 의도 기록

```text
ready → editor_checked → inserting → input_verified
→ save_requested → save_acknowledged → reopened_verified → blank_verified
```

- 블로그별 `acquire(blog, run_id)`로 Lease를 얻고 같은 실행에서는 그 lease를 유지한다. `ExecutionKey(target_blog, series_id, episode, revision)`의 revision은 콘텐츠 SHA-256이다.
- `start`는 같은 key를 초기화하지 않는다. `status`와 `events`는 읽기 전용이다.
- UI 부작용 전에 `begin_operation`의 intent 이벤트를 반드시 확정한다. 이 호출이 실패하면 실제 UI 작업도 수행하지 않는다.
- 실제 UI 동작 후 `finish_operation`에 observed/failed/unknown 결과를 기록한다. 인식하지 못한 관찰값은 null로 남긴다. 저장은 실제 ack가 있어야 `save_acknowledged`로 전환된다.
- 허용 작업: insert_block/upload_image/apply_quote/open_tag_settings/input_tags/close_tag_settings/save/open_saved/new_editor. 최종 공개 발행 작업은 없다.
- `verify`는 단계별 checks, environment, target_blog, content_revision, 실제 observed, evidence_ref를 요구한다. 이 값은 UI 검사 결과로부터 전달하며 expected를 복사해 만들어내지 않는다.
- 가상 테스트는 `environment='simulation'`을 사용한다. live store는 simulation 이력을 읽어 재사용하지 못한다.

## 이벤트와 집계

경로: `<execution-root>/<blog-hash>/<series-id>/episode-NN/<revision>/events/000001.json`.

각 이벤트에 sequence/event_id/operation_id/event_type/state/timestamp/previous_hash/payload/event_hash/key/environment가 있다. 최종 텍스트는 canonical JSON 방식으로 해시하고 직전 이벤트와 연결한다. 읽을 때 경로·파일 종류·순서·해시·전이·필수 증거를 재검사한다.

**파일명은 sequence 단독**으로 사용한다. 같은 sequence를 두 호출이 동시에 확정하면 둘째가 실패하도록 하기 위해서다. uuid event_id는 payload에 보존한다. flush+fsync한 파일을 exclusive hard-link로 확정하며 이벤트를 덮어쓰지 않는다. 이 hash chain은 손상 탐지 수단이지 파일 수정 권한이 있는 공격자에 대한 서명/인증이 아니다.

`write_summary`는 이벤트에서 `execution-summary.json`을 재생성한다. 집계 파일은 상태 정본이 아니며 사람이 바꾼 집계를 그대로 믿지 않는다. 준비 폴더나 과거 run-report를 실행 저장소로 지정하지 않는다.

## 재개 판단

| status.resume_decision | 행동 |
|---|---|
| start | 요청/준비 검증 후 빈 편집기를 확인하고 시작 |
| skip | 같은 회차·버전은 재생성하지 않음 |
| verify_blank_only | 이미 재열기 검증됨. 필요한 새 화면 전환과 빈 상태만 확인 |
| reconcile_save | 현재 편집기·저장 목록·초안 식별·내용을 대조. 저장 재클릭 금지 |
| reconcile_input | 실제 입력된 부분·이미지 위치·진행 중 업로드/작업을 대조 |
| revision_conflict | 다른 버전 실행 기록 존재. 새 글 생성/덮어쓰기 없이 보고 |

pending intent는 작업이 중단됐다는 증거가 아니다. 도구의 실제 실행 핸들이 살아 있으면 그 핸들을 확인/대기한다. 관찰 타임아웃만으로 재실행하지 않는다.

- 저장 후 로컬 기록 전에 중단: 저장 초안을 식별하여 전체 재열기 검증을 통과하면 `reconcile_saved`. ack를 추측해 작성하지 않는다.
- 부분 입력: 전체 현재 관찰·부분 콘텐츠 일치·진행 중 작업 없음의 증거가 있으면 `reconcile_input`. 이미 존재하는 블록을 다음 렌더 단계에서 건너뛰고 모호한 블록은 멈춘다.
- 미저장으로 확인되어 저장 재시도가 필요할 때: 전체 현재 입력 일치, 저장 목록에 일치 초안 없음, 진행 중 작업 없음, 사용자 재시도 승인까지 있어야 `reconcile_not_saved`로 input_verified를 복원한다. 목록에 안 보인다는 사실만으로 자동 재시도하지 않는다.
- 기존 내용·다른 블로그·로그인 만료·CAPTCHA·업로드 오류·식별 불가 화면에서는 이후 회차 중단. 기존 내용 자동 삭제나 전체 재입력 금지.

## 잠금

블로그당 한 writer.lock이며 같은 지정 실행 저장소를 공유하는 단일 호스트 실행을 지원한다. 다른 호스트/저장소나 수동 편집을 잠금으로 막는다고 주장하지 않는다.

Lease는 token과 run_id로 소유자를 확인한다. 완료 후 release한다. 실패 후 lock을 유지하거나 명시적으로 release하더라도 pending 이벤트는 남아서 다음 실행의 재입력을 막는다. 단발 Python 프로세스가 끝났다는 이유만으로 UI 작업도 종료됐다고 보지 않는다.

`recover_lock`은 OS liveness/process start identity로 기존 소유가 종료됐음을 확인하고 현재 UI·pending operation 대조 증거가 있어야 한다. TTL/파일 나이만으로 해제하지 않는다. 이전 잠금과 대조 증거는 lock-history에 보존한다. 잠금·이벤트가 손상되거나 process identity가 불명확하면 자동 삭제하지 않는다.

## 기존 보고서

`import_legacy`는 명시적으로 지정된 회차별 `draft-run-report.json`만 읽는다. status=saved_verified, 파일/폴더/내부 회차 일치를 검사한다. 원본 바이트 해시와 보고된 상태를 기록하되 `legacy_saved_reported`, observed_reopened=null로 해석한다. 기존 JSON은 변경하지 않는다.

이전 전체 run-report에 있는 모든 회차를 새 검증 완료로 일괄 승격하지 않는다. 해당 회차별 보고서를 대조하여 가져오며 회차가 불명확하면 멈춘다.

## 증거와 개인정보

expected/observed/checks/evidence_ref를 분리한다. 관찰값의 출처와 전체/부분 관찰 범위를 남기고 필요한 최소 캡처만 보존한다. 쿠키·로그인 정보·관계없는 초안 전체 목록은 저장하지 않는다. 실제 네이버 작업을 하지 않은 로컬 테스트 보고서에는 simulation임을 명시한다.
