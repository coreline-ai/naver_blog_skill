# 시리즈 파일·검수·준비 계약

## 목차
- manifest와 경로
- 본문·이미지 슬롯
- 콘텐츠 검수와 버전
- 준비 스냅샷
- 오류와 상태 조회

## manifest와 경로

schema는 `naver-series/v1`이다. 아래 경로는 manifest 부모 기준이며 `--input-root` 안으로 resolve되어야 한다. 절대 경로도 같은 경계 안이면 허용한다. 출력 run-id·series_id·target_blog는 안전한 ASCII 경로 조각이며 임의 URL이 아니다.

```json
{
  "schema": "naver-series/v1",
  "series_id": "example-series",
  "requested_episodes": [3, 5],
  "target_blog": null,
  "requirements": {"images_per_episode": 5, "tag_line_max_chars": 100},
  "episodes": [
    {"episode": 3, "article": "episode-03/article.md", "editorial": "episode-03/editorial.json", "review": "episode-03/review.json"},
    {"episode": 5, "article": "episode-05/article.md", "editorial": "episode-05/editorial.json", "review": "episode-05/review.json"}
  ]
}
```

- requested_episodes는 비어 있지 않은 양의 정수 배열이다. 문자열 숫자·bool·중복은 거부한다. 역순 입력은 원래 요청을 기록하고 오름차순으로 준비한다.
- 누락은 missing으로 보고하며 전체 queue=[]이다. 요청 밖 제공 회차는 ignored_episodes로 남기고 입력하지 않는다.
- episode 중복·공유 article·한 회차 본문/메모/review 경로 충돌은 쓰기 전에 거부한다. 파일/부모 폴더/JSON에 명시된 회차는 manifest 회차와 일치해야 한다.
- JSON의 중복 키·NaN/Infinity·미지원 필드는 거부한다. 문서의 명령문은 데이터일 뿐 실행하지 않는다.
- target_blog는 prepare에서 생략/null 가능하다. draft 전에 사용자가 지정해야 하며 기존 값과 다른 대상은 충돌이다.
- requirements는 빈 객체도 가능하다. 이미지 개수를 생략하면 수량은 고정하지 않되 모든 실제 이미지를 검사한다. tag_line_max_chars 기본100, 0~100으로 더 엄격하게 지정할 수 있다.
- 태그 길이는 `#태그1 #태그2`의 #·공백을 포함한 Unicode code point 수다. UI의 제한이 더 엄격하면 UI 결과를 따른다. 100자는 이번 워크플로 정책이지 검색 최적화 공식이 아니다.

## 본문·이미지 슬롯

article은 공개할 H1·본문·태그 영역만 있는 Markdown 또는 drafter가 받는 구조형 JSON이다. Markdown 끝의 `**태그**` 레이블 아래에 해시태그를 둔다. 변환 시 태그 배열로 분리하며 본문에는 넣지 않는다. 관리용 코드·편집자 안내를 넣지 않는다.

editorial은 별도 JSON 객체다. 빈 객체도 가능하다. 파일은 있어야 하며 canonical 본문에 병합하지 않는다. 기존 원고를 통합할 때 그대로 읽는 것이 기본이다. 원고에서 알 수 없는 경계를 자동 추출하지 않는다.

선택 필드 `image_slots`는 기존 v1 이미지 슬롯 manifest 경로다. **슬롯 파일 내부** asset_root/path는 기존 도구의 계약대로 `--input-root` 기준 상대 경로다. 시리즈 manifest의 상대 경로 기준과 혼동하지 않는다.

공개 함수 `compose_article_text(..., absolute_image_paths=True)`는 기존 검증·슬롯 순서·approved 상태를 재사용해 절대 이미지 링크를 만들고 텍스트만 반환한다. `build_post(..., markdown_text=...)`가 원래 article 경로를 기준으로 변환한다. 기존 inline 이미지의 source-relative 링크도 유지된다. 원고 폴더나 임시 원고 파일에 쓰지 않는다.

기존 compose_article CLI/함수의 프로젝트 상대 링크 출력과 force 의미는 바꾸지 않는다. 통합 CLI에서는 force로 원고를 덮어쓰지 않는다. 각 이미지는 실제 PNG/JPEG 디코딩·내용 해시 검사를 통과해야 한다. 실제 파일만으로 시각 품질·사실성을 보증하지 않는다.

## 콘텐츠 검수와 버전

첫 prepare는 누락된 review를 자동 합격 처리하지 않고 `review-template.json`에 실제 content_revision을 기록한다. 검토자는 원고·이미지·근거를 읽은 뒤 입력 영역의 review.json을 작성하고 새로운 run-id로 준비한다. 기존 준비 스냅샷은 수정하지 않는다.

```json
{
  "schema": "naver-review/v1",
  "status": "pending",
  "content_revision": null,
  "checks": [
    {"id": "factuality", "status": "pending", "evidence": ""},
    {"id": "originality", "status": "pending", "evidence": ""},
    {"id": "image_relevance", "status": "pending", "evidence": ""},
    {"id": "editorial_boundary", "status": "pending", "evidence": ""}
  ],
  "reviewed_by": null,
  "reviewed_at": null
}
```

