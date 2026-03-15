# External API Guide

이 문서는 외부 시스템 또는 LLM이 이 시뮬레이터의 외부 로직 계약을 정확히 이해하도록 정리한 최소 가이드입니다.

핵심 요약:
- 외부 로직은 `control_step(state)`로 작성한다.
- 이 함수는 시뮬레이션의 **매 simulation step마다 1회** 호출된다.
- 기본 `dt_s`는 `0.2s`이므로 보통 초당 약 5회 호출된다.
- 따라서 외부 로직은 "한 번만 실행"되는 함수가 아니라 **계속 반복 호출되는 제어 루프**로 봐야 한다.
- 고수준 명령(`turn`, `overtake`, `spawn`, `delete`, `update_params`)은 one-shot 성격이고, `set_speed`는 persistent 성격이다.
- 성능 보호를 위해 외부 로직에는 full UI state가 아니라 compact logic state만 전달된다.
- 무거운 정책은 `LOGIC_MIN_INTERVAL_S`를 사용해 cadence를 낮추는 것이 권장된다.

## 1. Execution Model

외부 로직은 다음 순서로 동작한다.

1. 현재 시뮬레이터 상태를 `state`로 만든다.
2. 외부 로직 `control_step(state)`를 호출한다.
3. 외부 로직이 `commands`, `params`, `notes`를 반환한다.
4. 서버가 반환된 명령을 엔진에 적용한다.
5. 엔진이 실제 물리 step과 안전 판정을 수행한다.

즉 외부 로직은 "정책 제안자"이고, 엔진은 "최종 집행자"다.

### 1.1 Call Frequency

- `control_step(state)`는 **매 simulation step**마다 1회 호출된다.
- 기본 `dt_s`는 `0.2s`다.
- 따라서 기본적으로 약 **5 Hz**다.
- `dt_s`와 `realtime_factor`는 바뀔 수 있으므로, 외부 로직은 절대로 "초당 1회"로 가정하면 안 된다.

### 1.2 Time Reference

- 현재 시뮬레이션 시간은 `state["t"]`에 들어온다.
- 단위는 초다.
- "매 1초마다", "매 5초마다", "매 10분마다" 같은 정책은 모두 `state["t"]` 기준으로 구현해야 한다.

### 1.3 Persistent Globals

외부 로직 코드의 module-global 변수는 로직이 활성화된 동안 유지된다.

따라서 아래 같은 상태를 global 변수로 저장해도 된다.
- startup 1회 실행 여부
- 기체별 마지막 명령 시각
- 기체별 cooldown
- 다음 의사결정 시각
- 최근 추월/선회 목표

단, 사용자가 코드를 수정하거나 로직을 다시 활성화하면 이 global 상태는 초기화된다고 보면 된다.

### 1.4 How To Implement Cadence Correctly

#### 매 step마다 실행되는 로직

예:
- 분리 감시
- wait 상태 감시
- 현재 conflict 감시
- 매 step speed correction

이 경우 `control_step(state)` 안에서 매 호출마다 바로 판단하면 된다.

#### 매 N초마다 실행되는 로직

예:
- 1초마다 추월 판단
- 5초마다 생성 판단
- 10초마다 global parameter tuning

이 경우 `state["t"]`와 global `next_run_t`를 사용해 직접 gate 해야 한다.

#### 시작 시 1회만 실행되는 로직

예:
- 처음 활성화될 때 `sep_min_m` 오버라이드
- 시뮬레이션 시작 직후 특정 spawn 배치

이 경우 global `initialized = False` 같은 플래그를 두고 첫 실행에만 동작시켜야 한다.

## 2. What External Logic Can Control

외부 로직은 한 번의 `control_step(state)` 호출에서 여러 기체를 동시에 조정할 수 있다.

즉:
- 전체 `state["aircraft"]`를 읽을 수 있고
- 같은 step에서 여러 기체에 대해 명령을 만들 수 있다
- 단, 한 step당 전체 명령 수는 최대 256개다

지원 명령:
- `set_speed`
- `turn`
- `overtake`
- `spawn`
- `delete`
- `update_params`

## 3. Command Semantics

이 부분을 잘못 이해하면 LLM이 이상한 로직을 만든다.

### 3.1 `set_speed`

- persistent 명령이다
- 한 번 보내면 그 기체의 command speed가 바뀌고, 이후 다시 바꾸기 전까지 유지된다
- 따라서 매 step마다 같은 `set_speed`를 계속 보낼 필요는 없다

