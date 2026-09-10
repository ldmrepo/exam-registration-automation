# 시험지 검색·시각 변환·문항 등록

Windows용 Codex 스킬. 현재 작업본은 0.2.0-preview이며 기존 공개 배포 이력은 v0.1.0이다. 공식 시험지 PDF를 브라우저에서 시각 확인하고 외부 TWK 편집기에 지문·문항을 입력한 뒤 저장·재열람한다. 편집기 서비스는 포함하지 않는다.

## Codex에 설치 요청

> https://github.com/ldmrepo/exam-registration-automation 을 내려받고 AGENTS.md에 따라 설치해줘. 편집기 연결은 로컬 터미널에서 설정할게.

필요 환경: Windows, Python 3.11 이상, 브라우저 제어 도구를 사용할 수 있는 Codex 환경, TWK API 키·handoff를 지원하는 편집기 계정. Codex와 브라우저 도구의 설치·로그인은 사용자 환경에서 준비해야 한다. 이 스킬 자체가 브라우저 제어 권한을 제공하지 않는다.

## 설치

PowerShell에서 저장소를 내려받은 뒤 실행한다. Git이 없으면 GitHub Release ZIP을 풀어 사용한다.

```powershell
git clone https://github.com/ldmrepo/exam-registration-automation.git
cd exam-registration-automation
powershell -NoProfile -ExecutionPolicy Bypass -File ./install.ps1
```

설치 위치는 `$CODEX_HOME/skills/exam-register`, CODEX_HOME이 없으면 사용자 홈의 `.codex/skills/exam-register`다. 기존 스킬은 해당 skills 폴더 옆 `exam-register-backups`에 보존한다. 스킬 목록에 나타나지 않으면 새 Codex 작업을 열거나 설치된 SKILL.md를 직접 지정한다.

## 외부 편집기 연결

저장소 폴더에서 아래 명령을 **사용자 터미널에 직접 실행**한다.

```powershell
python skills/exam-register/scripts/connector.py configure
```

웹 주소, API 기본 주소, API 키를 입력한다. 예시 주소는 웹 `http://localhost:3100`, API `http://localhost:4000/api/v1`이다. 외부 서비스는 HTTPS를 사용한다. 키는 편집기 설정 › API 키에서 사용자가 발급하며 터미널 입력 시 표시되지 않는다. 키를 채팅에 붙여넣거나 GitHub에 올리지 않는다.

연결 검사 성공 후 주소·키를 묶어 Windows CurrentUser DPAPI로 암호화하고 `%LOCALAPPDATA%/ExamRegister/connection.dpapi`에 보관한다. 같은 Windows 계정에서 사용하며 다른 PC에서는 다시 configure한다. 로컬 사용자 계정 자체가 침해된 상황까지 보호하는 별도 금고는 아니다.

```powershell
python skills/exam-register/scripts/connector.py status
python skills/exam-register/scripts/connector.py doctor
python skills/exam-register/scripts/connector.py open
```

Codex 자동화는 **내장 브라우저(iab)**를 사용한다. 기존 로그인 탭을 재사용하고, 새 로그인이 필요할 때만 `open --print-url` 결과를 즉시 내장 브라우저에 연다. 인자 없는 `open`은 수동 사용자를 위한 OS 기본 브라우저 실행 기능이며 자동화에서는 사용하지 않는다. 30초 코드나 API 키를 실행 기록에 저장하지 않는다. 사용자별 키를 쓰며 발급 계정의 전체 권한이 적용된다. 키는 만료되지 않지만 편집기에서 삭제하면 회수된다.

연결 해제는 `disconnect`, 주소·키 변경은 `configure`다. disconnect는 로컬 설정만 삭제하며 서버 키를 폐기하지 않는다.

## 사용

> $exam-register로 2026학년도 수능 국어 언어와 매체 36번을 원본과 대조해 등록해줘. 기존 등록이 있으면 재열람부터 해줘.

실행 기록은 status에 표시되는 사용자 runs 폴더에 둔다. 초안·문서 ID를 보존하고 재실행 때 기존 문서를 확인한다. 문항 입력과 서식 적용은 브라우저 UI를 사용한다. API 직접 문항 등록, 협업 WebSocket, 편집기 설치, 공통 지문과 문항 연결, 출력·내보내기, 무인 예약 실행은 포함하지 않는다.

