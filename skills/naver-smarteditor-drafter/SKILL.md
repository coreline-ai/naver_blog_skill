---
name: naver-smarteditor-drafter
description: 완성된 Markdown 또는 구조형 JSON을 네이버용 정본으로 검증하고, 명시적인 SmartEditor 입력·임시저장 요청이 있을 때 한 편씩 작성·저장·재열기 검증한다. 네이버 초안 사전검증·입력·중단 후 재개에 사용한다. 새 원고 창작·이미지 생성·공개 발행은 담당하지 않는다.
---

# Naver SmartEditor Drafter

완성 원고의 준비·입력 담당이다. 기본은 로컬 검증이며 브라우저 변경은 명시적 사용자 요청 안에서만 수행한다. 시리즈 전체 준비·검수는 총괄 스킬에서 연결할 수 있으나 이 스킬의 단독 변환도 유지한다.

## 모드와 준비

- `prepare`: scripts/build_naver_post.py로 정본·실제 이미지·요구 개수·범위를 검사한다. UI를 조작하지 않는다.
- `draft`: 사용자가 지정한 원고와 대상 블로그에 한 편씩 입력·임시저장·재열기 검증한다.
- `resume`: 실행 이벤트와 실제 현재 UI를 먼저 대조한다. 저장한 동일 버전은 재생성하지 않는다.
- `status`: 로컬 이력을 조회한다. 현재 브라우저를 확인했다고 표현하지 않는다.

입력 계약·실제 이미지 검사·지원 문법·불변 준비 출력은 [naver-post-v1.md](references/naver-post-v1.md)를 읽는다. Python3.11 및 scripts/requirements.txt의 Pillow가 필요하며 누락 시 자동 설치/검사 생략하지 않는다.

```bash
python3.11 -B /absolute/path/to/naver-smarteditor-drafter/scripts/build_naver_post.py \
  --project-root /absolute/project \
  --input-root /absolute/project/series \
  --output-root /absolute/project/runs --run-id prepared-new \
  --batch --episode-min 3 --episode-max 15 --expected-images 5
```

회차·이미지·태그 수는 실제 사용자 요구에 맞춘다. 태그 합성 문자열은 #·공백 포함100자 이하. 태그6개를 모든 글의 필수 조건으로 삼지 않는다.

하나라도 실패하면 전체 입력 큐를 시작하지 않는다. 유효 후보의 prepared_queue는 진단 자료이지 부분 실행 허가가 아니다. prepare 통과는 사실성 검수 완료나 UI 입력 권한을 뜻하지 않는다. 게시 본문·편집 메모를 분리하고 미검토 핵심 주장과 검수 대상 버전 불일치를 해소한 뒤 draft로 넘어간다. 단독 사용도 본문 검수 근거를 확인하되 작성 스킬이 설치돼 있다고 가정하지 않는다.

## UI 실행 전 필수 자료

- 사용자가 지정한 블로그·범위와 완료된 본문/콘텐츠 검수 근거.
- 현재 정본, preflight, asset-integrity 및 완료 manifest의 무결성 확인.
- 별도 실행 저장소와 기존 저장 이력/버전 대조.
- 현재 지원 브라우저 도구의 문서·로그인·입력/업로드/관찰 기능.

실제 입력 때만 [SmartEditor 런북](references/smarteditor-runbook.md)을 읽고 따른다. Node의 scripts/smarteditor_checks.mjs는 정본 렌더 계획과 실제 관찰값을 검사할 뿐 브라우저에 연결하지 않는다. 기대값을 관찰값으로 복사하지 않는다.

## 필수 입력·저장 경계

1. 모든 본문·미디어·복구 대기 UI까지 빈 화면을 확인한다.
2. render_plan steps 순서대로 처리하고 이미지 지점에서만 해당 로컬 파일을 업로드한다. 업로드 직전 이미지 해시를 재확인한다.
3. H2는 말풍선형, 핵심 요약은 제목 라벨의 라인형 인용구. 이미 적용된 인용구를 반복 변환하지 않는다. 원 selector의 유일성과 선택된 전체 문단을 확인한다.
4. 표·목록·H3·인라인 code의 대체 서식을 기록하고 bold·본문 의미와 순서를 검증한다. 태그 설정 진입과 최종 공개 발행을 엄격히 구분한다.
5. 제목·전체 본문·서식·이미지 위치·태그를 대조한 뒤 임시저장한다. save_acknowledged와 reopened_verified를 구분한다.
6. 저장 초안을 실제 다시 열어 내용·이미지·태그를 검증하고 새 글쓰기 전체 빈 상태를 확인한 후 다음 회차로 간다.

한 블로그의 작성자는 하나다. 비공개 API·내부 에디터 모델 직접 수정·기존 글 자동 삭제·공개/예약 발행을 수행하지 않는다.

## 실행 이력과 재개

[중단·복구 계약](references/recovery-and-safety.md)을 읽고 scripts/execution_state.py의 이벤트 저장소를 사용한다. 부작용 전 intent, 후 실제 결과를 기록한다. 준비 run은 불변이며 --force는 resume 수단이 아니다.

기존 내용·대상 불일치·업로드 미확인·저장 불확실성·부분 관찰·로그인 만료·식별 불가 화면에서는 다음 회차를 중단한다. 살아 있는 도구 핸들이 있으면 그 핸들을 확인/대기한다. 과거 saved_verified는 legacy_saved_reported로만 가져오고 자동 재열기 완료 승격이나 중복 작성을 하지 않는다.

## 보고

준비·콘텐츠 검수·입력·ack·재열기·빈 화면 상태를 구분하고, 실제 확인한 회차/제목, 이미지/태그, 대체 서식, 오류와 재개 지점을 간결하게 보고한다. 미관찰값은 unknown/null이다. simulation을 실제 UI 성공으로, 로컬 스킬 폴더를 전역 설치로, 임시저장을 공개 발행으로 표현하지 않는다.