### 3.2 `turn`

- one-shot 명령이다
- 선회 action을 시작시키는 요청이다
- 이미 `action` 중인 기체에 계속 반복 전송하면 안 된다

### 3.3 `overtake`

- one-shot 명령이다
- 추월 action을 시작시키는 요청이다
- 이미 `action` 중인 기체에 반복 전송하면 안 된다

### 3.4 `spawn`

- one-shot 명령이다
- 조건 없이 매 step 보내면 계속 새 기체가 생성된다
- 따라서 반드시 시간 gate나 조건 gate를 둬야 한다

### 3.5 `delete`

- one-shot 명령이다
- 보통 목적지 도착 직전 또는 특정 실험 조건에서만 사용한다

### 3.6 `update_params`

- one-shot 명령이지만, 결과는 전역적으로 지속된다
- 예를 들어 `sep_min_m`를 한 번 500으로 바꾸면 이후 step에도 계속 500이 유지된다
- 따라서 startup 1회 또는 느린 cadence로만 보내는 것이 일반적이다

## 4. Engine Has Final Authority

외부 로직이 명령을 만든다고 해서 무조건 실행되는 것은 아니다.

엔진은 최종적으로 다음을 다시 판정한다.
- 실제 분리 가능성
- 추월 가능성
- 선회 가능성
- merge 진입 가능성
- FIFO / node release / downstream separation

즉 외부 로직은 정책을 제안하지만, 엔진 feasibility check가 마지막에 명령을 거절할 수 있다.

중요 신호:
- `control.speed.can_issue_now`
- `control.turn.can_issue_now`
- `control.overtake.can_issue_now`

이 값이 false이면 해당 명령은 보내지 않는 것이 맞다.

## 5. Node / FIFO Rules

Node 운영 규칙은 엔진 내부에 들어 있다.

### 5.1 Wait Reasons

대표 `wait_reason`:
- `spacing`
- `start_hold`
- `fifo_hold`
- `node_hold`
- `merge_hold`

### 5.2 Straight Node vs Merge Node

- `route` 모드에서 FIFO는 **merge node**에서만 의미가 있다
- straight node는 FIFO 운영 대상이 아니다
- 따라서 단순 직선 route node를 merge처럼 해석하면 안 된다

### 5.3 What External Logic Should Read

외부 로직은 아래 필드를 읽고 의사결정하면 된다.
- `ac["data"]["fifo"]["enabled"]`
- `ac["data"]["fifo"]["queue_rank"]`
- `ac["data"]["fifo"]["can_cross_node_now"]`
- `ac["data"]["fifo"]["can_enter_next_link_now"]`
- `ac["data"]["status"]["wait_reason"]`

단, node scheduler 자체를 외부 로직이 다시 구현하려고 하지 말고, 엔진 상태를 보고 정책만 조정하는 것이 맞다.

## 6. Important Aircraft Fields

자세한 전체 스키마는 [AIRCRAFT_DATA_SCHEMA.md](C:/Users/AISIMULATOR2/Desktop/Code/uam_congestion/AIRCRAFT_DATA_SCHEMA.md)를 본다.

외부 로직에서 자주 보는 영역:
- `ac["data"]["status"]`
- `ac["data"]["operations"]`
- `ac["data"]["spacing"]`
- `ac["data"]["routing"]`
- `ac["data"]["fifo"]`
- `ac["data"]["control"]`
- `ac["data"]["flow"]`
- `ac["data"]["wind"]`
- `ac["data"]["parameters"]`

특히 자주 쓰는 필드:
- `forward_flow_gap_m`
- `nearest_conflict_distance_m`
- `forward_flow_relative_speed_knots`
- `candidate_target_aircraft_id`
- `can_issue_now`
- `queue_rank`
- `can_cross_node_now`
- `can_enter_next_link_now`
- `phase`
- `action`
- `wait_reason`

### 6.1 Relative Speed Sign Convention

중요:
- `spacing.forward_flow_relative_speed_knots`는 `front - self`다
- 음수면 현재 기체가 더 빠르다
- 양수면 앞 기체가 더 빠르다

## 7. Top-Level State

외부 로직이 받는 top-level state의 핵심 필드:

```json
{
  "t": 12.4,
  "mode": "route",
  "aircraft": [],
  "params": {},
  "summary": {},
  "external_logic": {}
}
```

