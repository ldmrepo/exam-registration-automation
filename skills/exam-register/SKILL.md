---
name: exam-register
description: Search official Korean exam PDFs, visually extract questions in parallel, and register editable content through a connected TWK editor browser UI. Use for exam registration and resuming recorded work.
---

# 시험지 검색·시각 변환·문항 등록

이 스킬 폴더를 기준으로 상대 경로를 해석한다. 외부 편집기는 설치하거나 재시작하지 않는다. 이 스킬은 Codex가 실제 도구로 실행하는 절차이며 독립 무인 서비스가 아니다.

## 진입과 역할

브라우저 작업은 **Codex 내장 브라우저(`iab`)**를 사용한다. 외부 Chrome/Edge로 자동 전환하지 않는다. [내장 브라우저 운영](references/browser-policy.md)을 먼저 적용해 실제 접근 가능한 담당자를 정한다. 서브에이전트가 내장 브라우저에 접근하지 못하면 마스터가 단일 편집 역할을 겸임하며, 추출 분석은 로컬 이미지로 병렬 진행한다. 이 경우 아래 편집 에이전트 생성 지침은 마스터 겸임 절차로 대체한다.

1. 요청 범위와 기존 실행 기록을 확인한다. 새 등록 요청에서 추출 인원이 지정되지 않았으면 “추출·분석 에이전트를 몇 개 사용할까요? 기본은 2개입니다.”라고 묻는다. 답변 전에는 검색·원본 확보·분류만 진행하고 인원에 의존하는 실행은 시작하지 않는다. 실제 동시 실행 한도에서 마스터 1개와 편집 1개를 제외한 수를 확인한다. 한도를 고정값으로 가정하지 않는다.
2. 기본 구성은 현재 요청을 수행하는 마스터 1 + 추출·분석 2 + 편집 1이다. [실행 연결](references/orchestration.md)을 읽고 실제 서브에이전트를 생성한다. 역할 파일을 만들어 둔 것만으로 실행된다고 보고하지 않는다.
3. 마스터는 [역할](references/roles/master.md)과 [계획](references/planning.md), 추출 담당은 [역할](references/roles/extractor.md)과 [추출](references/extraction.md), 편집 담당은 [역할](references/roles/editor.md)과 [편집](references/editing.md)을 읽는다. [검증](references/verification.md)은 완료 보고와 인계 심사 시 사용한다.

## 공통 불변 조건

- 마스터가 유형별 빈 문서를 먼저 생성하고 대상 ID·원본 영역을 배정한다. 추출은 병렬, 편집은 준비 완료 순서대로 한 에이전트만 수행한다.
- 마스터만 manifest·assignment·queue의 공식 상태를 변경한다. 담당자는 자신의 산출물과 메시지로 결과를 제출한다. 편집 대상은 문항 번호뿐 아니라 문서 ID·명세 버전·초안 버전·배정 토큰으로 확인한다.
- 원본은 저장된 페이지 이미지 좌표로 지정한다. 추출 담당마다 별도 원본 열람 환경을 사용하고 편집기 탭은 단일 소유자가 제어한다.
- 텍스트·수식은 편집 가능하게, 그림은 원본에서 시각 확인한 영역으로 등록한다. 내용 변경은 브라우저 UI·키보드·허용된 붙여넣기로 수행한다. 비공개 저장 API나 DOM/앱 상태 직접 변경으로 우회하지 않는다.
- 저장 후 재열람과 원본 대조 증거가 있어야 완료다. 빈 문서 생성·초안 완성·API 연결 성공을 등록 완료로 세지 않는다.
- 공통 지문과 문항의 앱 내 연결, 출력·내보내기, 여러 편집 담당의 동시 쓰기는 범위 밖이다. 사용자 수정은 보존한다.

## 연결·기록·기존 자료

`python scripts/connector.py status`로 편집기 주소와 사용자 기록 위치를 확인한다. 미설정이면 [연결 안내](references/connection.md)를 따른다. 키는 초안·메시지·대기열·로그에 기록하지 않는다. 연결과 로그인은 마스터가 준비하고 추출 담당에게 인증 정보를 전달하지 않는다.

신규 병렬 작업은 [계획](references/planning.md)의 작업폴더 및 `scripts/parallel_run.py --help`에 따른다. 기존 [실행 절차](references/workflow.md)는 공식 검색·시각 판독의 공통 참고, [재개 기록](references/run-records.md)은 레거시 기록의 해석·보존 기준이다. 신규 병렬 상태 전환·파일 소유권은 [실행 연결](references/orchestration.md)이 기준이다. 레거시 v1 예시를 신규 병렬 manifest 위에 덮어쓰지 않는다.

편집기 조작은 현재 브라우저 도구 문서 및 필요한 computer-use 스킬을 먼저 확인하고 [편집 기능 지침](references/editor-playbook.md)의 필요한 형식만 읽는다. 실제 도구가 없으면 가능한 준비를 완료하고 실행 미검증 범위를 명시한다. 과거 개발 환경의 검증을 현재 실행 증거로 사용하지 않는다.
