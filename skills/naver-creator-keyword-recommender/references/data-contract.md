# 데이터 계약

이 계약은 크리에이터 어드바이저의 날짜별 유입 데이터 전용이다. 네이버 블로그 홈 제목 표본은 [별도 블로그 홈 데이터 계약](blog-home-data-contract.md)을 사용하며 이 스키마의 surface에 합치지 않는다.

## 목차

1. 입력 계약
2. surface와 item 의미
3. 출력 계약
4. 상태와 개인정보

## 1. 입력 계약 — `naver-creator-snapshots/v1`

브라우저 관찰 결과는 하나의 JSON 파일로 저장한다. 날짜는 크리에이터 어드바이저 화면에 표시된 데이터 날짜이며 캡처 날짜가 아니다.

```json
{
  "schema": "naver-creator-snapshots/v1",
  "captured_at": "2026-09-12T21:00:00+09:00",
  "snapshots": [
    {
      "date": "2026-09-11",
      "surface": "search_inflow",
      "status": "complete",
      "items": [
        {
          "kind": "search_keyword",
          "text": "화담숲 예약",
          "category": "국내여행",
          "segment": "topic",
          "list_position": 4,
          "indicator_raw": "2"
        }
      ]
    },
    {
      "date": "2026-09-11",
      "surface": "main_inflow",
      "status": "partial",
      "reason": "viewport_truncated",
      "items": [
        {
          "kind": "main_title",
          "text": "화면에서 확인한 전체 제목",
          "list_position": 1
        }
      ]
    },
    {
      "date": "2026-09-11",
      "surface": "business",
      "status": "unavailable",
      "reason": "temporary_service_error",
      "items": []
    }
  ]
}
```

허용 필드는 닫혀 있다.

### 최상위

| 필드 | 타입 | 규칙 |
|---|---|---|
| `schema` | string | 정확히 `naver-creator-snapshots/v1` |
| `captured_at` | string | 비어 있지 않은 ISO 8601 권장 |
| `snapshots` | array | 하루·surface 단위 관찰 목록 |

### snapshot

| 필드 | 타입 | 규칙 |
|---|---|---|
| `date` | string | `YYYY-MM-DD` |
| `surface` | string | 아래 허용값 중 하나 |
| `status` | string | `complete`, `partial`, `unavailable`, `manual_partial` |
| `reason` | string | partial/unavailable이면 권장 |
| `items` | array | unavailable이면 비어 있어야 함 |

### item

| 필드 | 타입 | 규칙 |
|---|---|---|
| `kind` | string | surface에 허용된 종류 |
| `text` | string | 화면에서 확인한 전체 텍스트. 잘렸으면 넣지 않고 snapshot을 partial로 처리 |
| `category` | string | 화면에 표시된 경우만 |
| `segment` | string | `topic`, `audience`, `all` 등 관찰 출처. 출력에서는 개인화 이름을 제거 |
| `list_position` | integer | 화면 목록의 1부터 시작하는 위치 |
| `indicator_raw` | string | `new`, 숫자, `-` 등을 해석하지 않고 그대로 저장 |

## 2. surface와 item 의미

| surface | 허용 kind | 추천 키워드 사용 |
|---|---|---|
| `search_inflow` | `search_keyword` | 사용 |
| `main_inflow` | `main_title` | 사용하지 않고 제목 패턴만 집계 |
| `business` | `business_keyword`, `business_title`, `business_signal` | `business_keyword`만 별도 출처로 사용 |
| `manual` | `search_keyword`, `main_title`, `business_keyword`, `business_title`, `business_signal` | item kind에 따르되 전체 상태는 partial |

비즈니스 화면의 설명이 키워드인지 콘텐츠인지 불분명하면 `business_signal`로 기록한다. 모델이 의미를 추정해 kind를 승격하지 않는다.

## 3. 출력 계약 — `naver-creator-keyword-pack/v1`

```json
{
  "schema": "naver-creator-keyword-pack/v1",
  "as_of": "2026-09-12",
  "analysis_status": "complete",
  "periods": {
    "recent": {"start": "2026-09-05", "end": "2026-09-11"},
    "comparison": {"start": "2026-08-29", "end": "2026-09-04"}
  },
  "coverage": {},
  "comparison_ready": true,
  "recommendations": [
    {
      "keyword": "화담숲 예약",
      "normalized_keyword": "화담숲 예약",
      "evidence_score": 74.5,
      "trend_type": "persistent",
      "recent_days_seen": 5,
      "comparison_days_seen": 2,
      "recent_dates": ["2026-09-11"],
      "sources": ["search_inflow"],
      "categories": ["국내여행"],
      "new_signal_observed": false,
      "segment_count": 1
    }
  ],
  "title_pattern_summary": {
    "titles_observed": 20,
    "patterns": [],
    "sensitivity_flags": []
  },
  "limitations": []
}
```

`evidence_score`는 입력 안에서 비교하기 위한 관찰 점수다. 검색량, 클릭률, 기대 조회수 또는 노출 확률이 아니다. `trend_type`도 데이터 창 안의 등장 패턴이며 네이버가 제공한 공식 분류가 아니다.

## 4. 상태와 개인정보

- `complete`: 지정한 required surface가 두 기간의 모든 날짜에 관찰됨.
- `partial`: 추천 가능한 최근 키워드는 있으나 required surface·날짜 일부가 누락됨.
- `unavailable`: 최근 기간에 추천할 키워드 관찰값이 없음.
- `comparison_ready`: 최근·비교 기간 모두에서 필수 키워드 surface가 7일 완전 관찰됐을 때만 true.

원시 파일은 `.creator-advisor-private/` 또는 `outputs/creator-advisor-private/`처럼 Git 제외 경로에 둔다. 계정 ID, 쿠키, 토큰, 전체 화면 HTML, 개인화된 연령 세그먼트 이름은 출력 팩에 넣지 않는다.
