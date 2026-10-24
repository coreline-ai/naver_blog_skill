# 질문 흐름

질문은 현재 옵션·파일 상태에서 계산한다. 최초 요청의 확정 값은 건너뛰고 빈 답은 확정하지 않는다. 한 응답은 질문 또는 작업 하나다.

| ID | 값 | 조건 / 다음 구간 |
|---|---|---|
| task_mode | new/rewrite/images-only/edit-existing | 주제/원고/편집 대상 |
| topic | 자유 텍스트 | new만 → 작성 옵션 |
| source_article | 실제 원고 경로 | rewrite/images-only → 원고 작업 |
| audience | beginner/general/experienced 또는 자유 입력 | new/rewrite → article_type |
| article_type | auto/information/comparison/howto/expert, 자유 입력 review/place/story/checklist/troubleshooting | new/rewrite → tone. auto는 제목에 맞춰 자동 선택 |
| tone | plain/friendly/professional/profile 또는 자유 입력 | profile 파일 변경 없음 → length |
| length | short/medium/long 또는 양의 글자 수 | 사용자 분량 우선 → format_preset |
| format_preset | auto/clean/magazine/review, 자유 입력 comparison/checklist/emotional | 기존 enum → 경험 근거 |
| experience_basis | 실제 근거 텍스트, source-based 또는 `{type,evidence}` | review/place/story 또는 auto의 체험 제목. source-based는 information 전환하되 최종 제목의 허구 체험 약속은 별도 차단. 가정 사례는 illustrative로 구분 |
| article_review | use/revise/change | 새 원고만. images-only는 사용으로 처리 |
| article_change | 작성 옵션 key | change 후 해당 질문만 다시 |
| image_action | none/prompt-only/generate/use-files | images-only는 none 제외 |
| presentation | standard/info-slide/mixed | 이미지 처리 시 |
| requested_count | 1/3/5/auto 또는 양의 정수 | auto 선택은 총 5장 |
| aspect_ratios | 선택 객체: cover/inline → 4:5·1:1·16:9 | 최초 요청·직접 change 또는 비율 변경 메뉴에서만 확인. 기존 세션의 필수 질문 아님 |
| additional_requirements | none 또는 자유 입력 | 미확정 시만 |
| reference_use | no/yes | yes → path/instructions |
| reference_path | 실제 이미지 경로 | 참조 사용 시 |
| reference_instructions | default 또는 자유 입력 | 참조 사용 시 |
| image_plan_review | use/change | 유효한 N슬롯 계획 이후 |
| image_change | 이미지 옵션 key | 조건 변경 선택 시 |
| image_review | use/edit/pause | 파일 검사·시각 QA 이후 |
| edit_slot | 현재 슬롯 ID | 특정 이미지 수정 시 |
| edit_target | 실제 원본 이미지 경로 | 원고 없는 편집만 |
| edit_instruction | 실제 변경 지시 | 편집 작업 |
| failure_resolution | change-options/use-files/pause | 보정 한도 초과 |

위치 불명확 시 세션 생성 전 저장 위치만 확인한다. 최초 복수 옵션은 initial-options로 전달한다. 모호한 복수 선택은 같은 질문에서 확인한다. 문구 전체가 아니라 key/value·분기·행동을 검증한다.

정보 슬라이드는 표지까지 한국어 제목·요점 2~3개를 사용하며 비율 미지정 시 4:5·권장 1080×1350이다. `aspect_ratios={"cover":"1:1","inline":"16:9"}`를 지정하면 표지는 정사각형, 본문은 가로형 정보 슬라이드로 만든다. 한 역할만 지정하면 다른 정보 슬라이드는 4:5이며 빈 객체는 비율 지정을 해제한다. 비율 선택을 하지 않은 기존 세션에 추가 질문을 끼우지 않는다. helper는 제목 34/요점 52 UTF-16 units의 첫 유효 문장을 사용한다. 같은 소제목의 동일 요점은 재설계한다. 원고 유지 모드에서 재구성이 필요하면 수량 조정/재작성 전환을 확인한다.
