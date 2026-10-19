# 월별 시즌 작성 스킬 검증 결과

검증일: 2026-10-19. 대상: [naver-seasonal-blog-writer](../skills/naver-seasonal-blog-writer/SKILL.md). [개발 계획](../dev-plan/implement_20261019_145740.md)의 5개 Phase를 순서대로 진행하고 각 단계 자체 테스트 후 다음 단계로 이동했다.

이 문서는 최초 구현의 격리 검증과 이후 전역 설치·실제 원고·월별 기본 동작 보완을 시간 순서로 구분한다. 현재 사용법과 독립 실행 조건은 [사용 가이드](naver-seasonal-blog-writer-guide.md)를 참고한다.

## 구현 결과

| 항목 | 결과 |
|---|---|
| 데이터 | 원문 3,109행 → 완전 일치 2,796개 → NFC·공백 정리 2,793개 |
| 주제 | 보수적 별칭 규칙으로 2,728개 그룹. 최종 의미 중복은 에이전트가 검토 |
| 자동 추천 대상 | 후보 문구 1,946개. 교정·사업/행사명 검토 대기 847개는 보존·제외 |
| 추천 | 12개월·분야·연도·회차·블로그 이력 반영, 후보 부족 표시, 신규/갱신 분리 |
| 작성 | 현재 에이전트가 공식 자료를 읽고 실제 한국어 본문·출처·검수 작성 |
| 이력 | 블로그별 상태·revision·동시 기록 충돌·재시도 중복 방지 |
| 갱신 | 이전 원고 보존, 새 v0002·본문 해시·검수·이력 연결 |
| 실행 의존성 | 스킬 폴더 내부 데이터/모듈 + Python 3.10+ 표준 라이브러리. 사실 확인에 사용 가능한 웹 도구 |

원본 Downloads 경로에 엑셀이 남아 있지 않아 이전 분석에서 보존한 전체 시트 스냅샷으로 생성했다. 스냅샷 SHA-256은 `41d5a9d1a6ab28478cf904aeaab2af9d6cfa6ece462c788857d4359534b9ac0f`다. 원본 엑셀 바이트 대조는 미실행이다. 전체 스냅샷을 읽기 전용으로 다시 정제한 결과가 배포 데이터와 일치했다. A 요약과 상세의 83행 차이, B 복제 월별 보기 제외를 유지했다.

## 최초 구현의 자동 테스트와 격리 실행

- 신규 테스트 **30개** 통과. 데이터/정제 6, 추천/이력 10, 원고 11, 패키지/격리 3개다.
- 전체 Python **334개**, Node **43개** 통과. 기존 코드와 스킬을 수정하지 않았다.
- skill-creator 기본 검증과 로컬 문서 링크 106개, 스킬 내부 참조·import 경계 검사를 통과했다.
- 원고 해시 변경, 검수 파일 변조, 주제/회차 연결 오류, 근거 누락·상충, 미래 확인일, 근거 없는 체험, 파일 경로 이탈, revision 충돌, 저장 실패·재시도를 검사했다.
- 자료 제목의 실행 지시 문구는 문자열로만 전달되며 명령으로 실행되지 않는 것을 검사했다. 과장 제목·원본성 등 의미 문제는 실제 검수 판단을 기록하며 자동 판별로 주장하지 않는다.
- 검색/확인 불가를 가정한 미확인 초안은 needs_review로 보존하고 발행 완료로 승격하지 않는 것을 fixture로 검사했다.

실제 원고 검증은 fixture와 구분했다. 새 스킬 폴더만 `/private/tmp/naver-seasonal-proof-1nla5q68/naver-seasonal-blog-writer`에 복사하고 저장소 밖 CWD·별도 work에서 **28개 CLI 명령**을 실행했다. `-E -s -S -B`로 환경/사용자 패키지 유입을 배제하고 Python audit hook으로 원본 저장소 및 설치된 기존 스킬 경로의 파일 접근을 차단했다. 이는 검증용 Python 프로세스의 경로 차단이며 운영체제 전체 샌드박스를 새로 구성한 것은 아니다.

