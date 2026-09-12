# `naver-post/v1` 계약

Markdown과 구조형 JSON을 동일한 순서형 블록으로 바꾸어 SmartEditor 입력의 정본으로 사용한다. 모든 블록은 회차 안에서 고유한 `id`를 가지며 배열 순서가 실제 입력 순서다.

```json
{
  "schema": "naver-post/v1",
  "episode": 3,
  "source": "/absolute/episode-03.md",
  "title": "흔들린 사진과 실패한 사진을 빠르게 골라내는 기준",
  "blocks": [
    {"id": "b001", "type": "image", "path": "/absolute/01-cover.png", "alt": "스마트폰 사진을 검토하는 모습"},
    {"id": "b002", "type": "heading", "level": 2, "text": "1. 실패한 사진은 한 종류가 아닙니다", "style": "quotation_bubble"},
    {"id": "b003", "type": "paragraph", "text": "본문"}
  ],
  "tags": ["사진정리", "스마트폰사진"]
}
```

## 블록

| `type` | 필수 필드 | SmartEditor 기본 처리 |
|---|---|---|
| `heading` | `level`, `text`, `style` | H2는 `quotation_bubble`, H3는 보조 소제목 |
| `paragraph` | `text` | 기본 본문 문단 |
| `image` | 절대 `path`, `alt` | 현재 블록 위치에서 로컬 파일 업로드 |
| `list` | `style`, `items` | `unordered`, `ordered`, `checklist` 목록 |
| `table` | `columns`, `rows` | 모바일용 레이블 문단 또는 표 컴포넌트 |
| `callout` | `variant`, `title`, `text`, `style` | 요약은 기본 `quotation_line` |
| `divider` | 없음 | 구분선 컴포넌트 |

`paragraph`, `heading`, 목록 항목은 선택적으로 `marks`를 가진다. 각 mark는 Markdown 표시를 제거한 최종 `text` 기준의 `start`, `end`, `type`(`bold` 또는 `code`)을 기록한다.

## Markdown 규칙

- H1은 정확히 하나이며 제목으로 분리한다.
- H2는 `heading(level=2, style=quotation_bubble)`로 변환한다.
- H3는 `heading(level=3, style=subtitle)`로 변환한다.
- `**핵심 요약**`은 `callout(variant=summary, style=quotation_line)`이다.
- `**다음 편 예고**`, `**시리즈 활용 방법**`, `**함께 생각해볼 질문**`은 라인형 레이블 callout이다.
- `**태그**` 이후 `#태그` 문자열은 본문에서 제거하고 `tags`로 분리한다.
- 이미지의 Markdown 위치가 업로드 위치다. 상대경로는 원고 파일 기준으로 해석한다.
- 표, 순서 목록, 불릿 목록의 텍스트와 순서를 보존한다.

## 구조형 JSON 규칙

최상위 `title`과 `content` 또는 `blocks`를 받는다. 태그는 `tags` 또는 `seo_tags`를 사용한다.

- `steps` → `list(style=ordered)`
- `checklist` → `list(style=checklist)`
- `list` → `list(style=unordered)`
- `comparison` → `table(columns=[항목, 설명])`
- `callout` → 같은 형식의 `callout`; `summary`는 라인형
- `image_prompts`는 업로드 파일이 아니다. 실제 `image` 블록의 로컬 경로를 대체하지 않는다.

## 검증

- 이미지 파일은 존재하는 일반 파일이며 지정한 프로젝트 루트 안에 있어야 한다.
- `..`를 포함한 이미지 경로와 프로젝트 밖으로 해석되는 경로를 거부한다.
- 제목, 블록 ID, 태그는 비어 있을 수 없다.
- 태그는 중복될 수 없고 `#`과 공백을 제거한 값으로 정규화한다.
- 태그 출력 문자열 `#태그1 #태그2`는 100자 이하여야 한다.
- 기대 이미지·태그 수를 CLI에 지정했다면 정확히 일치해야 한다.

## 엄격한 입력과 손실 방지

- canonical `schema: naver-post/v1` 입력은 다시 Markdown 파싱하지 않는다. `source`, block id, marks를 포함해 보존하고 미지원 필드는 거부한다. `source`는 절대경로 provenance이며 새 입력 JSON 경로로 바꾸지 않는다.
- canonical top-level은 `schema/episode/source/title/blocks/tags`. 회차는 양의 정수 또는 단독 원고의 null이며 bool·문자열 숫자는 정수로 변환하지 않는다.
- 파일명·상위 회차 폴더·내부 회차가 명시되면 일치해야 한다. 목록 id가 같거나 image path가 중복되면 실패한다.
- 제목·text·tags·level·style의 타입을 강제 변환하지 않는다. canonical marks는 최종 텍스트의 Unicode code point 기준 `[start,end)`이며 범위 밖, 중복 및 같은 type의 겹침을 거부한다. UTF-16 UI 선택에는 명시적 변환이 필요하다.
- image는 `caption`을 선택적으로 보존한다. checklist item의 선택적 `checked`는 boolean이다. unsupported style/variant는 임의 기본값으로 대체하지 않는다.
- `tags`와 `seo_tags`는 배열만 받는다. 공백/# 포함 합성 태그 문자열은 100자 이하이다. Markdown의 태그 영역 뒤에는 태그와 구분선만 허용한다.
- 게시 제외 메모·관리용 시리즈 코드가 본문에 섞이면 `EDITORIAL_BOUNDARY_AMBIGUOUS`로 실패한다. 본문 전용 파일을 제공해야 하며 문자열 삭제로 경계를 추측하지 않는다.
- Markdown H4 이상, fenced code, HTML, 참조 링크, 중첩 목록, inline image, 미완료 이미지 슬롯은 거부한다. 일반 링크는 설명과 http/https URL을 `설명 (URL)`로 보존하고 대체 경고를 남긴다. 인라인 italic은 plain text 대체 경고를 남긴다.
- H3·목록·표에는 문서화된 text-render 대체 경고가 있다. 모든 네이티브 서식을 보존한다는 뜻이 아니다. 정본의 표 값·목록 순서는 유지한다.

