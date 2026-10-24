# 단일 네이버 글

new/rewrite에서 현재 Codex가 작성한다. Python에 LLM/이미지 클라이언트를 추가하지 않는다.

유형 auto는 [제목 중심 자동 구조](../../../references/title-driven-writing-style.md)에 따라 제목의 독자 의도를 의미로 판단한다. 최종 helper 결과를 article record payload의 `style_selection`에 넣는다. expert/troubleshooting도 명시 선택 가능하다. 유형과 개인 말투, 이미지 표현 유형은 서로 독립적이다.

새 자료 기반 정보형·전문 해설형·방법형·비교형·문제 해결형·체크리스트형은 [공통 블로그 본문 참고 흐름](../../../references/blog-research-workflow.md)을 본문 작성 전에 적용한다. 기본 section-blog 5개이며 최초 요청의 명시 검색 경로·참고 수·비활성화를 우선한다. 재작성은 검색 보완 명시 시에만 적용한다. 참고 자료·분석 메모는 작업 영역에 분리하고 원고를 기존 article 기록으로 등록한다. 새 조사 질문·세션 필드·record type을 추가하지 않으며 이미지의 requested_count와 참고 수를 공유하지 않는다.

- 주제·독자·유형·문체·분량·서식과 실제 자료를 사용한다. 시리즈 writer 전체를 호출해 15편·3,000자 최소·다음 편 예고를 적용하지 않는다.
- short/medium/long은 약 800~1,200 / 1,500~2,200 / 2,500~3,500 공개 본문자 참고 목표다. 사용자 수치 우선이며 SEO/완료 게이트가 아니다.
- profile은 기존 docs/naver-blog-style-profile.md를 읽고 입력 사본을 보관한다. 이번 명시 선택이 우선하며 프로필을 갱신하지 않는다.
- 경험 없는 후기·방문 기록을 만들지 않는다. source-based는 information으로 전환한다. 시점에 따라 바뀌는 사실은 현재 근거를 확인하고 출처를 남긴다.
- 한 H1과 읽기 쉬운 문단/소제목의 UTF-8 Markdown으로 저장한다. 내부 상태·옵션·작업 메모는 공개 본문과 분리한다.
- rewrite는 원본을 보존하고 새 버전에 저장한다. 이미지 장수를 위해 사실·반복 문장을 추가하지 않는다. 원고를 재구성하면 다시 사용 선택을 받는다.

이미지 슬롯·해시를 확정하기 전에 [본문 표시 품질](../../../references/article-presentation-quality.md)을 적용한다. build_post/body_metrics로 구조·실제 분량을 기록하고 drafter preflight로 출처 배치·중복·표·개행 보존을 검사한다. 기본은 말미 출처이며 이번 명시 inline 요청만 해당 정책을 선택한다. warnings와 의미 검수·UI 검수를 구분한다. 새 원고 확인 전 이미지를 실행하지 않는다.

새 글/재작성의 제목 선정은 [현재 루트 작성 지침](../../../SKILL.md)과 [기존 naver-title](../../naver-title/SKILL.md)을 적용한다. 제목 후보·선정 근거는 메모로 분리하고 H1과 본문을 확정한 뒤 article을 등록한다. 이미지만 처리하는 원고는 기존 제목을 유지한다. 새 제목 선택 질문이나 title schema를 추가하지 않는다.
