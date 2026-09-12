# 작성 스킬 → 준비 CLI → SmartEditor drafter 연결

## 1. 발견·입력·범위

- 이 스킬의 실제 파일 위치를 기준으로 sibling seo-series-writer/SKILL.md와 naver-smarteditor-drafter/SKILL.md를 찾는다. 이름만으로 설치·이전 상태를 추측하지 않는다.
- 저장소 직접 사용이 기본 지원 경로다. 개별 설치본도 sibling drafter가 있어야 CLI가 작동한다. 슬롯 합성은 추가로 저장소 공용 scripts/insert_article_images.py가 필요하다. 자동 설치·외부 저장소 쓰기는 하지 않는다.
- writer는 새 원고/수정 요청이 있을 때만 호출한다. 기존 파일 처리만 요청했다면 글·이미지를 새로 생성하지 않는다. 제목 전용·문체 전용 스킬은 필수 의존성이 아니다.
- 모드·회차·블로그·출력 루트를 현재 사용자 요청에서 확정한다. 시리즈 코드만으로 과거 대화를 복원하지 않는다. 이미 알려진 값은 반복 질문하지 않되 필수 계정을 추측하지 않는다.

## 2. 원고와 검수 인계

writer의 파일 출력 규칙으로 article.md, editorial.json, review.json을 분리한다. 공개 본문은 drafter의 지원 subset으로 작성한다. 기존 원고는 모호하지 않을 때만 재사용한다. 검수 기록에 핵심 주장·이미지 시각 검수 미수행이 있으면 pending을 유지한다.

이미지 생성 요청이 있으면 현재 이미지 도구 지침을 읽고 요청 수량·주제에 맞게 준비한다. 개념 설명용 이미지·UI 예시가 사실 화면처럼 오인되지 않게 표시한다. 최종 파일 경로와 관련성·배치 근거를 검토하고 승인된 슬롯만 합성한다. CLI는 이미지 생성을 호출하지 않는다.

첫 prepare→후보 정본·revision 확인→실제 검수→입력 review 저장→새 run-id prepare 순서다. 이미지5장·태그100자 등 설정은 실제 사용자 요구를 사용한다. 모든 회차 ready 이전에는 UI 진입이 없다.

## 3. 실제 UI 진입 전 게이트

이 절차는 사용자가 draft/resume을 명시적으로 요청한 경우에만 수행한다. 로컬 개발/prepare/status에서 이 절차를 시험 삼아 실행하지 않는다.

1. 지원되는 현재 브라우저 스킬/도구의 설명을 읽고 현재 탭·로그인·대상 블로그를 관찰한다. 파일 업로드가 실제 로컬 파일에 접근 가능한지 확인한다. 수동 조치가 필요하면 정확히 요청한다.
2. Python status로 snapshot/source/assets/review를 다시 검증한다. queue가 있더라도 UI 권한으로 취급하지 않는다. 다른 target_blog, stale revision, 레거시/부분 실행은 대조부터 수행한다.
3. 명시적으로 고른 별도 실행 root와 environment=live로 기존 ExecutionStore를 만든다. 준비 output이나 레거시 보고서 폴더를 실행 root로 재사용하지 않는다.
4. 블로그별 lease를 확보한다. 오래됐다는 이유만으로 잠금을 지우지 않는다. 실제 프로세스·미완료 operation·현재 UI 근거를 확인한다.
5. 모든 회차를 동시에 여러 탭에서 쓰지 않는다. 이미 검증된 동일 revision은 skip, 대조할 회차가 있으면 그 회차에서 멈춘다.

CLI의 `draft`/`resume` 하위 명령은 없다. UI는 현재 Codex 도구가 수행하고 결정적 데이터 처리는 기존 모듈이 수행한다. 쉘에서 CUA를 가짜 import하거나 미문서화 연결 API를 만들지 않는다.

## 4. 한 회차의 실행 계약

실제 drafter의 references/smarteditor-runbook.md와 references/recovery-and-safety.md를 읽고 그 계약을 그대로 따른다.

| 단계 | 재사용 자산 / 기록 |
|---|---|
| 시작·기존 상태 | ExecutionKey(blog, series, episode, revision), ExecutionStore.status/start |
| 전체 빈 화면 | JS verifyBlank scope=editor_checked → store.verify |
| 본문·이미지·태그 | renderPlan 순서, actionGate, begin_operation → 현재 지원 UI 동작 → finish_operation |
| 이미지 직전 | asset_integrity.verify_asset, 실제 파일/표시 이미지 연결 증거 |
| 전체 입력 대조 | verifyContent scope=input_verified → store.verify |
| 임시저장 | save intent → 실제 ack. 미관찰은 unknown, 자동 재시도 금지 |
| 해당 초안 재열기 | 실제 고유 초안 식별 → verifyContent scope=reopened_verified |
| 빈 글쓰기 전환 | 기존 본문 삭제가 아닌 새 글쓰기 → verifyBlank scope=blank_verified |
| 다음 회차 | canAdvance와 이벤트 상태가 모두 통과한 후에만 진행 |

H2는 말풍선 인용구, 핵심 요약은 라인형 제목 라벨이다. 긴 문단 전체 선택·원 selector 유일성·이미 적용된 스타일을 대조한다. 이미지 수만 맞는 것으로 성공 처리하지 말고 순서와 앞뒤 본문까지 확인한다.

태그 패널 진입 버튼과 최종 발행 버튼은 이름이 같을 수 있다. panel/role/purpose/is_final_submit의 실제 관찰로 분리한다. 최종 발행 제출은 허용 목록에 없으며 식별이 불확실하면 중단한다.

## 5. 중단·재개·완료

- status의 next_action=start이면 현 편집기의 전체 빈 상태부터 확인한다. verify_blank_only이면 저장된 동일 원고를 재생성하지 말고 빈 화면 전환만 대조한다.
- reconcile_input은 진행 중 UI operation과 실제 부분 입력을 확인한 뒤 기존 저장소의 대조 절차를 따른다. 입력 전체를 지우고 처음부터 시작하지 않는다.
- reconcile_save는 저장 목록·고유 초안·내용을 확인한다. 저장 ack가 없다는 사실만으로 미저장이라고 단정하지 않는다. 미저장 재시도는 실제 대조 및 사용자 확인이 필요하다.
- revision_conflict이면 변경된 원고로 기존 초안을 자동 덮어쓰지 않는다. 새 revision과 기존 저장 이력을 보여준다.
- legacy saved_verified는 명시적으로 해당 보고서를 읽을 때만 legacy_saved_reported로 취급한다. 자동 재열기 완료 승격·신규 초안 생성 금지다.
- 이벤트 저장 실패·이미지 미완료·로그인 만료·부분 관찰·복구 팝업에서는 다음 회차를 시작하지 않는다. 로그와 현재 상태를 보존한다.

실제 보고서는 각 회차의 준비/검수/저장 ack/재열기/빈 화면과 근거를 분리한다. 모든 요청 회차와 최종 빈 화면까지 검증되지 않았으면 전체 완료라고 하지 않는다. screenshot·목록·계정 정보는 필요한 최소 범위만 남기고 쿠키·토큰·불필요한 초안 목록은 저장하지 않는다.

로컬 simulation이 성공해도 실제 계정에서 성공한 것이 아니다. 라이브 테스트는 별도 요청된 원고·초안 수에 한정하며 기존 초안을 삭제하거나 공개 발행하지 않는다.
