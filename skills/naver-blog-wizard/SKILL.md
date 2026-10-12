---
name: naver-blog-wizard
description: "네이버 단일 글 작성과 이미지 옵션을 한 번에 하나씩 선택하는 문답형 스킬. 옵션을 차례로 질문해줘, 문답형 블로그 작성처럼 선택을 확인하며 진행할 때 사용한다. 개인 문체 인터뷰·시리즈·네이버 입력과 발행은 기존 별도 흐름을 사용한다."
---

# 네이버 블로그 문답형 글·이미지

한 질문에 답이 확정되면 다음 질문으로 이동한다. 현재 Codex가 글쓰기·이미지 작업을 수행하고 Python은 상태·파일·계약을 검증한다. 일반 주제 자동 완성은 [기존 흐름](../../references/topic-image-completion-workflow.md)을 유지한다.

## 시작과 질문

1. [질문 흐름](references/question-flow.md)을 읽고 최초 요청의 확정 옵션을 정규화한다. 불명확한 답은 같은 질문에서 확인한다. 제공한 옵션·같은 생성 권한을 반복 질문하지 않는다.
2. 사용자 작업 영역이 명확하면 그곳에 세션을 만든다. 스킬 소스에는 원고를 저장하지 않는다. 위치가 불명확할 때만 저장 위치 하나를 확인한다.
3. `scripts/wizard_session.py init --work-root ROOT --initial-options FILE`로 시작한다. 옵션 JSON은 실제 요청에서 확정한 값만 담는다.
4. `next --session FILE`의 question 하나만 표시하고 답을 기다린다. 선택지는 보통 동작이 다른 3~5개와 자유 입력을 허용하며 이진 질문은 두 선택으로 충분하다. 미응답·default 표시는 답이 아니다.
5. canonical value를 `answer`에 question_id/expected_revision과 전달한다. 앞선 선택은 change, 중단/재개는 pause/resume을 사용한다. [세션 계약](references/session-contract.md)에 명령과 payload가 있다.

## action 처리

- write_article/rewrite_article: [단일 글 지침](references/single-post-writing.md)으로 별도 Markdown을 작성한다. 원문을 보존하고 메모를 분리해 article 기록을 등록한다. 새 원고는 사용 선택을 기다린다.
- use_source_article: 실제 원고 사본을 준비한다. 텍스트는 확인한 제목과 원문을 Markdown으로 저장한다. 그대로 사용하라는 원고는 승인 질문을 반복하지 않는다.
- design_slots/revise_slot_plan/revise_slot_metadata: N개의 구체 설명 목적과 장면을 정하고 원고 사본에 독립된 `<!-- naver-image:ID -->` 줄을 넣는다. `{"slots":[...]}` JSON과 사본을 slots 기록으로 등록한다. metadata 수정에서는 지정 alt만 바꾼다. 본문·공백 변경을 삽입으로 숨기지 않는다.
- prepare_plan: `wizard_artifacts.py prepare-plan --session FILE`을 실행해 반환 payload를 plan 기록으로 등록한다. 외부 참고 파일에 대해 change가 반환되면 reference_path를 change로 정규화한 뒤 다시 실행한다. N은 표지 포함이다. info-slide는 표지까지 슬라이드, mixed만 일반 표지다. requires_design도 payload를 plan 기록으로 등록하면 다음 작업이 design_slots로 돌아간다. 요점 부족/반복은 재설계한다.
- generate_image/edit_image/repair_image: imagegen 스킬과 현재 이미지 도구 지침을 따른다. effect-intent를 먼저 기록하고 실제 도구 파일/결과를 effect-result로 등록한다. 참고 이미지가 있으면 plan.reference.path를 실제 도구의 참조 입력에 전달한다. 편집은 실제 원본을 확인해 전달한다. 계획만으로 생성 완료를 보고하지 않는다.
- import_image: 실제 사용자 파일을 effect-result로 등록한다. 생성 provenance를 만들지 않는다.
- visual_review: 실제 이미지를 보고 한국어 문구·사실성·비율·모바일 가독성·문맥·묶음 차별성을 검사한다. slot_id/asset SHA/passed/관찰 notes를 등록한다. 자동 파일 검사로 시각 QA를 대체하지 않는다. 실패 슬롯은 한 번 보정 후 해결 선택을 묻는다.
- compose_article: 승인 파일·사용 선택 이후 `wizard_artifacts.py compose --session FILE`을 실행하고 package 기록을 등록한다. 원고·N장·manifest·합성 원고를 전달한다.
- reconcile: 미완료 intent의 실제 반환과 파일을 먼저 확인한다. 불명확한 결과를 자동 재생성하지 않는다. 발견 결과 또는 명확한 실패를 기록한다.
- repair_artifacts: 실제 검사 실패에서 repair 기록의 target으로 해당 메타데이터만 무효화하고 다음 작업에서 새 버전을 등록한다. 불명확한 intent를 먼저 reconcile한다. 정상 파일을 삭제하거나 문답 전체를 재시작하지 않는다.

글만은 확정 원고, 프롬프트만은 검토 계획, 생성/내 파일은 실제 파일·시각 QA·합성까지 완료한다. 원고 없는 편집은 검수 파일로 끝난다. package_verified는 파일·합성 검증이며 생성/QA 진위 인증이 아니다. 미실행·누락·미검수는 미완료로 알리고 파일을 보존한다.

저장소 공통 scripts와 sibling 스킬이 필요하다. 하위 폴더만 복사해 자립한다고 안내하지 않는다. 네이버 로그인·입력·저장·발행은 수행하지 않는다.