이전 개발 환경에서 공식 18문항·4지문을 등록·재열람했다. 이는 모든 시험·편집기 버전의 호환성을 보장하지 않는다. 개인 실행 기록과 시험지 원본은 배포하지 않는다. 현재 편집기와 다른 서비스는 별도 커넥터·편집 지침이 필요하다.

## 검증과 패키징

### 병렬 처리 개선판 (구현 완료)

범용 코드·스킬·실행 흐름 구현과 로컬 검증을 완료했다. 특정 시험지의 미처리 문항·서식 보완은 별도 운영 작업이며 프로젝트 구현 완료 조건에 포함하지 않는다. 추가 환경·성능 검증과 릴리스 게시 상태도 별도로 관리한다.

기본 구성은 마스터 1, 추출·분석 2, 편집 1이다. 새 요청에서는 추출 인원을 확인하며, 이미 지정한 인원은 다시 묻지 않는다. 마스터가 문항별 좌표와 빈 문서 ID를 배정하고 준비 완료 순서대로 단일 편집 담당에게 전달한다.

편집 서브에이전트가 내장 브라우저에 접근할 수 없으면 마스터가 편집 역할을 겸임하고 추출만 병렬로 진행한다. 외부 Chrome/Edge로 자동 전환하지 않는다. [내장 브라우저 연결·인계 기준](skills/exam-register/references/browser-policy.md)을 따른다. 마스터의 내장 문서 생성·텍스트/PNG HTML 붙여넣기·저장·재열람을 확인했다. 서브에이전트 내장 접근은 불가했으며 OS 파일 선택기 업로드와 모든 문항 형식은 별도 검증 대상이다.

역할은 [agents](agents/master.md), 실행 절차는 [배포 스킬](skills/exam-register/SKILL.md)에 정의한다. `parallel_run.py`는 로컬 상태·대기열 관리 도구이며 브라우저를 실행하거나 문항을 자동 판독하는 독립 서비스가 아니다. Codex 마스터가 실제 서브에이전트를 생성해 실행한다.

```powershell
python skills/exam-register/scripts/parallel_run.py --help
```

현재 개선판은 실제 기본 구성 파일럿, 저장·재열람, 반환 및 동일 ID 재개를 검증했다. 전체 실행 기록은 30문항 중21개 완료이며, 시험지·문항 식별 재확인과 나머지 등록은 미완료다. 새로운 형식5개는4개 통과·1개 보완이었다. 사용자 첨부29번은 별도 형식 검증이며 전체 완료 수에 합산하지 않는다. 전체 추출 포함 동일 조건 성능 비교 및 다른 PC 검증은 미완료다. 생성되는 ZIP은 `0.2.0-preview`이며 기존 공개 릴리스를 변경하지 않는다.

현재 흐름은 원본 확보·항목 분류 → 유형별 빈 문서/ID 배정 → 병렬 추출·마스터 승인 → 준비 순서 단일 편집 → 증거 제출과 다음 배정 → 마스터 시각 심사다. 마스터 소유의 제한 시간 [인계 중계기](skills/exam-register/references/handoff-relay.md)를 사용하면 제출·다음 배정을 이어 처리한다. 중계기는 최종 승인을 대신하지 않는다. 성공 응답은 간결하게 출력하고 전체 기록은 복구용으로 보존한다.

원본에서 답항 뒤에 있는 그림은 사용자 확정 규칙에 따라 발문 영역 하단으로 옮겨 `발문 → 그림 → 답항` 순서로 입력한다. 조건 박스와 좌우 표 배치는 편집 가능한 형태로 확인했으나 열 너비가 균등하게 저장되는 사례가 있어 원본 비율은 별도 검증한다. 정답 없는 첨부 이미지의 형식 입력은 정답을 추정하지 않고 내용·배치 검증으로 구분한다.

```powershell
python -m unittest discover -s tests -v
python scripts/package_release.py
```

패키징은 명시한 파일만 ZIP에 포함하고 실제 키 패턴·개인 절대경로를 검사한다. 자동 테스트는 연결·DPAPI·설치, 대기열·토큰·버전·해시, 입력 검증 증거, 제한 시간 중계·중복 및 불확실한 실패 복구를 검사한다. 실제 서비스의 로그인 화면과 문항 등록은 별도 브라우저 검증 대상이다.

## 라이선스

배포 코드·스킬은 [MIT](LICENSE). 외부 편집기 및 시험지·문항 원본의 권리는 포함하지 않는다.
