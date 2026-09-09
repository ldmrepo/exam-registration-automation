---
name: exam-register
description: Search official Korean exam PDFs, visually read passages and questions, and register them through a connected TWK editor browser UI. Use for exam registration and resuming recorded work.
---

# 시험지 검색·시각 변환·문항 등록

이 스킬 폴더를 기준으로 상대 경로를 해석한다. 외부 편집기는 설치하거나 재시작하지 않는다.

1. `python scripts/connector.py status`로 편집기 주소와 사용자 실행 기록 경로를 확인한다. 미설정이면 [연결 안내](references/connection.md)를 따른다. 키를 대화에 요청하거나 파일·로그에 평문으로 기록하지 않는다.
2. [실행 절차](references/workflow.md)와 [재개 규칙](references/run-records.md)을 읽는다. 요청한 시험·과목·선택과목·홀짝형·문항 범위와 해당 사용자 실행 기록을 확인한다. 기존 ID는 새 문서 생성 전에 재열람한다.
3. `doctor`로 연결을 검사한다. 로그인이 필요하면 `open --print-url`로 일회용 주소를 발급받아 즉시 브라우저 도구로 연다. 주소를 사용자 메시지나 실행 기록에 보존하지 않는다. 새 탭의 문서 화면으로 로그인 성공을 확인한다.
4. 현재 제공된 브라우저 도구 문서와 관련 computer-use 스킬을 따라 공식 검색·PDF 시각 확인·UI 입력을 수행한다. 브라우저 도구가 없으면 환경이 준비되지 않았음을 알린다. 내부 앱 상태 변경이나 비공개 저장 API로 우회하지 않는다.
5. [편집 지침](references/editor-playbook.md)의 해당 형식만 읽는다. 텍스트·수식은 편집 가능하게, 그림은 시각 확인한 원본으로 입력한다. 옛한글은 문자표를 사용한다. 원문 읽기 순서로 단·페이지를 이어 붙인다.
6. 초안과 생성 ID를 사용자 실행 폴더에 먼저 기록한다. 저장 완료·재열람·원본 대조까지 통과한 항목만 verified로 기록한다. API 연결 성공은 문항 등록 성공을 뜻하지 않는다.

지문은 일반 문서, 문항은 별도 QTI 문서다. 지문과 여러 문항의 앱 내 연결, 출력·내보내기, 독립 무인 실행은 제외한다. 요청 범위 밖 문항을 임의로 추가하지 않는다. 사용자 수정은 보존하고 잘못 편집하면 Undo/Redo 후 확인한다. 저장 결과가 불명확하면 생성 대신 기존 ID와 목록부터 확인한다.

등록·기존 확인·보류 개수와 문서 링크, 다음 재개 위치를 보고한다. 과거 검증 사례를 현재 설치 환경의 검증 결과로 주장하지 않는다.
