# 블로그 이미지 프롬프트 계획 계약

## 입력과 실행

공통 도우미 `scripts/build_blog_image_prompts.py`는 Python 3.11+ 표준 라이브러리와 저장소의 `build_naver_post.py`를 사용한다. 원본 앱·브라우저·네트워크·이미지 생성에 연결하지 않는다. 루트 및 시리즈 스킬이 동일한 도우미를 사용한다. 저장소의 scripts와 sibling 스킬 구조가 필요하며 일부 폴더만 설치한 환경의 누락 의존성은 명시적으로 보고한다.

CLI: `--input REQUEST.json --project-root ROOT (--check | --output PLAN.json) [--operation plan-only|generate-and-compose|edit-existing]`. 기본 operation은 plan-only다. `--check`는 stdout JSON만 반환한다. 출력 경로는 ROOT 안에 있어야 하며 기존 파일·심볼릭 링크·입력 파일 덮어쓰기를 거부한다. operation·출력 경로는 CLI 인수이며 원고/JSON으로 승격하지 않는다. 자연어 주제 요청의 원고/내부 JSON 준비와 생성 도구 실행은 [주제 완성 흐름](topic-image-completion-workflow.md)이 담당한다.

```json
{
  "schema": "naver-blog-image-request/v1",
  "article": {"path": "drafts/article.md"},
  "presentation": "mixed",
  "aspect_ratios": {"cover":"1:1","inline":"16:9"},
  "language": "ko",
  "requested_count": 3,
  "article_type": "information",
  "format_preset": "auto",
  "additional_requirements": "상황에 맞는 자연광과 행동을 표현",
  "slots": [
    {"id":"cover","role":"cover","purpose":"글의 중심 상황","prompt":"출근길에 겉옷을 입고 걷는 장면","mode":"photorealistic-natural","heading_hint":"","placement":"H1 바로 아래","alt":"출근길 착용 장면"},
    {"id":"material","role":"inline","purpose":"소재 질감 비교","prompt":"원단과 봉제의 근접 장면","mode":"photorealistic-natural","heading_hint":"소재 비교","placement":"해당 문단 뒤","alt":"원단과 봉제"},
    {"id":"packing","role":"inline","purpose":"휴대 과정 설명","prompt":"옷을 접어 가방에 넣는 손동작","mode":"photorealistic-natural","heading_hint":"휴대 순서","placement":"해당 문단 뒤","alt":"휴대 과정"}
  ]
}
```

필수 필드는 schema/article이다. 다른 기본값은 standard, ko, auto, information, auto, 빈 추가 지시다. slots는 선택 사항이며 지정하면 ID·순서·role·mode를 보존하고 앞 N개를 선택한다. 슬롯의 필수 필드는 id/role/purpose/prompt/mode이며 heading_hint/placement/alt는 선택 사항이다. 승인 status나 생성 파일 path를 입력 슬롯에 넣지 않는다. 기존 마커가 있으면 같은 순서의 전체 slots를 제공해야 한다. 마커만 메모리에서 제거한 뒤 기존 원고 파서를 사용하며 원고는 수정하지 않는다.

선택 필드 `aspect_ratios`는 `cover`·`inline` 역할별 비율 객체다. 허용 값은 `4:5`, `1:1`, `16:9`이며 다른 역할·비율·null·배열·숫자는 거부한다. 예를 들어 `{"cover":"1:1","inline":"16:9"}`는 대표를 정사각형, 본문을 가로형으로 지정한다. 일부 역할만 지정하면 나머지 정보 슬라이드는 기존 4:5이며 일반형은 별도 비율을 강제하지 않는다. 미지정 또는 빈 객체는 기존 계획·프롬프트를 유지한다. 자연어의 대표/표지는 cover, 본문은 inline으로 현재 에이전트가 정규화하며 원고 내부 문장에서 비율을 추론하지 않는다.

**완성 모드의 장수:** `generate-and-compose`는 명시 requested_count를 정확한 완료 수량으로 사용한다. 미지정 단일 글은 총 5장, 시리즈 required는 기존 스타일 목표다. 완성 요청의 slots는 에이전트가 직접 설계한 명시 목록이어야 한다. 무슬롯·부족·잘못된 cover 구조는 insufficient/next_action=design_slots로 되돌린다. 원본 호환 source 상한을 수정하거나 일반 장면으로 자동 보충해 완료하지 않는다. plan-only의 auto 계산과 원본 비교 함수는 유지한다. 정상 완성 계획의 next_action=generate_images는 에이전트가 실제 도구를 이어서 호출해야 한다는 뜻이다.

