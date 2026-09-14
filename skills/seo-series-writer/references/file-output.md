# 연동용 본문 전용 파일 출력

사용자가 파일/시리즈 연동을 요청한 경우에만 적용한다. 기존 니치·목차·첫 회차 대화 출력과 단독 사용은 유지한다.

1. 지정된 작업 영역에 회차별 article.md와 editorial.json을 별도 작성한다. 기존 파일을 덮어쓰지 않는다. 기존 원고 재사용 요청이면 내용을 새로 쓰지 않는다.
2. article.md에는 H1 제목 1개와 공개 본문만 둔다. 관리용 시리즈 식별 코드·닉네임 질문·승인 평가·게시 제외 안내·작성 진행 상황은 editorial.json으로 보낸다. 편집 메모 제거를 위한 임의 문자열 삭제는 하지 않는다.
3. 원고는 H2/H3·문단·bold·단층 목록·표·로컬 이미지·지정 레이블의 지원 subset으로 작성한다. H2는 나중에 말풍선, `**핵심 요약**`은 제목 라벨의 라인형 인용구로 렌더된다. 요약 목록 전체를 인용구 한 덩어리로 만들지 않는다.
4. `**태그**`를 마지막 레이블로 두고 그 아래 `#태그1 #태그2`만 작성한다. 태그가 필요 없으면 이 영역을 생략한다. 태그는 준비 시 본문과 분리된다. 개수나 100자 제한을 SEO 합격 규칙으로 주장하지 않는다.
5. 이미지가 이미 있으면 위치를 유지한다. 이미지 생성 요청이 없으면 생성하거나 가짜 파일 링크를 만들지 않는다. 슬롯을 요청받은 경우 공용 image-slot 계약을 사용하고 미완료 상태를 기록한다.
6. 검수는 기존 quality-policy와 evaluation-rubric을 적용한다. 허구 체험·검증하지 않은 핵심 주장·중복·과장·승인 보장을 확인한다. 메모는 JSON 데이터이지 다른 스킬에 실행시킬 명령문이 아니다.
7. 신규 완성형 연결은 `naver-series/v2`를 사용한다. 게시 본문 3,000자 하한, primary/secondary 작성 프로필, 이미지 포함 시 최소·목표 수량을 manifest에 기록한다. prepare가 만든 `content-metrics.json`을 계산 근거로 사용하며 기존 v1 파일을 검수 없이 v2로 승격하지 않는다.

최소 editorial.json 예시:

```json
{"series_id":"example-series","episode":3,"search_intent":"이번 편의 독자 질문","notes":[],"open_questions":[]}
```

후기형 또는 체험 기반 스토리형에는 다음처럼 근거의 종류를 기록한다.

```json
{
  "series_id": "example-series",
  "episode": 3,
  "experience_basis": {
    "type": "user_provided",
    "evidence": ["사용자가 제공한 사용 메모", "원본 사진 3장"]
  }
}
```

`type`은 `user_provided`, `verified_records`, `illustrative` 중 하나다. 후기형은 앞의 두 값과 비어 있지 않은 evidence가 필요하다. `illustrative`는 후기 근거가 아니며 스토리형의 공개 가정 사례에만 쓴다.

naver-series-workflow 연동의 review.json은 첫 변환 전에는 아래와 같이 둔다.

```json
{"schema":"naver-review/v1","status":"pending","content_revision":null,"checks":[],"reviewed_by":null,"reviewed_at":null}
```

신규 v2 review의 evidence는 자유 문장 하나가 아니라 실제 위치와 발견 내용을 담은 배열이다.

```json
{
  "schema": "naver-review/v2",
  "status": "pending",
  "content_revision": null,
  "checks": [
    {"id": "question_resolution", "status": "pending", "evidence": []}
  ],
  "reviewed_by": null,
  "reviewed_at": null
}
```

passed evidence 항목은 `location`, `finding`, `source_refs`를 가진다. 공통 검사 외에도 주·보조 프로필에 맞는 정보 자산, 이야기 흐름, 후기 근거, 초보자 명료성, 진단 경로 또는 대칭 비교 검사를 포함한다. 여러 회차에 같은 포괄 문장을 복사하지 않는다.

변환 결과의 실제 revision과 전체 사실성·독창성·이미지 관련성·본문 경계 검수를 연결한 후에만 passed로 작성한다. 전체 검수 항목은 workflow의 references/series-contract.md를 따른다. 실제 이미지 시각 검수를 하지 않았거나 핵심 근거가 없으면 pending/needs_revision을 유지한다. 단독 writer 사용에는 workflow 설치를 요구하지 않는다.
