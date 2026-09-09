# 외부 편집기 연결

Windows + Python 3.11 이상을 지원한다. 웹 서비스·백엔드·브라우저 자동화 도구는 포함하지 않는다. 호환 대상은 TWK API 키와 handoff 규격을 제공하는 편집기다. 다른 서비스는 별도 커넥터와 UI 지침이 필요하다.

스킬 폴더에서 `python scripts/connector.py configure`를 사용자 터미널로 실행한다. 웹 주소, `/api/v1`을 포함한 API 기본 주소, 사용자가 편집기 설정에서 발급한 키를 입력한다. 키 입력은 표시되지 않는다. 터미널이 키를 숨길 수 없는 환경에서는 진행하지 말고 사용자 로컬 터미널을 사용한다. 키를 채팅에 붙여넣게 하지 않는다.

예: 웹 `http://localhost:3100`, API `http://localhost:4000/api/v1`. 외부 서비스는 HTTPS를 사용한다. 연결 파일은 `%LOCALAPPDATA%/ExamRegister/connection.dpapi`에 Windows CurrentUser DPAPI로 암호화한다. 주소와 키를 함께 묶어 저장하므로 주소를 바꾸려면 configure를 다시 수행한다. 다른 계정/PC로 이 파일을 복사해 사용하지 않는다. 테스트 격리용 `EXAM_REGISTER_HOME`으로 저장 위치를 바꿀 수 있다.

- `status`: 비밀 없이 주소·실행 기록 경로 출력.
- `doctor`: Bearer 키로 GET `/documents`; 데이터 본문은 출력하지 않음.
- `open`: POST `/auth/handoff` 후 기본 브라우저 열기. `--print-url`은 Codex 브라우저 도구용 30초 일회용 주소를 출력한다. 즉시 열고 기록에 넣지 않는다. 만료 시 새 코드를 발급한다.
- `open --redirect /documents/<ID>/edit`: 기존 문서로 인계.
- `disconnect`: 로컬 연결만 제거. 서버 키 폐기는 사용자가 편집기 설정에서 수행.

응답은 `{data,error,traceId}`다. 오류는 래핑되지 않으며 `message`의 코드로 처리한다. 401은 키 누락·삭제·오류, 403은 권한 부족이다. 리다이렉트는 따라가지 않으므로 API의 최종 주소를 설정한다. 키에는 만료·세부 scope가 없고 발급자 계정 권한이 적용된다. 사용자별 키를 사용한다. 토큰 교환과 협업 WebSocket은 이 배포판에서 사용하지 않는다.

인증에 성공해도 이미지·문항 저장·편집 UI 호환성을 보장하지 않는다. 지정된 시험 범위에서 입력 후 저장·재열람으로 검증한다.