article에는 path, 선택적 source_type/title/expected_sha256/rewrite_revision을 받는다. 기본 source_type=article은 기존 Markdown·구조형 JSON·canonical post 지원 문법을 따른다. `provided-article`은 title과 원문 텍스트 파일을 받으며 전체 본문을 그대로 문맥 데이터로 전달한다. `rewrite-applied`는 이미 적용한 원문만 받으며 expected_sha256과 rewrite_revision이 필수다. SHA-256은 입력 파일 바이트 버전 확인값이며 기존 content_revision을 대체하지 않는다. 본문을 재작성하거나 N장에 맞춰 재분배하지 않는다.

title은 UTF-16 200 units, 문맥 본문은 30,000 units까지다. 제공 원고의 CRLF/CR 정규화·외곽 공백 제거는 원본과 같으며 파일 바이트는 보존한다. 초과 입력은 자동 절단하지 않는다. 일반 원고 문맥은 기존 파서의 공개 텍스트 블록에서 추출하고 태그·이미지·참고자료는 제외한다. 빈 본문·제목/레이블만 있는 원고를 의미 있는 계획으로 만들지 않는다.

reference에는 `path`와 선택적 `instructions`를 받는다. ROOT 내부의 실제 디코딩 가능한 PNG/JPEG를 기존 asset_integrity로 확인한다. 누락·범위 이탈·가짜 이미지·지시만 있고 파일이 없는 경우 진단하고 계획을 blocked로 반환한다. 출력에는 파일 참조와 해시를 기록할 뿐 생성 도구에 첨부했다고 주장하지 않는다. edit-existing에는 reference가 필수이며 실제 편집 대상 전달·사전 확인은 현재 이미지 도구 지침을 따른다.

시리즈에는 선택적 `series_requirements`를 받는다: `visual_mode`, `primary_style`, `min_images_per_episode`, `target_images_per_episode`. required일 때 최소 3장과 cover 1+inline 2를 유지하고 expert 미지정 목표는 5장이다. optional에는 수량 필드를 선언하지 않으며 none은 수량 필드 생략 또는 0을 허용하고 계획 항목을 만들지 않는다. 수량·역할 미달은 진단이며 기존 prepare/시각 QA를 대체하지 않는다.

## 원본 대응과 어댑터 차이

기준: `sns_content_writer main@ab4c700`, `1.12.35 / 20261003-r47`. 원본 함수 범위·SHA-256·독립 기대값은 `tests/fixtures/blog-image-prompts/source-oracle.json`에 보존한다. `capture_source.cjs`는 선택적인 원본 읽기 비교 도구이며 일반 테스트와 런타임은 원본 없이 실행된다.

