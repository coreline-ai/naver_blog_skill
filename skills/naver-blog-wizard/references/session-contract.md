# 세션·산출물 계약

schema=naver-blog-wizard-session/v1. 사용자 work_root의 naver-blog-output/UUID/session.json에 저장한다. revision은 상태 변경 횟수이며 산출물 vN과 다르다. 스킬 소스 내부 work_root는 거부한다.

```text
wizard_session.py init --work-root ROOT [--initial-options FILE]
wizard_session.py next --session FILE
wizard_session.py answer --session FILE --question-id ID --value-json JSON --expected-revision N
wizard_session.py change --session FILE --key KEY --value-json JSON --expected-revision N
wizard_session.py record --session FILE --type TYPE --payload FILE --expected-revision N
wizard_session.py pause|resume --session FILE --expected-revision N
wizard_session.py status --session FILE
wizard_artifacts.py inspect|prepare-plan|compose --session FILE
```

next/status/inspect는 읽기 전용. 0=명령 처리, 1=산출물 복구 필요, 2=계약/경로/동시성 오류. 오류는 stderr JSON이다. question_id=key:rREVISION. 잘못된 답·미응답·중복 제출은 상태를 바꾸지 않는다.

confirmed_options는 value/origin/user_text. origin=initial-request/answer/explicit-default. auto 장수는 명시 선택 시 5. phase/pending_question_id는 파생 캐시이며 실제 파일을 다시 확인한다.

| record type | payload |
|---|---|
| repair | target(article/slots/plan/asset/package), asset이면 slot_id. 실제 검사 실패에서만 무효화 |
| article | path, 선택 profile_path |
| slots | article_path(마커 사본), slots_path(ordered slots 배열을 담은 JSON 객체) |
| plan | request_path, plan_path |
| effect-intent | slot_id, 선택 tool_prompt |
| effect-result | slot_id, path, provenance(generated/user-file/edited), 선택 effect_id/tool_result/failed |
| visual-review | slot_id, asset_sha256, passed(bool), notes(실제 관찰) |
| package | manifest_path, composed_article_path, completion_path |

prepare-plan/compose는 새 버전 파일과 record payload를 반환하고 record가 상태를 저장한다. 임의 JSON patch로 phase/승인을 바꾸지 않는다. 실제 도구 반환 기록·시각 QA의 진위를 Python이 인증하지 않는다.

article은 바이트 hash, plan은 원고/요청/계획 hash, asset은 slot_id·본문/slot prompt/reference hash·presentation/role·파일 hash로 연결한다. origin_plan은 추적용이다. 다른 슬롯 변경으로 plan 파일 hash만 바뀌었다고 모든 파일을 재생성하지 않는다. 편집 tool prompt/target hash는 별도로 기록한다.

작성 조건 변경은 원고/계획/검수를 무효화한다. 이미지 옵션·장수는 계획/합성, 한 이미지 편집은 해당 슬롯, caption은 합성, alt는 현재 prompt 비교 후 검수/합성을 갱신한다. 제외된 파일도 삭제하지 않는다.

intent 이후 결과 불명은 reconcile하고 자동 재생성하지 않는다. failed는 명확한 실패만 기록한다. QA 실패는 슬롯당 한 번 보정 후 해결 선택을 기다린다.

lock은 O_EXCL/PID, 변경은 lock 내 reread/CAS/검증/temp/fsync/replace. finally 해제하며 죽은 PID 확인 시 stale lock 정리, 살아 있거나 생사 불명인 lock은 유지한다. 저장 실패는 마지막 유효 상태와 실제 파일을 대조한다.

글만=확정 원고, 프롬프트만=검토 계획, 생성/내 파일=정확한 고유 N파일+시각 QA+사용 선택+package_verified. 편집만=실제 편집 결과+QA+사용 선택. package_verified로 생성/QA를 주장하지 않는다. 네이버 UI 작업 권한은 없다.

슬롯 파일은 `{"slots":[...]}` 객체다. 공통 strict JSON loader를 재사용한다. 참조가 외부 파일이면 prepare-plan은 change payload를 반환한다. reference_path를 change로 정규화한 뒤 다시 prepare-plan을 실행한다.

슬롯 문구 변경은 `change --key caption:ID` 또는 `change --key alt:ID`로 처리한다. alt 변경은 revise_slot_metadata 작업의 새 slots JSON 등록→계획 재검사→접근성/이미지 QA로 연결한다.

세션 쓰기는 macOS/Linux의 표준 fcntl guard 안에서 O_EXCL/PID lock을 관리한다. guard 파일은 유지하고 OS가 프로세스 종료 시 잠금을 해제한다. stale PID lock 정리와 재획득의 경합도 이 guard로 막는다.

검사 실패 복구는 repair 기록으로 해당 메타데이터만 무효화하고 다음 작업에서 새 버전을 등록한다. 파일은 삭제하지 않는다. 불명확한 intent는 먼저 reconcile해야 한다. 외부 입력 경로는 절대 경로, 실행용 상대 경로는 run_root 기준이다.
