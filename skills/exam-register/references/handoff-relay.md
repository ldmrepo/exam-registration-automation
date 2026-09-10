# 마스터 소유의 제한 시간 인계 릴레이

`scripts/handoff_relay.py`는 마스터가 지정한 run과 문항 범위에서만 제출과 다음 편집권 인계를 수행하는 로컬 파일 릴레이다. 서버가 유지하는 `Run`은 `submit_and_claim`만 호출한다. `finish`는 호출하지 않는다. 브라우저, 네트워크, 외부 에이전트 깨우기 API를 사용하지 않는다.

마스터가 서버 프로세스를 직접 시작하는 행위가 해당 범위의 `review_pending` 전환과 다음 `editing` 토큰 발급을 위임한다. 편집 담당은 증거와 요청 파일만 작성한다. 공식 manifest와 대기열의 변경 주체는 마스터 소유 서버다. 마스터는 stdout의 성공 이벤트나 편집 담당의 비동기 보고를 보고 스크린샷을 독립 검토한 뒤 기존 `parallel_run.py finish`를 실행한다.

## 실행

마스터가 최초 문항을 claim하고, 편집 담당을 깨우기 전에 다음 서버를 시작한다. `--only`는 필수이며 서버 수명 동안 고정된다. `--max-seconds`는 0 초 초과 3600 초 이하이다.

```powershell
python scripts/handoff_relay.py --run RUN serve --only q1 q2 q3 q4 q5 --max-seconds 600 --stop-when-drained
```

편집 담당은 저장·재열람과 입력 검사 네 항목을 완료한 뒤, 본인 문항 폴더에 스크린샷과 JSON payload를 보존한다. 한 프로세스에서 증거 작성, 제출 요청, 응답 대기를 연결한다.

```powershell
python scripts/handoff_relay.py --run RUN request --item q1 --token EDIT_TOKEN --payload verification/q1/payload.json --wait-seconds 45
```

`--payload -`는 stdin JSON도 받는다. 기존 증거가 있으면 `--payload` 대신 `--evidence verification/q1/evidence.json`을 쓴다. 두 옵션은 동시에 사용할 수 없다. 요청 파일과 응답 파일은 토큰별로 한 번만 생성한다. 기존 증거·요청·응답을 덮어쓰지 않는다.

성공 응답은 `status: ok`, `submitted`, `next`를 포함한다. `next`가 객체이면 새 편집 토큰과 대상·초안 경로가 공식 인계다. 같은 활성 편집 담당이 응답을 읽고 계속 진행하므로 새 에이전트 wakeup이나 문항별 마스터 모델 왕복이 필요하지 않다. 이미 읽은 응답을 다시 읽는 것은 새 권한 발급이 아니다. 해당 토큰이 취소·갱신된 뒤에는 과거 응답으로 작업하지 않는다.

`request`, `wait`, `serve`의 CLI 출력은 기본적으로 성공 응답을 축약한다. `submitted`는 `id`, `version`, `edit_token`, `evidence`를, `next`는 `id`, `document_id`, `type`, `version`, `spec_version`, `edit_token`, `draft`, `draft_hash`, `source_hashes`, `asset_hashes`를 보존한다. 원본에 없는 필드는 생성하지 않는다. 캐시 검증에 필요한 버전·해시·초안 경로는 유지하고 전체 영역·사유 등은 출력에서 생략한다. 최상위 요청 `token`도 유지한다. 각 하위 명령에 `--verbose`를 붙이면 전체 응답을 출력한다.

`relay/responses/TOKEN.json`의 영구 응답과 내부 처리 결과는 항상 전체 기록이다. 축약은 출력에만 적용하며 편집권 발급·토큰·해시 의미를 바꾸지 않는다. 오류·timeout·복구 안내와 `next: null`은 그대로 보존한다. 복구 시 전체 기록은 응답 파일 또는 `wait --verbose`로 확인한다.

`next: null`이면 편집 담당은 멈춘다. `--stop-when-drained` 서버는 성공 제출 후 next가 null이고 지정 범위에 ready/editing이 없을 때 종료한다. review_pending은 종료를 막지 않으며 마스터 검토는 계속 필요하다. 아직 준비되지 않은 문항이 있다면 이 옵션 대신 제한 시간만 사용하고 마스터가 나중에 인계를 재개한다.

45 초 내 응답이 없으면 `status: timeout, next: null`이다. 이는 실패 확정이나 편집권 허가가 아니다. 기존 요청을 다시 제출하지 않고 읽기 전용 대기를 반복한다.

```powershell
python scripts/handoff_relay.py --run RUN wait --token EDIT_TOKEN --max-seconds 45
```

## 장애와 복구

`.handoff-relay.lock`은 동일 run의 복수 서버 실행을 거부한다. manifest 쓰기에는 기존 coordinator lock도 적용된다. 마스터의 독립 finish와 충돌한 경우, transaction 진입 전의 정확한 lock acquisition 오류만 최대 2 초 및 남은 서버 시간 이내로 재시도한다. 그 밖의 오류는 자동 재시도하지 않는다. 종료 시간은 새 요청 처리 시작을 제한하며 이미 진행 중인 파일 transaction을 중간에 강제 종료하지 않는다.

서버는 변경 전 `relay/attempts/TOKEN.json`을 먼저 디스크에 기록한다. 성공 응답은 fsync 후 원자적·배타적으로 `relay/responses/TOKEN.json`에 게시한다. 잘못된 JSON/필드/범위는 `rejected`이며 manifest를 바꾸지 않는다. 요청 이름·경로가 잘못되거나 출력 게시가 실패하면 서버는 오류를 보고하고 정지한다.

transaction 성공 뒤 대기열 갱신 또는 응답 출력이 실패할 수도 있다. `recoverable_error` 또는 응답 없는 attempt는 불확실한 변경을 나타낸다. 서버 재시작도 이 요청을 다시 실행하지 않는다. 마스터가 다음 절차를 수행한다.

1. 편집 담당을 멈추고 기존 서버가 종료했는지 확인한다. 남은 lock 파일은 PID의 실제 종료를 확인한 뒤에만 수동 처리한다.
2. 기존 `parallel_run.py --run RUN status`로 manifest 상태, 토큰, 이벤트를 확인하고 attempts와 responses를 함께 읽는다.
3. 투영 실패이면 `parallel_run.py --run RUN rebuild`로 큐를 복구한다. 이 명령은 submit이나 claim을 반복하지 않는다.
4. 이미 커밋된 경우 마스터가 현재 manifest의 editing 항목·토큰을 확인하여 편집 담당에게 직접 인계하고 review_pending 증거를 독립 검토한다. 기존 응답은 덮어쓰지 않는다.
5. 커밋되지 않은 경우에도 상태와 편집 담당의 정지를 확인한 후 마스터가 기존 수동 submit-and-claim 경로를 선택한다. 같은 토큰 요청을 삭제하고 자동 재시도하는 방식은 사용하지 않는다.

합성 테스트는 정상 인계, null 다음 항목, 범위 밖 불변성, 중복·오래된 토큰, 읽기 전용 timeout, 전역 lock, 제한 시간 종료, 증거 작성부터 응답까지의 단일 client 호출, lock 경합, 커밋 후 출력/투영 실패를 검사한다. 실제 브라우저 입력 품질이나 성능 향상은 별도 고정 조건 실행에서 검증한다.