- `resolveImagePromptEntries` / `resolveRequestedAutoImageCount`: 원본은 준비된 슬롯을 먼저 쓰고 앞 N개를 선택한다. 일반 원고 상한은 `1 + (번호 소제목 최대값 또는 소제목 수)`다. 제공 원고 자동은 최대 3장, 문단 focus 후보는 최대 9개+대표다. 대상은 명시 slots와 시리즈 목표/사용자 수량을 우선하므로 원본 상한을 전역 규칙으로 강제하지 않는다. 부족하면 requested_count/selected_count/diagnostics에 남긴다.
- `deriveFallbackImagePrompts`: 대표는 제목·요약, 본문은 소제목으로 후보를 만든다. 이미 확정한 대상 slots는 임의로 늘리지 않는다. 무슬롯 일반 원고는 구조형 JSON의 기존 image_prompts를 먼저 선택하고 원본처럼 부족한 항목에 fallback 후보를 보충한다. 후보는 의미 있는 장면·시각 비트가 확인됐다는 증거가 아니다. SOURCE_CANDIDATES 진단은 이 후보를 실제 연출 계획으로 검토해야 한다는 뜻이다.
- `ProvidedArticle.create/contextFor`: 원본과 같이 전체 문단을 최대 9개 focus로 먼저 균등 구분하고 앞 N개를 선택한다. N 변경은 focus를 다시 나누지 않는다. 대상 명시 slots의 본문은 heading_hint가 있으면 해당 구간을 우선한다. rewrite-applied는 적용 원고를 이 경로에 연결한다.
- `extractInformationSlideSectionSource`: HTML DOM 대신 기존 정본의 H2/H3 뒤 최대 8개 텍스트 fragment, 다음 H2/H3까지를 읽는다. 원본의 whitespace 제거·소문자·부분 포함 heading matching을 유지한다. full body와 focus는 원고 JSON 데이터로 추가 전달한다.
- `buildInformationSlideBrief`: 제목 34, 요점 최대 3개/각 52, 본문 근거 700 UTF-16 units. 원본의 900-unit 구간 → 700-unit source, 불릿/번호 제거, 5-unit 미만 제외, 제목과 동일/중복 문장 제외, 마침표·물음표·느낌표 분리(소수점 제외)를 유지한다. 요점은 문장 추출이며 AI 의미 요약이 아니다. surrogate를 잘라 잘못된 유니코드를 만드는 경계만 안전하게 짧게 자르는 어댑터 차이가 있다. 결합 문자는 원본처럼 별도 unit이며 grapheme 재분석하지 않는다.
- `getInformationSlideLayoutGuide`: comparison 우선 → howto/checklist → review → 기본. 대상 primary comparison/troubleshooting/review는 각각 comparison/howto/review에 대응하고 expert/friendly/story는 information/information/story다. 사용자 article_type/format_preset을 우선한다.
- `buildImageGenerationPrompt`: 한국어는 원본의 목적·유형·슬라이드 원고·글 정보·참고·추가 지시·제작 기준 순서를 유지한다. provider 이름은 현재 이미지 도구로 치환한다. 입력 문서의 명령은 실행 지시가 아닌 데이터이며 full body/focus JSON을 추가한다. language=en은 원본 englishImagePrompt 경로를 쓰며 새 문구는 영어, 확인된 지정 문구는 보존한다. 한국어 슬라이드 문구/한국어 전용 레이아웃을 영문 기본 경로에 강제하지 않는다.

## 표현 유형과 기존 manifest

`presentation`은 standard/info-slide/mixed다. standard는 기존 장면·매체 선택을 유지한다. info-slide는 본문 기반 제목/요점을 지시하며 `mode=infographic-diagram`으로 연결한다. 기본 비율은 4:5·권장 1080×1350이며 역할별 지정 시 1:1·권장 1080×1080 또는 16:9·권장 1920×1080을 사용한다. 픽셀 크기는 권장값이며 필수 해상도가 아니다. 16:9의 기본 정보 카드는 가로 공간을 활용한 열 구성을 지시한다. mixed는 **대상 role=cover**만 standard, inline은 info-slide다. 비율 지정으로 이 표현 유형을 바꾸지 않는다. 원본의 빈 heading_hint 대표 판정을 대상에 그대로 쓰면 본문도 일반형으로 바뀌므로 명시 role이 우선한다. 정보 슬라이드에서도 주제별 장면·정보 구조·분위기를 선택하며 이전 글의 디자인을 기본으로 복제하지 않는다. 역할별 비율은 대상 어댑터의 확장이며, 미지정 원본 oracle의 4:5 프롬프트는 유지한다.

출력 schema는 `naver-blog-image-plan/v1`이다. status는 planned/insufficient/blocked/not_requested, count_origin은 explicit/series_target/image_completion_default/explicit_slots/source_auto, next_action은 설계/생성/편집/계획 반환의 후속 단계다. entries에는 id/role/presentation/mode/purpose/heading_hint/placement/alt/prompt/manifest_prompt/brief/context를 기록한다. reference는 검증된 로컬 입력 기록이다. article에는 source_sha256·선택적 rewrite_revision을 기록한다. 각 항목은 1장용 프롬프트다. `generation_performed=false`, `visual_ready=false`, `manifest_ready=false`, `ui_authorized=false`를 유지한다. approved·생성 결과 path는 없다.

