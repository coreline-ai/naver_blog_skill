# M5 울트라 정보 슬라이드 실검증 — 2026-10-23

상태: **신규 원고·실제 생성·시각 검수·최종 5장 삽입·로컬 패키지·ZIP 재검사·네이버 임시저장·재열기 검증 완료**.

사용자가 M5 울트라 원고를 새로 작성하도록 선택한 뒤 진행했다. 기존 M5 Max 원고·이미지·네이버 초안을 재사용하거나 변경하지 않았다. 대상 코드는 `main@0297abf`이며 이번 검증에서 기능 코드를 수정하지 않았다.

## 요청과 결과

| 항목 | 실제 결과 |
|---|---|
| 원고 | M5 울트라 맥 스튜디오, 로컬 AI 구매 전 4가지 |
| 기존 글 참고 | section-blog 첫 검색 화면에서 고유 블로그 본문 5개 실제 관찰, 짧은 발췌만 로컬 보관 |
| 사실 확인 | Apple 사양·발표, MLX·Ollama·ComfyUI 공식 문서 확인 |
| 표현 유형 | 대표·본문 모두 `info-slide`, mode는 `infographic-diagram` |
| 생성 도구 | built-in `image_gen`, CLI/API 우회 없음 |
| 실제 호출 | 신규 생성 5회 + 본문 슬롯별 가독성 편집 1회씩 총 4회 |
| 최종 채택 | 승인 고유 PNG 5개, 본문 삽입 5개 |
| 대표 | 1254×1254, 1:1 |
| 본문 | 각 1672×941, 16:9 정수 픽셀 반올림 검사 통과 |
| 이미지 처리 | 생성 도구의 반환 바이트 그대로 보관, 크롭·리사이즈 없음 |
| 로컬 원고 표시 | 인앱 브라우저 AX에서 제목·이미지 5개·표 2개·출처 링크 5개 확인 |
| 축소 검수 | 데스크톱 브라우저에서 CSS 표시 너비 375px로 상·하단 확인, 본문 보정 후 재확인 |
| 원고 사전검사 | `passed`; 확정 원고의 SHA-256 유지 |
| 패키지 검사 | 최종 요청·manifest·합성 원고의 paired CLI `package_verified` |
| 배포 ZIP | 임시 폴더로 추출 후 같은 도우미로 고유 5장·합성 결과 `package_verified` |
| 네이버 입력 | 사용자 요청으로 어사이드에서 제목·전체 본문·이미지 5장·네이티브 표 2개·링크 5개·태그 없음 입력 |
| 저장·재열기 | 임시저장 완료 알림과 저장 목록의 고유한 초안 확인 후, 빈 편집기에서 해당 초안을 실제 불러와 전체 검증 통과 |
| 저장 후 태그 | 설정 열기·읽기·닫기만 수행, 콘텐츠 전후 SHA-256 동일 |
| 완료 경계 | 새 빈 작성 화면 관찰·`can_advance` 통과·작성 잠금 해제, 공개·예약 발행 없음 |

## 장별 검수

| 장 | 설명 목적 | 시각 검수 |
|---|---|---|
| 1 표지 | 칩·메모리·호환성·총비용 네 판단 기준 | 정보 슬라이드 표지 유지, 제목·아이콘·요점 확인 |
| 2 칩 구성 | 기본 30 CPU/64 GPU와 상위 36 CPU/80 GPU | 공통 1.2TB/s 및 구성 수치 대조, 1회 글자 확대 |
| 3 메모리 | CPU·GPU 공유 공간과 운영체제·앱·모델·캐시 | 실측 비율을 암시하는 수치 없음, 1회 글자 확대 |
| 4 작업 | LLM·이미지·영상의 서로 다른 시험 조건 | 허위 속도·벤치마크 없음, 작은 부연 제거·핵심 요점 확대 |
| 5 구매 판단 | 주문·배송 확인, 총비용, 대표 작업 시험 | 즉시 재고·확정 납기·손익 보장 없음, 1회 글자 확대 |

초기 본문 카드의 일부 작은 보조 글씨를 375px 표시에서 발견했다. 본문 슬롯마다 기존 이미지를 참조한 편집을 한 번씩 실행했고, 제목·세 핵심 요점·사실을 유지하며 글자를 확대했다. 표지는 재생성하지 않았다. 최종 5개만 manifest와 원고에 채택했으며 이전 파일은 보존한다. 작은 장식 라벨은 핵심 정보의 유일한 전달 수단으로 쓰지 않고 같은 내용을 본문에도 남겼다.

