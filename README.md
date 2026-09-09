# 시험지 검색·시각 변환·문항 등록

Windows용 Codex 스킬 배포판 v0.1.0. 공식 시험지 PDF를 브라우저에서 시각 확인하고 외부 TWK 편집기에 지문·문항을 입력한 뒤 저장·재열람한다. 편집기 서비스는 포함하지 않는다.

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

`open`은 일회용 코드로 기본 브라우저에 로그인 인계를 요청한다. Codex 내장 브라우저를 사용하려면 Codex가 `open --print-url` 결과를 즉시 브라우저 도구로 연다. 30초 코드나 API 키를 실행 기록에 저장하지 않는다. 사용자별 키를 쓰며 발급 계정의 전체 권한이 적용된다. 키는 만료되지 않지만 편집기에서 삭제하면 회수된다.

연결 해제는 `disconnect`, 주소·키 변경은 `configure`다. disconnect는 로컬 설정만 삭제하며 서버 키를 폐기하지 않는다.

## 사용

> $exam-register로 2026학년도 수능 국어 언어와 매체 36번을 원본과 대조해 등록해줘. 기존 등록이 있으면 재열람부터 해줘.

실행 기록은 status에 표시되는 사용자 runs 폴더에 둔다. 초안·문서 ID를 보존하고 재실행 때 기존 문서를 확인한다. 문항 입력과 서식 적용은 브라우저 UI를 사용한다. API 직접 문항 등록, 협업 WebSocket, 편집기 설치, 공통 지문과 문항 연결, 출력·내보내기, 무인 예약 실행은 포함하지 않는다.

이전 개발 환경에서 공식 18문항·4지문을 등록·재열람했다. 이는 모든 시험·편집기 버전의 호환성을 보장하지 않는다. 개인 실행 기록과 시험지 원본은 배포하지 않는다. 현재 편집기와 다른 서비스는 별도 커넥터·편집 지침이 필요하다.

## 검증과 패키징

```powershell
python -m unittest discover -s tests -v
python scripts/package_release.py
```

패키징은 명시한 파일만 ZIP에 포함하고 실제 키 패턴·개인 절대경로를 검사한다. 테스트는 로컬 모의 API, 리다이렉트 차단, DPAPI 저장·손상 탐지, 설치 위치 변경과 백업을 검증한다. 실제 서비스의 로그인 화면과 문항 등록은 별도 브라우저 검증 대상이다.

## 라이선스

배포 코드·스킬은 [MIT](LICENSE). 외부 편집기 및 시험지·문항 원본의 권리는 포함하지 않는다.