주요 의미:
- `t`: 현재 시뮬레이션 시간
- `mode`: `corridor` 또는 `route`
- `aircraft`: 현재 기체 리스트
- `params`: 현재 전역 파라미터
- `summary`: 전체 요약
- `external_logic`: 현재 외부 로직 상태

## 8. WebSocket Actions

기본 WebSocket 경로:
- `/ws`

주요 action:
- `start`
- `pause`
- `reset`
- `step`
- `set_mode`
- `set_speed`
- `turn`
- `overtake`
- `spawn`
- `delete`
- `update_params`
- `logic_analyze`
- `logic_activate`
- `logic_deactivate`
- `logic_apply_params`

## 9. Practical Design Guidance For LLM-Generated Logic

LLM이 가장 자주 틀리는 포인트는 아래다.

1. `control_step(state)`가 1회성 함수라고 오해함
2. `set_speed`를 one-shot으로 이해하지 못함
3. `turn`/`overtake`를 매 step 반복 발행함
4. startup 1회 로직과 continuous 감시 로직을 구분하지 않음
5. `state["t"]`를 사용하지 않고 "초당 1회"라고 가정함
6. straight node에도 FIFO를 적용하려고 함
7. 모든 기체를 매 step 중첩 루프로 전부 비교해 O(N^2) 코드를 만듦
8. 매 step마다 불필요하게 full sort를 반복함

따라서 LLM 프롬프트에는 아래를 꼭 명시해야 한다.
- 실행 cadence
- startup 1회 동작 여부
- continuous 감시 동작 여부
- high-level action cooldown
- 같은 기체에 한 step에서 명령 1개 제한 여부

## 10. Performance Guidance

외부 로직이 느려지면 시뮬레이터 전체가 같이 느려진다. 이유는 외부 로직이 메인 시뮬레이션 루프 안에서 실행되기 때문이다.

권장 사항:
- 특별한 이유가 없으면 `LOGIC_MIN_INTERVAL_S = 1.0` 또는 `2.0`부터 시작
- `turn`, `overtake`, `spawn`, `delete`, `update_params`는 per-step이 아니라 느린 cadence나 cooldown으로 실행
- 가능한 한 엔진이 제공하는 후보 필드(`candidate_target_aircraft_id`, `can_issue_now`, `wait_reason`, `queue_rank`)를 직접 사용
- 매 step 전체 기체 중첩 비교 O(N^2) 금지
- 매 step 전체 정렬 반복 금지
- 필요하면 기체별 마지막 명령 시각을 global dict에 저장해서 중복 판단을 줄일 것

외부 로직 상태에는 아래 성능 필드가 포함된다.
- `logic_min_interval_s`
- `runtime_ema_ms`
- `slow_run_count`
- `performance_warning`

즉 외부 로직이 과하게 무거우면 상태 패널에서 바로 확인할 수 있다.

## 11. Recommended Minimal Delivery Set

외부 사용자에게 코드 생성을 맡길 때는 보통 아래 2개만 전달하면 된다.
- `EXTERNAL_LOGIC_SAMPLE_ADAPTIVE_GUARD.py`
- `EXTERNAL_LOGIC_PROMPT_TEMPLATE.md`

외부 시스템이 직접 `/ws`에 붙어서 제어까지 할 경우에는 아래도 추가한다.
- `EXTERNAL_API_GUIDE.md`
- `AIRCRAFT_DATA_SCHEMA.md`

## Human-Readable Labels For External Logic

External logic can now rely on readable names as well as raw IDs.

### Per-aircraft labels

Useful fields:

- `ac["data"]["mission"]["origin_display_name"]`
- `ac["data"]["mission"]["destination_display_name"]`
- `ac["data"]["mission"]["route_display_name"]`
- `ac["data"]["routing"]["display_name"]`
- `ac["data"]["routing"]["short_name"]`
- `ac["data"]["operations"]["active_link_display_name"]`
- `ac["data"]["fifo"]["exit_node_display_name"]`

These fields are for explanation, grouping, route selection, and notes.
Commands must still use IDs, not names.

### Top-level labels catalog

`control_step(state)` now also receives:

- `state["labels"]["corridor_route"]`
- `state["labels"]["corridor_segments"]`
- `state["labels"]["route_nodes"]`
- `state["labels"]["route_links"]`

This catalog is useful when external logic needs a stable readable lookup table without scanning every aircraft.

### Recommended usage rule

- Use `*_id` fields when issuing commands.
- Use `*_display_name` or `*_short_name` for notes, logs, reports, LLM summaries, or route grouping.