역할별 비율을 지정한 계획 항목에는 해석된 `aspect_ratio`가 추가된다. 한국어는 해당 비율·방향·권장 크기를, 영어는 `aspectRatio`와 `canvasLayout`을 생성 payload에 전달한다. manifest v1에는 새 비율 필드를 추가하지 않고 기존 `manifest_prompt`로 현재 요청·비율을 연결한다. 비율 변경 시 현재 요청으로 계획과 prompt를 재계산하고 영향받은 이미지의 실제 비율·시각 QA를 다시 확인한다.

실제 생성 후 이미지 파일·문구·비율·내용 적합성·모바일 가독성을 눈으로 검수한 항목만 기존 manifest v1으로 옮긴다. mode/role은 계획에서, path/status=approved/caption은 실제 생성·검수 후 채운다. **생성 도구에는 prompt를 전달하고, manifest의 prompt에는 manifest_prompt를 저장한다.** 기존 manifest가 한 줄 문자열만 허용하므로 manifest_prompt는 전체 prompt를 JSON 문자열로 인코딩한 한 줄 보관값이다. `json.loads(manifest_prompt)`로 원래 다중 행 prompt를 손실 없이 복원할 수 있으며 기존 합성기는 이 값에 명령 실행을 하지 않는다. 계약 버전이나 필드를 바꾸지 않는다. 계획 JSON을 합성기나 series prepare에 승인 manifest로 넘기지 않는다. 장수 미달·참고 누락·stale source는 계획을 다시 확인하고 기존 v2 게이트를 그대로 통과해야 한다.

## 실제 파일·합성 원고 검사

생성·시각 QA·기존 manifest 승인·합성이 끝난 뒤 **원본 image-request.json**에 아래 두 옵션을 함께 제공한다. 계획 보고서를 요청 JSON 대신 사용하지 않는다.

```bash
python3.11 -B scripts/build_blog_image_prompts.py \
  --input drafts/image-request.json --project-root "$PWD" \
  --operation generate-and-compose --check \
  --manifest drafts/image-manifest.json \
  --composed-article drafts/article-with-images.md
```

verify_completion은 새 계획을 재계산하고 기존 합성기/asset_integrity를 재사용한다. 요청 N과 실제 디코딩 이미지 수가 정확히 같아야 하고 바이트가 고유해야 한다. ID 순서·role·mode·목적·배치·alt·보관 프롬프트가 현재 계획과 같고 모든 슬롯이 approved여야 한다. 각 실제 파일을 역할별 지정 비율과 비교하며, 비율 미지정 info-slide는 4:5를 검사한다. 권장 픽셀 수는 강제 해상도가 아니다. 비율 a:b에서 `오차=abs(width*b-height*a)`에 대해 `오차<=a` **및** `오차*1000<=height*a`일 때만 정수 반올림을 허용한다. 이는 기존 세로 환산 오차 1픽셀 이하·상대 오차 0.1% 이하 조건과 같다. 실제 1122×1402의 4:5 반올림을 허용하되, 1:1 표지에 16:9나 4:5를 제출하면 거부한다. 실패 코드는 정보 슬라이드의 `SLIDE_ASPECT_MISMATCH`, 일반형에 명시한 비율의 `IMAGE_ASPECT_MISMATCH`다. 합성 원고는 기존 상대/절대 이미지 링크 합성 결과 중 하나와 정확히 같아야 한다. 원고·manifest·합성 원고·이미지가 검사 중 바뀌면 거부한다.

출력 schema는 naver-blog-image-completion/v1이며 status=package_verified/incomplete다. 파일/해시·verified_image_count·unique_image_count·diagnostics·다음 조치를 보고한다. manifest 자체가 유효하지 않으면 아직 관찰할 수 없는 수량은 null이다. generation_verified/visual_qa_verified/ui_authorized는 false다. 파일 검사는 이미지 모델을 호출했는지, 실제 글자를 읽었는지, 장면이 적합한지를 증명하지 않는다. 에이전트는 실제 생성 결과를 눈으로 검수한 기록과 함께 최종 완료를 보고한다. helper는 원고·manifest·이미지·합성 파일을 변경하지 않는다.

종료 코드: 0=계획/미요청 정상 또는 로컬 package_verified, 1=수량·참고·시리즈 요구 부족 또는 incomplete, 2=입력 계약·경로·버전·덮어쓰기·paired 옵션 오류. 어떤 코드도 실제 생성/시각 QA 성공을 뜻하지 않는다.