## 실제 파일을 이용한 실패 경계

- 대표의 기대 비율을 16:9로 바꾼 대조 요청은 `SLIDE_ASPECT_MISMATCH`로 실패했다.
- 실제 5장을 요구 수량 4장으로 보고한 대조 요청은 `IMAGE_RESULT_INCOMPLETE`로 실패했다.
- 보정 전 manifest를 최신 요청에 연결하면 `PROMPT_PLAN_MISMATCH`로 실패했다.

대조 요청은 메모리에서만 변경했고 실제 원고·이미지는 바꾸지 않았다. 공통 도우미의 `generation_verified`·`visual_qa_verified`는 파일 검사만으로 true가 되지 않으며, 실제 도구 반환 기록과 직접 시각 검수는 별도 파일로 남겼다.

## 최종 산출물과 근거

- [이미지 포함 최종 원고](../assets/m5-ultra-info-slides-20261023-160049/article-with-images-v2.md)
- [이미지를 내장한 HTML 미리보기](../assets/m5-ultra-info-slides-20261023-160049/article-v2.html)
- [최종 5장·원고·프롬프트·검수 기록 ZIP](../outputs/m5-ultra-info-slides-20261023-160049.zip)
- [최종 전달 요약](../assets/m5-ultra-info-slides-20261023-160049/delivery-summary-v2.json)
- [최종 이미지 요청](../assets/m5-ultra-info-slides-20261023-160049/image-request-v2.json) · [계획](../assets/m5-ultra-info-slides-20261023-160049/image-plan-v2.json) · [프롬프트](../assets/m5-ultra-info-slides-20261023-160049/prompt-set-v2.md)
- [최초 도구 반환](../assets/m5-ultra-info-slides-20261023-160049/generation-returns.json) · [보정 반환](../assets/m5-ultra-info-slides-20261023-160049/correction-returns.json) · [직접 시각 검수](../assets/m5-ultra-info-slides-20261023-160049/visual-qa-v2.json)
- [최종 파일·합성 검사](../assets/m5-ultra-info-slides-20261023-160049/completion-report-v2.json) · [실패 경계 검사](../assets/m5-ultra-info-slides-20261023-160049/negative-live-checks.json) · [ZIP 검사](../assets/m5-ultra-info-slides-20261023-160049/portable-package-check.json)
- [실제 블로그 본문 수집 결과](../assets/m5-ultra-info-slides-20261023-160049/research-report.json) · [본문 표시 사전검사](../assets/m5-ultra-info-slides-20261023-160049/final-preflight-v2.json) · [로컬 브라우저 표시 확인](../assets/m5-ultra-info-slides-20261023-160049/browser-preview-review.json)
- [SmartEditor 실행 요약](../outputs/smarteditor-execution/m5-ultra-20261023-aside-live/delivery-report.json) · [입력 검사](../outputs/smarteditor-execution/m5-ultra-20261023-aside-live/input-check.json) · [재열기 검사](../outputs/smarteditor-execution/m5-ultra-20261023-aside-live/reopened-check.json) · [완료 경계 검사](../outputs/smarteditor-execution/m5-ultra-20261023-aside-live/can-advance.json)
- [임시저장 완료 화면](../outputs/smarteditor-execution/m5-ultra-20261023-aside-live/save-ack.png) · [실제 재열기 화면](../outputs/smarteditor-execution/m5-ultra-20261023-aside-live/reopened-cover.png)

`assets/`와 `outputs/`는 Git 추적 제외다. 위 로컬 원고·PNG·ZIP·계정별 실행 기록은 이 작업 환경의 결과이며 저장소 복제본에 함께 포함되지 않는다. 새 빈 작성 화면은 이후 사용자 브라우저 이동 전의 관찰이며 현재 화면이 계속 비어 있다는 뜻은 아니다. 문단 간격은 실제 화면의 글자 경계를 기준으로 근사 관찰했다. 실제 장비의 AI 성능 측정, 물리 휴대폰·네이버 앱의 표시, 공개·예약 발행은 수행하지 않았다. 이전 Python 364개·Node 43개는 개발 단계 회귀 기록이며 이번 실검증의 재실행 수치로 바꾸지 않는다.