## 실제 이미지와 콘텐츠 버전

`scripts/asset_integrity.py`는 Pillow로 실제 PNG/JPEG를 verify + decode한다. 설치 의존성은 `scripts/requirements.txt`에 있으며 부족하면 검사 생략 없이 `DEPENDENCY_MISSING`으로 종료한다. 자동 설치하지 않는다.

정적 PNG/JPEG만 지원하며 확장자·디코딩 형식 일치, 파일 20 MiB·40 million pixels 이하를 확인한다. 이 수치는 자체 안전 상한이지 네이버 공식 한도가 아니다. 이미지마다 path·sha256·bytes·format·width·height를 `asset-integrity.json`에 보존한다. 업로드 직전 `verify_asset`으로 버전이 동일한지 확인한다.

`content_revision`은 경로·시각을 제외한 정본 의미, 이미지 해시/크기와 순서, 태그, render policy에서 계산한다. 동일 경로에서 이미지가 교체되면 revision이 달라진다. 원본 파일 해시는 provenance로 별도 기록한다.

preflight에는 실질 본문이 필요하다. paragraph/list/table/callout 본문은 인정하지만 제목·이미지·레이블·태그만으로 통과하지 않는다. 이는 정보성 준비 계약이며 SEO 고정 글자 수 규칙이 아니다. preflight의 `content_review=not_evaluated`는 내용의 사실성 검수를 아직 수행하지 않았다는 의미다.

## 준비 CLI 출력 v2와 불변성

기존 canonical `naver-post/v1`은 유지하지만 준비 보고서는 `naver-smarteditor-run/v2`, `naver-smarteditor-preflight/v2`다. UI 저장 이력 필드 `last_saved_episode`를 준비 보고서에서 제거했다. 이전 v1 실행 보고서를 이 CLI로 갱신하지 않는다.

- 요청 min/max가 모두 있으면 연속 요청 집합을 검사하여 누락을 `missing`으로 보고한다. 임의 sparse 집합은 총괄 manifest에서 지정한다.
- 일부 실패 시 전체 `queue=[]`이며 `prepared_queue`는 진단용 통과 후보다. 일반 준비 CLI의 `ui_executable=false`는 콘텐츠 검수/실행 권한을 승인하지 않았다는 뜻이다.
- 새 run-id에만 결과를 작성한다. 일시 staging에 정본·무결성·보고서를 쓴 뒤 전체 준비 성공일 때 `complete.json`을 마지막에 확정하고 run 폴더로 전환한다. 완료 marker의 파일 해시도 실행 전에 검사해야 한다.
- `--force`는 기존 산출물과 완전히 동일한 순수 준비 run을 읽기 재사용할 때만 허용한다. 원고 변경·레거시 저장 보고서·추가 실행 이력이 있으면 `IMMUTABLE_RUN`으로 중단하며 파일을 바꾸지 않는다. resume 기능이 아니다.
- run id는 ASCII 영숫자로 시작하는 단일 안전 세그먼트다. 점 경로·경로 구분자·symlink 탈출은 거부한다. 중단된 staging/잠금을 무조건 삭제해 재시도하지 않는다.
- 종료 코드: 0=전체 구조 준비 통과, 1=회차 오류/누락, 2=호출/경로/기존 결과 충돌 등 실행 오류. 어떤 코드도 실제 저장 성공을 의미하지 않는다.

## 시리즈 연동용 공개 함수 보완

`build_post(source, project_root, markdown_text=...)`는 승인된 슬롯 삽입기의 메모리 합성 결과를 원래 Markdown source 경로로 변환한다. 기존 두 인수 호출과 canonical 재입력은 그대로 유지한다. `.json/.txt`에는 markdown_text를 제공할 수 없다. source_sha256은 원본 바이트이며 합성 결과의 의미·이미지는 content_revision으로 확인한다.

독립 이미지 블록의 angle-bracket 링크 `![설명](</absolute/path/image.png>)`는 지원한다. 경로 검증 없이 HTML로 취급하거나 본문에 HTML을 허용하는 예외가 아니다. H2/style=quotation_bubble, H3/style=subtitle 조합을 검사하며 렌더할 수 없는 혼합 조합은 거부한다. `load_json_object`는 공유 strict JSON 로더이고 중복 키·비유한 수를 거부한다.
