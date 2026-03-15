# External Logic Prompt Template

이 파일은 LLM에게 외부 교통관리 로직을 생성시킬 때 그대로 붙여 넣는 템플릿입니다.

함께 전달할 기준 파일:
- `EXTERNAL_LOGIC_SAMPLE_ADAPTIVE_GUARD.py`
- `EXTERNAL_LOGIC_PROMPT_TEMPLATE.md`

아래 프롬프트에서 `[ ... ]` 부분만 바꿔서 사용하면 됩니다.

---

## Copy Prompt

당신은 UAM 시뮬레이터의 외부 교통관리 로직 작성자다.

반드시 실행 가능한 Python 코드만 출력하라.
- 설명문 금지
- 마크다운 코드블록 금지
- 최종 출력은 바로 붙여 넣어 실행 가능한 Python 코드여야 한다

기준 파일:
- 첨부된 `EXTERNAL_LOGIC_SAMPLE_ADAPTIVE_GUARD.py`를 기본 구조와 스타일의 기준으로 삼아라
- 가능하면 helper 함수 기반 구조를 유지하라
- 사용자가 정책만 바꾸고 싶다고 하면 baseline sample을 수정하는 방식으로 작성하라

시뮬레이터 실행 모델:
1. `control_step(state)`는 시뮬레이터의 매 simulation step마다 1회 호출된다.
2. 기본 `dt_s`는 0.2초이며, 보통 초당 약 5회 호출된다.
3. 하지만 `dt_s`와 `realtime_factor`는 바뀔 수 있으므로 절대로 "1초에 1번 호출"이라고 가정하지 마라.
4. 현재 시뮬레이션 시간은 `state["t"]` 초 단위 값으로 들어온다.
5. 따라서 "매 step마다 실행되는 로직", "매 N초마다 실행되는 로직", "시작 시 1회만 실행되는 로직"을 코드에서 명시적으로 구분해야 한다.

상태 지속성 규칙:
1. 외부 로직 코드의 module-global 변수는 로직이 활성화된 동안 유지된다.
2. cooldown, 다음 실행 시각, 기체별 마지막 명령 시각, startup 1회 실행 여부를 global 변수로 저장해도 된다.
3. 사용자가 코드를 수정하거나 로직을 다시 활성화하면 global 상태는 초기화된다고 가정하라.

실행 cadence를 구현하는 방법:
- 매 step 로직: 매 호출마다 바로 판단
- 매 1초/5초 로직: `state["t"]`와 global `next_run_t`로 직접 gate
- 시작 시 1회 로직: global `initialized = False` 플래그로 1회만 실행
- 엔진 cadence gate: 선택적으로 `LOGIC_MIN_INTERVAL_S = 1.0` 같은 전역 상수를 둘 수 있다

명령 의미:
- `set_speed`: persistent 명령이다. 한 번 보내면 다시 바꾸기 전까지 유지된다.
- `turn`: one-shot 명령이다. 선회 action을 시작시키는 요청이다.
- `overtake`: one-shot 명령이다. 추월 action을 시작시키는 요청이다.
- `spawn`: one-shot 명령이다.
- `delete`: one-shot 명령이다.
- `update_params`: one-shot 명령이지만 결과는 이후 step에도 계속 유지된다.
- `LOGIC_MIN_INTERVAL_S`: 엔진 레벨 cadence gate다. 예를 들어 `1.0`이면 외부 로직 본문은 최대 1초마다 1회만 실행된다.

엔진 최종 판정 규칙:
1. 외부 로직은 정책만 제안한다.
2. 실제 실행 가능 여부는 엔진이 마지막에 다시 판정한다.
3. 따라서 `turn`이나 `overtake`를 요청해도 feasibility check에서 거절될 수 있다.
4. `control.*.can_issue_now`는 엔진이 현재 받아줄 가능성이 있는지 알려주는 가장 중요한 신호다.

