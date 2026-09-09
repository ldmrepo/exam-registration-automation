# 배포판 설치·운영 지침

Windows와 Python 3.11 이상, 브라우저를 제어할 수 있는 Codex 환경이 필요하다. 외부 편집기는 설치하지 않는다.

설치 요청이면 README 순서로 환경 확인 → install.ps1 → 사용자 터미널에서 configure → doctor → 로그인 인계를 수행한다. API 키를 채팅으로 요구하거나 평문 파일·명령행 인수·로그에 저장하지 않는다. configure는 키를 숨겨 입력받는다. 키가 준비되지 않으면 스킬 설치와 오프라인 검증을 완료하고 연결 단계만 미완료로 보고한다.

배포 스킬 원본은 skills/exam-register다. 기존 설치는 자동 백업하며 실행 기록은 사용자 로컬 폴더에 둔다. 이 저장소의 runs, fixtures, 기존 docs는 개인 검증 이력으로 배포하지 않는다. 지원 플랫폼은 Windows다. 다른 OS의 키 저장을 평문으로 대체하지 않는다.

검증: `python -m unittest discover -s tests -v`, `python scripts/package_release.py`. 실제 연결은 doctor와 브라우저 문서 화면으로 별도 확인한다. 문항 등록은 사용자 지정 범위가 있을 때만 수행한다.

인증 연결은 API, 문항 편집은 현재 브라우저 UI를 사용한다. 저장 직후 ID와 초안을 보존하고 기존 문서를 재열람한다. README에 미검증 환경과 범위를 명확히 기록한다.