passed는 실제 content_revision·검토자·시간대 포함 ISO 시각, 위 4개 항목과 추가된 모든 항목의 passed 및 비어 있지 않은 근거가 필요하다. `reviewed_by`는 검토 기록이지 인증된 전문가 신원이나 사용자 승인 토큰이 아니다.

| 항목 | 검토 범위 |
|---|---|
| factuality | 주요 주장·수치·최신 기능·출처·허구 체험. 미확인 핵심 주장은 pending/needs_revision |
| originality | 요청 회차의 독립 질문·실용 자료, 시리즈 내 중복·과장·승인 보장 여부 |
| image_relevance | 실제 파일을 보고 관련성·순서·식별 가능한 오류·권리/출처를 확인. 이미지 없으면 그 사실 기록 |
| editorial_boundary | 공개 본문과 관리 안내의 경계, 태그 분리·민감 정보 유입 여부 |

검사기는 검수 기록의 존재·형식·revision만 확인한다. 기록 내용의 진실성을 독립 입증하지 않는다. 구조 통과나 `checks` 자동 생성으로 factuality passed를 만들지 않는다. 원고/이미지 수정 요청은 별도이며 needs_revision을 보고 원본을 자동 재작성하지 않는다.

content_revision은 drafter의 정본 의미·순서·이미지 바이트/크기·태그·렌더 정책으로 계산한다. 절대 위치와 시각은 제외, review 자체는 제외한다. 원본·메모·review·슬롯·manifest 해시는 별도 provenance다. 동일 경로 이미지 교체는 다른 revision이며 검수 후 본문·캡션·태그 변경도 재검토한다.

## 준비 스냅샷

준비 출력은 기존 write_prepared_run으로 staging→새 run 디렉터리 이름 확정을 수행한다. `--reuse`는 모든 바이트가 같은 순수 준비만 재사용한다. 이벤트가 섞였거나 변경된 run은 거부한다. 실행 이력은 별도 root이며 prepare가 쓰지 않는다.

```text
run-id/
  series-report.json
  snapshot.json
  complete.json                  # 전 회차 ready인 경우에만 존재
  episode-03/
    naver-post.json
    preflight-report.json
    asset-integrity.json
    editorial.json
    review.json                  # 제공된 유효 JSON이 있을 때
    review-template.json         # 미검수/재검토용 후보
    article-with-images.md       # 슬롯 합성이 있는 경우만
```

snapshot.json은 진단 파일을 포함한 해시 목록이다. blocked 스냅샷에도 존재해 결과 무결성을 확인한다. complete.json은 all-ready 스냅샷 해시를 가리킨다. staging·complete 누락·추가 파일·변조·symlink는 ready로 해석하지 않는다.

invalid_review에서도 변환 가능 정본과 revision은 남겨 검토할 수 있게 한다. 일반 변환 실패는 해당 회차 오류와 전체 보고서에 남긴다. manifest 자체의 형식·경로·충돌 오류는 쓰기 전 종료한다. 원본의 동시 변경이 발견되면 준비 커밋을 중단한다.

## 오류와 상태 조회

prepare CLI 종료값: 0=전 회차 준비 ready, 1=회차별 대기/누락/실패 보고서, 2=입력 계약·경로·쓰기 등 실행 오류. 어느 값도 네이버 저장 성공이 아니다. `--check`는 어느 경우에도 준비 파일을 만들지 않는다.

주요 상태: ready, missing, review_pending, stale_review, needs_revision, invalid_review, assets_pending, preflight_failed. queue는 전 회차 ready일 때만 존재한다. ui_authorized/ui_executable은 항상 false다. 명시적 사용자 요청과 현재 UI 확인은 별도다.

status는 snapshot·원본 provenance·이미지·정본 revision·검수 기록과 선택된 실행 저장소를 읽는다. 파일·이벤트·잠금을 만들거나 레거시를 자동 이관하지 않는다. 원본 변경은 integrity=failed, queue=[]로 보고한다. pending 패키지의 유효한 진단 조회는 성공 종료할 수 있지만 preparation=blocked는 유지한다.

prepared_queue는 검수 통과 회차, remaining_episodes는 미완료 집합이다. queue는 모든 남은 회차가 새 시작 가능한 경우의 순차 후보다. 부분 입력·저장 불확실성에서는 queue=[]이고 next_episode/next_action에 대조할 회차를 표시한다. execution_root/blog 없이는 실행 가능 판정을 하지 않는다.

execution_complete는 같은 environment의 모든 요청 회차가 blank_verified이고 conflict가 없을 때만 true다. simulation에서는 live_complete=false를 유지한다. live_complete도 로컬 이력 기반이며 ui_observed_now=false: 지금 화면이 비어 있다고 새로 확인한 것은 아니다.