12개월 추천 → 실제 신규 원고 → 같은 이벤트 재시도 → 재추천 제외 → 다른 블로그의 정상 추천 → 갱신 필요 기록 → updates 분리 → 실제 수정본 → 검수/이력 재조회까지 통과했다. alpha 이력 revision은 3, beta는 0이며 원고는 v0001/v0002 두 버전이다. 스킬 파일은 실행 전후 바이트가 동일했다. 원본 엑셀·분석 outputs·루트 도우미·기존 작성 스킬을 런타임 입력으로 전달하지 않았다.

## 실제 작성 근거

검증 원고는 ‘한파 수도관 동파 예방’이다. 이 대화에서 [서울시 동파 예방 안내](https://mediahub.seoul.go.kr/archives/2016694)와 [서울아리수본부 장기 외출 전 안내](https://arisu.seoul.go.kr/home/sub?dsn=1772496843-011-353&menukey=7205&mode=view)를 실제 읽고 7개 핵심 주장과 본문 위치를 연결했다. 두 문서의 확인일은 2026-10-19다. 설 연휴 당시 운영 일정을 향후 겨울 일정으로 전용하지 않았다.

직접 답·제목 일치·실용성·사실 근거·원본성의 5개 항목을 실제 본문 문구와 함께 검토했다. v2는 외출 전 확인 표를 추가하고 새 해시·검수를 만들었다. 기계 검사 통과는 파일·근거 연결 검사를 의미하며, 실제 사실성·독창성 판단은 에이전트 검수 기록이다. 전 웹 표절 검색은 수행하지 않았다.

## 로컬 증거

아래 outputs는 Git 추적 제외이므로 저장소 복제에는 포함되지 않는다. 실행한 로컬 작업 공간에 보존돼 있다.

- [격리 실행 요약](../outputs/seasonal-writer-validation/isolation-report.json), [28개 명령](../outputs/seasonal-writer-validation/isolated-run-final/work/commands.json), [월별 결과](../outputs/seasonal-writer-validation/isolated-run-final/work/monthly-results.json)
- [신규 원고 v1](../outputs/seasonal-writer-validation/isolated-run-final/work/articles/alpha/post-09214394653753b9b4ba/v0001/article.md), [수정 원고 v2](../outputs/seasonal-writer-validation/isolated-run-final/work/articles/alpha/post-09214394653753b9b4ba/v0002/article.md)
- [v2 근거](../outputs/seasonal-writer-validation/isolated-run-final/work/articles/alpha/post-09214394653753b9b4ba/v0002/editorial.json), [v2 검수](../outputs/seasonal-writer-validation/isolated-run-final/work/articles/alpha/post-09214394653753b9b4ba/v0002/review.json), [작성 이력](../outputs/seasonal-writer-validation/isolated-run-final/work/.seasonal-writer/alpha/history.json)
- [Python 로그](../outputs/seasonal-writer-validation/python-tests.log), [Node 로그](../outputs/seasonal-writer-validation/node-tests.log), [입력 재정제 대조](../outputs/seasonal-writer-validation/data-rebuild.json)
- [독립 배포 ZIP](../outputs/naver-seasonal-blog-writer.zip)

최초 격리 검증에는 전역 설치·새 대화 자동 선택·네이버 입력/발행을 포함하지 않았다. 후속 전역 설치와 실제 실행은 아래에 별도로 기록한다. 자동 추천은 검색량 순위나 성과 예측이 아니며 검토 대기 847개 문구는 자동 추천에서 제외하고, 최종 주제의 의미 중복은 에이전트가 검토한다.

## 후속 전역 설치와 실제 작성

| 항목 | 실행 결과 | 로컬 증거 |
|---|---|---|
| 전역 설치 | `~/.codex/skills/naver-seasonal-blog-writer/` 11개 파일 설치·해시 대조 | [설치 기록](../outputs/global-skill-install-20261019/installation.json) |
| Codex 목록 인식 | 저장소 CWD와 `/private/tmp` 양쪽에서 `scope=user`, `enabled=true` 확인 | [목록 인식](../outputs/global-skill-install-20261019/discovery-check.json) |
| 10월 추천 | 설치본으로 원시 139개 후보 조회 후 의미 중복 검토를 거친 8개 선정 | [추천 결과](../outputs/global-skill-install-20261019/recommendations-final.json), [실행 범위](../outputs/global-skill-install-20261019/verification.json) |
| 부가세 글 작성 | 개인사업자 대상 실제 원고·국세청 공식 자료 3건·핵심 주장 11개·검수 5개 저장 | [작성 완료 기록](../outputs/vat-article-20261019/completion.json) |
| 실제 사용자 작업 공간 이력 | default 블로그에 drafted v1·revision 1 등록, 같은 주제의 신규 추천 제외 확인 | [저장 검증](../outputs/vat-article-20261019/saved-verification.json), [당시 이력](../outputs/vat-article-20261019/history-after.json) |

기록된 부가세 원고는 사용자 작업 공간의 `articles/default/`에, 이력은 `.seasonal-writer/default/`에 저장했다. 설치된 스킬 폴더에는 사용자 원고나 이력을 넣지 않았다. 이 검증은 전역 스킬 목록 인식과 현재 대화에서 설치본을 사용한 추천·실제 작성이다. 새 대화에서의 암묵적 모델 선택과 네이버 발행은 검증하지 않았다.

## 월별 기본 동작 보완

사용자의 목적을 ‘해당 월에 필요한 주제 자동 추천 → 주제 선택 → 실제 블로그 글 작성’으로 명확히 했다. 기본 호출문은 월별 추천을 우선하고, 날짜·월을 생략한 CLI도 실행 환경의 현재 날짜를 사용한다. 지정 월·명시 연도·확인 기준일은 구분해 유지한다.

- 관련 테스트 **33개** 통과: 기존 30개에 현재 월 기본값·월만 지정/명시 연도·명시 기준일 계획 검사를 추가했다. [테스트 로그](../outputs/monthly-recommendation-default-20261019/tests.log)
- 전역 설치본으로 날짜 인자 없는 12개월 추천을 실행했다. [월별 조회](../outputs/monthly-recommendation-default-20261019/monthly-checks.json)
- 4개 변경 파일을 전역 설치본에 동기화하고 11개 파일이 저장소 패키지와 일치하는지 확인했다. [전역 갱신](../outputs/monthly-recommendation-default-20261019/global-update.json)
- 기존 부가세 원고와 작성 이력의 해시가 보존됐고, 같은 주제가 재추천에서 제외됐다. [최종 확인](../outputs/monthly-recommendation-default-20261019/verification.json)
- 보완된 배포 파일은 [월별 추천 기본판 ZIP](../outputs/naver-seasonal-blog-writer-monthly-default-20261019.zip)이다. 초기 ZIP과 구분하며 사용자 파일은 포함하지 않는다.

최초 전체 Python 334개·Node 43개와 후속 관련 테스트 33개는 서로 다른 실행 범위다. 추가한 테스트 수를 기존 전체 수에 더해 전체 회귀를 새로 수행한 것처럼 보고하지 않는다. 문서 갱신 역시 위 실행 기록을 대조하는 작업이며 코드·스킬·원고·이력을 변경하지 않는다.

## 문서 동기화 검증

2026-10-19에 README, 기능 가이드, 월별 시즌 전용 가이드, 이 검증 문서를 현재 동작과 대조했다. 로컬 링크 대상 167개와 앵커 23개, Markdown 코드 블록, 가이드의 Bash 예제 구문을 확인했다. 8개 스킬 진입점의 기본 검증을 통과했으며 기존 코드·스킬·테스트·원고·이력 등 158개 파일의 SHA-256이 보존됐다. `git diff --check`도 통과했다.

이번 작업에서 전체 코드 회귀·신규 원고 작성·전역 스킬 재설치·네이버 입력은 실행하지 않았다. 문서 검사 증거는 로컬 `outputs/documentation-update-20261019/`에 보존했다.

## main 커밋 전 확인

후속 커밋 준비 단계에서 현재 작업 트리의 전체 Python **337개**, Node **43개**를 다시 실행해 통과했다. 로그는 로컬 `outputs/documentation-update-20261019/pre-push-python.log`, `pre-push-node.log`에 보존했다. 개인 원고 `articles/`와 작성 이력 `.seasonal-writer/`는 Git 추적 제외로 추가해 스킬·테스트·문서와 함께 배포되지 않도록 했다. 원고·이력 파일 자체는 보존했다.