Node / FIFO 운영 규칙:
1. `route` 모드에서 node 운영은 엔진이 맡는다.
2. `spacing`, `start_hold`, `fifo_hold`, `node_hold`, `merge_hold`는 엔진 내부 운영 상태다.
3. FIFO는 merge node에서만 의미가 있다.
4. straight node는 FIFO 대상이 아니므로 merge처럼 해석하지 마라.
5. 외부 로직은 `ac["data"]["fifo"]`와 `ac["data"]["status"]["wait_reason"]`를 읽고 판단하되, node scheduler 자체를 다시 구현하려고 하지 마라.

반드시 지켜야 할 simulator-specific 해석 규칙:
1. `spacing.forward_flow_relative_speed_knots`는 `front - self` 의미다.
2. 이 값이 음수이면 현재 기체가 앞 기체보다 더 빠르다는 뜻이다.
3. `control.overtake.can_issue_now`는 엔진 측 추월 가능성 신호이므로 우선 신뢰하라.
4. `control.overtake.candidate_target_aircraft_id`가 있으면 기본 추월 목표로 우선 사용하라.
5. `spacing.shared_remaining_link_count`는 route conflict 맥락에서만 참고하고, corridor 추월의 필수 게이트로 사용하지 마라.

필수 계약:
1. 반드시 `control_step(state)` 함수를 정의하라.
2. 선택적으로 아래 전역 상수를 둘 수 있다.
   - `LOGIC_NAME = "..."`
   - `LOGIC_DESCRIPTION = "..."`
   - `PARAM_OVERRIDES = {...}`
   - `LOGIC_MIN_INTERVAL_S = 1.0`
3. `control_step(state)`는 다음 둘 중 하나를 반환해야 한다.
   - `{"commands": [...], "params": {...}, "notes": [...]}`
   - 또는 `commands` 리스트만 직접 반환

허용 명령:
- `set_speed`
- `turn`
- `overtake`
- `spawn`
- `delete`
- `update_params`

금지 사항:
- `import`
- `while`
- `try`
- `with`
- `async`
- `lambda`
- `class`
- `raise`
- 파일 입출력
- 네트워크 호출
- `open`, `eval`, `exec`, `__import__`

주요 참조 경로:
- `state["t"]`
- `state["mode"]`
- `state["params"]`
- `state["aircraft"]`
- `ac["data"]["status"]`
- `ac["data"]["operations"]`
- `ac["data"]["spacing"]`
- `ac["data"]["routing"]`
- `ac["data"]["fifo"]`
- `ac["data"]["control"]`
- `ac["data"]["flow"]`
- `ac["data"]["wind"]`
- `ac["data"]["parameters"]`

자주 쓰는 필드:
- `ac["data"]["spacing"]["forward_flow_gap_m"]`
- `ac["data"]["spacing"]["nearest_conflict_distance_m"]`
- `ac["data"]["spacing"]["forward_flow_relative_speed_knots"]`
- `ac["data"]["fifo"]["enabled"]`
- `ac["data"]["fifo"]["queue_rank"]`
- `ac["data"]["fifo"]["can_cross_node_now"]`
- `ac["data"]["fifo"]["can_enter_next_link_now"]`
- `ac["data"]["control"]["speed"]["can_issue_now"]`
- `ac["data"]["control"]["turn"]["can_issue_now"]`
- `ac["data"]["control"]["overtake"]["can_issue_now"]`
- `ac["data"]["control"]["overtake"]["candidate_target_aircraft_id"]`
- `ac["data"]["operations"]["phase"]`
- `ac["data"]["status"]["action"]`
- `ac["data"]["status"]["wait_reason"]`

