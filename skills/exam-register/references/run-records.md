# 실행 기록과 재개 규칙

## 기존 기록을 먼저 읽기

`runs/2026-csat-math-odd/manifest.json`은 `items` 배열의 `job_key`, `document_id`, `status`를 사용한다. `registered_and_reopened`는 당시 저장·재열람 완료다.

`runs/2026-csat-korean-formats/manifest.json`의 공식 문항은 `official_questions`, 공식 지문은 `official_passages`에 있다. `checks.reopened`는 당시 재열람 근거다. `documents` 배열은 P01/T01/T02/T03 창작 형식 표본으로 공식 문항과 구분한다. 기존 명세 형식은 이력을 보존하며 강제 변환하지 않는다.

## 새 실행 기록

새 작업은 `runs/<시험-범위-실행일>/manifest.json`에 기록한다. 아래 구조는 신규 실행을 위한 규칙이며 기존 자료를 변경하는 명령이 아니다.

```json
{
  "schema_version": 1,
  "run_id": "user-selected-run",
  "exam": {"academic_year": 2026, "exam_type": "수능", "session": "본시험", "subject": "국어", "elective": "언어와 매체", "variant": "홀수형"},
  "source": {"board_url": null, "question_pdf_url": null, "answer_pdf_url": null, "local_pdf": null, "sha256": null},
  "requested_units": ["q44", "q45"],
  "items": [
    {"unit": "q44", "kind": "question", "job_key": null, "physical_pages": [], "printed_pages": [], "state": "planned", "document_id": null, "document_url": null, "last_verified_at": null, "checks": {}, "next_action": "원본 확인", "issue": null},
    {"unit": "q45", "kind": "question", "job_key": null, "physical_pages": [], "printed_pages": [], "state": "planned", "document_id": null, "document_url": null, "last_verified_at": null, "checks": {}, "next_action": "원본 확인", "issue": null}
  ]
}
```

예시 번호는 실행 지시가 아니다. 실제 요청으로 대체한다. 지문은 `kind: passage`, `unit: p44-45`처럼 원문 범위로 식별하되 앱 내 문항 연결을 만들지 않는다. 미확인 값은 추정하지 않고 null로 둔다. 생성 ID와 체크 결과는 확인 즉시 저장한다.

`job_key`는 출처 기관·학년도·시험 종류/회차·과목·선택과목·홀짝형·단위 종류/번호로 구성한다. 과거의 다른 키 형식도 같은 필드가 일치하는지 대조한다. 원본 해시는 별도 비교한다. 해시가 다르다는 이유만으로 같은 시험 문항을 새로 만들지 말고 개정본인지 판단한다.

## 상태와 다음 행동

| 상태/관찰 | 다음 행동 |
|---|---|
| planned | 공식 원문 식별·시각 판독 |
| transcribed | 초안 원본 대조 후 기존 문서 확인 |
| editing, ID 있음 | 기존 문서를 열어 부족한 내용부터 입력 |
| saved, 재열람 미완료 | 기존 ID 재열람 검증 |
| verified | 기존 문서·시험 식별이 일치하면 신규 생성 생략 |
| blocked | 사유를 확인하고 해결된 단계부터 재개, ID 유지 |
| 저장 시간 초과, ID 불명확 | 목록 검색으로 제목·출처·번호를 대조한 뒤 존재 여부 결정 |
| 동일 식별자에 여러 ID | 중복 후보로 보류. 임의 삭제·덮어쓰기 금지 |
| 기록 ID 문서가 없음 | 목록에서 이동/다른 ID 여부 확인. 사용자 삭제 가능성이 있으면 복구 전에 확인 |
| 기록과 현재 내용이 다름 | 사용자 수정 여부 확인. 원본으로 자동 덮어쓰지 않음 |

검증 항목은 대상에 맞게 남긴다: 본문 대조, 답항 개수·순서·공식 정답, 수식, 이미지 로드·크기·정렬, 표 행열, 특수문자, 지문 읽기 순서, 임시 내용 없음, 저장 후 재열람. 검증하지 않은 항목에 true를 넣지 않는다.

종료 시 `requested_units` 전체가 항목별로 설명되어야 한다. `q36`, `q38` 완료가 `q37` 완료를 의미하지 않는다. 로컬 기록 확인은 현재 앱의 실시간 중복 검색을 대체하지 않는다.

## 장애 후 재개 순서

1. 입력 전 초안과 생성 직후 문서 ID를 실행 폴더에 보존한다. 이미지 원본·순서·크기도 함께 남긴다.
2. 실패하면 생성 버튼을 누르지 않는다. 현재 문서 URL, 저장 표시, 마지막 성공 단계부터 기록한다.
3. 연결을 복구하고 같은 ID를 연다. 보존된 내용과 초안을 비교해 누락된 부분만 다시 입력한다. 사용자 변경과 충돌하면 덮어쓰지 않는다.
4. 저장 완료와 재열람을 확인한 뒤 `verified`로 승격한다. ‘저장 실패’에서도 실시간 본문이 보존된 사례가 있으므로 미저장=전체 손실로 가정하지 않는다.
5. ‘문서를 불러오지 못했습니다’는 삭제 증거가 아니다. 연결·서비스 상태부터 확인하고 조회 가능한 상태에서 존재 여부를 판단한다.

복구 시험은 공식 문항과 구분한 문서에서 수행한다. 과거 복구 검증에서는 저장 실패·탭 종료·저장 지연·정상 재열기를 구분했다.
