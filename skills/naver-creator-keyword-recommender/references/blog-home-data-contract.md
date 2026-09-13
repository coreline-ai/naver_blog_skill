# 블로그 홈 데이터 계약

네이버 블로그 홈 제목은 크리에이터 어드바이저의 날짜별 검색 유입과 의미가 다르다. 기존 `naver-creator-snapshots/v1`에 합치지 않고 별도 스냅샷과 패턴 팩으로 관리한다.

## 입력 — `naver-blog-home-snapshot/v1`

```json
{
  "schema": "naver-blog-home-snapshot/v1",
  "captured_at": "2026-09-13T10:30:00+09:00",
  "source": {
    "directory_no": 0,
    "group_id": 0,
    "page_start": 1,
    "page_end": 10
  },
  "pages": [
    {
      "page": 1,
      "status": "complete",
      "items": [
        {
          "kind": "home_title",
          "text": "화면에서 전체를 확인한 제목",
          "list_position": 1
        }
      ]
    }
  ]
}
```

### 닫힌 필드

| 객체 | 필수 필드 | 선택 필드 |
|---|---|---|
| 최상위 | `schema`, `captured_at`, `source`, `pages` | 없음 |
| `source` | `directory_no`, `group_id`, `page_start`, `page_end` | 없음 |
| `page` | `page`, `status`, `items` | `reason` |
| `item` | `kind`, `text`, `list_position` | 없음 |

- `kind`는 `home_title`만 허용한다.
- `page`는 요청 범위 안의 양의 정수이고 중복될 수 없다.
- `list_position`은 한 페이지 안에서 중복될 수 없다.
- `complete` 페이지는 제목이 하나 이상 있어야 한다.
- `unavailable` 페이지의 `items`는 비어 있어야 한다.
- `page_end`는 `page_start`보다 작을 수 없고 한 번의 범위는 최대 50페이지다.
- 게시물 URL·작성자·프로필·본문·DOM·쿠키는 저장하지 않는다.

## 페이지 상태

| 상태 | 의미 |
|---|---|
| `complete` | 주요 피드 영역의 제목을 끝까지 확인함 |
| `partial` | 일부 제목 잘림, 지연 로딩, 영역 판별 불확실성이 있음 |
| `manual_partial` | 사용자 제공 스크린샷·텍스트처럼 화면 일부만 제공됨 |
| `unavailable` | 오류, CAPTCHA, 구조 변경 등으로 제목을 확인하지 못함 |

UI에서 제목 전체 문구를 확인하지 못했으면 추측해 채우지 않는다. 해당 제목을 제외하고 페이지를 `partial`로 기록한다.

## 출력 — `naver-blog-home-pattern-pack/v1`

```json
{
  "schema": "naver-blog-home-pattern-pack/v1",
  "captured_at": "2026-09-13T10:30:00+09:00",
  "analysis_status": "complete",
  "coverage": {
    "requested_pages": 10,
    "observed_pages": 10,
    "complete_pages": 10,
    "partial_pages": 0,
    "unavailable_pages": 0,
    "missing_pages": []
  },
  "titles_observed": 100,
  "titles_unique": 100,
  "pattern_denominator": "unique_titles",
  "length": {"average": 34.5, "minimum": 5, "maximum": 67},
  "patterns": [],
  "sensitivity_flags": [],
  "limitations": []
}
```

패턴과 민감도는 고유 정규화 제목을 분모로 계산한다. 같은 제목이 여러 페이지에 나오면 `titles_observed`에는 모두 포함하되 `titles_unique`와 패턴 분모에서는 한 번만 센다.

출력에는 다음을 넣지 않는다.

- 원본 제목 또는 일부 문구
- 게시물 URL과 작성자
- 키워드 추천, 검색량, CTR, 예상 조회수
- 원본 제목에서 추출한 고유명사 목록

## 분석 상태

- 모든 요청 페이지가 존재하고 모두 `complete`이면 `complete`다.
- 제목은 있으나 누락·부분·수동·오류 페이지가 있으면 `partial`이다.
- 관찰한 제목이 하나도 없으면 `unavailable`이다.

`complete`도 검색 수요나 네이버 전체 인기의 완전성을 뜻하지 않는다. 요청한 페이지 범위를 화면에서 완전하게 관찰했다는 뜻일 뿐이다.

## 실행

```bash
python3.11 -B scripts/analyze_home_titles.py \
  --input /absolute/private/blog-home-snapshot.json \
  --output /absolute/private/blog-home-pattern-pack.json
```

원시 입력은 `.creator-advisor-private/` 또는 `outputs/creator-advisor-private/`처럼 Git에서 제외된 경로에 저장한다.