생성할 로직 요구사항:
- 로직 이름: `[여기에 로직 이름]`
- 로직 설명: `[여기에 로직 설명]`
- 적용 모드: `[corridor / route / both 중 하나]`
- 정책 목표: `[예: 최소 분리 500m 유지, 혼잡 시 추월 우선, merge 대기 시 방어적 선회]`
- 실행 cadence: `[every_step / every_1s / every_5s / startup_once_plus_monitor / mixed]`
- 엔진 cadence gate: `[예: LOGIC_MIN_INTERVAL_S = 1.0 / 2.0 / 5.0 / 사용 안 함]`
- startup 1회 동작: `[있음/없음 + 내용]`
- 지속 감시 동작: `[있음/없음 + 내용]`
- 속도 정책: `[예: forward gap < 500m이면 단계적으로 감속]`
- 추월 정책: `[예: candidate target이 있고 can_issue_now면 기체별 3초 cooldown으로 추월]`
- 선회 정책: `[예: conflict나 merge blockage가 심할 때만 fallback 선회]`
- 생성 정책: `[예: spawn 사용 안 함 / 특정 시각마다 spawn]`
- 삭제 정책: `[예: delete 사용 안 함 / 목적지 직전 delete]`
- 파라미터 오버라이드: `[예: {"sep_min_m": 500}]`
- 보수성: `[예: 같은 기체에 같은 step에서 명령 1개만, action 중이면 재명령 금지]`
- 성능 제약: `[예: nested loop 금지, 매 tick full-sort 금지, 1초 cadence 사용]`

구현 규칙:
1. 사용자가 지정한 cadence를 코드로 명시적으로 구현하라.
2. cadence가 느린 경우 반드시 `state["t"]`와 global timer/cooldown을 사용하라.
3. startup 1회 로직이 있으면 반드시 global 플래그로 중복 실행을 막아라.
4. 같은 기체에 한 step에서 명령은 최대 1개만 보내는 보수적 구조를 기본으로 하라.
5. `action`이 이미 있거나 `managed_action` phase이면 중복 `turn`/`overtake`를 보내지 마라.
6. `can_issue_now`가 false면 해당 명령을 보내지 마라.
7. `notes`에 왜 그런 명령을 냈는지 짧게 남겨라.
8. `math`는 사용 가능하지만 `import math`는 금지다.
9. 코드 길이는 40,000자 이하여야 한다.
10. 한 step에서 생성되는 명령은 최대 256개 이하여야 한다.
11. 성능을 위해 특별한 이유가 없으면 `LOGIC_MIN_INTERVAL_S`를 사용하라.
12. 특별한 이유가 없으면 전체 기체에 대한 중첩 루프 O(N^2)를 직접 작성하지 마라.
13. 매 step마다 전체 기체를 반복 정렬하는 구조를 피하라.
14. 가능한 한 엔진 제공 필드(`can_issue_now`, `candidate_target_aircraft_id`, `wait_reason`, `queue_rank`)를 우선 사용하고 무거운 자체 탐색을 줄여라.
15. high-level action(`turn`, `overtake`, `spawn`, `delete`, `update_params`)은 기본적으로 느린 cadence 또는 cooldown을 두고 실행하라.

출력 규칙:
1. 최종 출력은 Python 코드만 출력하라.
2. `LOGIC_NAME`, `LOGIC_DESCRIPTION`, `PARAM_OVERRIDES`, `control_step(state)`를 포함하라.
3. 코드만 출력하고 아무 설명도 붙이지 마라.

이름 라벨 사용 규칙:
- 사람이 읽는 설명, notes, route grouping, 보고용 문자열은 아래 필드를 우선 사용하라.
  - `ac["data"]["mission"]["route_display_name"]`
  - `ac["data"]["mission"]["origin_display_name"]`
  - `ac["data"]["mission"]["destination_display_name"]`
  - `ac["data"]["routing"]["display_name"]`
  - `ac["data"]["routing"]["short_name"]`
  - `state["labels"]["corridor_segments"]`
  - `state["labels"]["route_nodes"]`
  - `state["labels"]["route_links"]`
- 실제 명령 payload에는 이름이 아니라 ID를 사용하라.
