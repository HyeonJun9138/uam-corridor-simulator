# External API Guide

이 문서는 외부 시스템이 이 시뮬레이터를 읽고 제어하는 방법을 정리한 기준 문서입니다.

- 실시간 상태 수신: WebSocket `/ws`
- 개별 기체 제어: `set_speed`, `turn`, `overtake`, `spawn`, `delete`
- 시뮬레이터 규칙 변경: `update_params`
- 외부 코드 실행형 제어: `logic_analyze`, `logic_activate`, `logic_deactivate`, `logic_apply_params`

외부 시스템은 두 가지 방식으로 붙을 수 있습니다.

1. 자체 프로그램이 `/ws`에 직접 연결해서 상태를 읽고 명령을 보내는 방식
2. 브라우저의 `외부 로직` 창에서 Python 코드를 붙여 넣어 시뮬레이터 내부에서 매 step 실행시키는 방식

## 1. Transport

- 프로토콜: WebSocket
- 경로: `/ws`
- 주요 서버 푸시 메시지: `type = "state"`
- 주요 클라이언트 송신 메시지: `action = ...`

상태 메시지는 시뮬레이션이 실행 중이면 주기적으로 브로드캐스트되고, 정지 중에는 주요 액션 이후 즉시 갱신됩니다.

## 2. Top-Level State

서버가 보내는 대표 상태 구조는 아래와 같습니다.

```json
{
  "type": "state",
  "t": 12.4,
  "mode": "route",
  "aircraft": [],
  "heatmaps": null,
  "segments": [],
  "summary": {},
  "wind": {},
  "route_network": {},
  "params": {},
  "external_logic": {}
}
```

### 주요 필드

- `t`: 현재 시뮬레이션 시간 초 단위
- `mode`: `corridor` 또는 `route`
- `aircraft`: 전체 기체 목록
- `heatmaps`: 현재 히트맵 데이터
- `segments`: 직선 항로 세그먼트 또는 Custom 항로 링크 단위 혼잡 데이터
- `summary`: 전체 요약 지표
- `wind`: 전역 바람 상태
- `route_network`: Custom 항로 노드/링크/경로 정보
- `params`: 현재 적용 중인 전역 파라미터
- `external_logic`: 현재 활성 외부 로직 상태

## 2.1 `external_logic` Status Object

상태 메시지의 `external_logic`는 현재 외부 로직 엔진 상태를 그대로 담습니다.

```json
{
  "active": true,
  "logic_name": "My Logic",
  "logic_description": "설명",
  "source_length": 1280,
  "source_line_count": 42,
  "analysis_ok": true,
  "function_name": "control_step",
  "function_count": 1,
  "detected_param_count": 2,
  "warning_count": 0,
  "error_count": 0,
  "analysis": {},
  "last_error": null,
  "last_traceback": null,
  "last_result": {}
}
```

### `last_result`

```json
{
  "command_count": 3,
  "last_run_s": 1710000000.0,
  "last_runtime_ms": 0.421,
  "params_applied": {
    "sep_min_m": 500
  },
  "commands_by_action": {
    "set_speed": 2,
    "spawn": 1
  },
  "commands_preview": [
    {"action": "set_speed", "id": 1, "speed": 85}
  ],
  "note_count": 2,
  "notes": [
    "forward gap guard applied"
  ]
}
```

주요 의미:

- `source_length`, `source_line_count`: 현재 활성 코드 크기
- `analysis_ok`: 최근 분석 기준 정상 여부
- `function_count`: 코드 안 함수 개수
- `detected_param_count`: 감지된 `PARAM_OVERRIDES` 항목 수
- `warning_count`, `error_count`: 분석 결과 수
- `commands_by_action`: 최근 step에서 action별 명령 개수
- `commands_preview`: 최근 명령 일부 미리보기
- `note_count`, `notes`: 로직이 반환한 notes

## 3. Aircraft State

각 `aircraft[]` 항목은 빠른 UI용 기본 필드와, 정밀 제어용 `data` 필드를 동시에 가집니다.

```json
{
  "id": 12,
  "x": 1530.2,
  "y": 100.0,
  "heading_rad": 0.0,
  "remaining_m": 18469.8,
  "v_act_knots": 95.0,
  "v_cmd_knots": 100.0,
  "sta_s": 780.0,
  "eta_s": 805.4,
  "tti": 1.03,
  "battery_remaining_s": 1700.0,
  "battery_pct": 94.4,
  "l": 0.050,
  "D": 3.2,
  "R": 0.200,
  "c": 0.420,
  "delayed": false,
  "managed": false,
  "action": null,
  "action_phase": "idle",
  "action_meta": null,
  "origin_node_id": "R1C0",
  "destination_node_id": "R1C4",
  "wait_reason": null,
  "data": {}
}
```

정밀 스키마는 [AIRCRAFT_DATA_SCHEMA.md](C:/Users/AISIMULATOR2/Desktop/Code/uam_congestion/AIRCRAFT_DATA_SCHEMA.md)를 기준으로 사용하면 됩니다.

외부 제어 로직에서 특히 자주 보는 섹션은 아래입니다.

- `data.control`
- `data.operations`
- `data.spacing`
- `data.routing`
- `data.fifo`
- `data.parameters`
- `data.wind`
- `data.schedule`

## 4. Global Params

상태의 `params`는 현재 시뮬레이터 전역 설정의 즉시 스냅샷입니다.

대표 항목:

- `simulation_mode`
- `path_length_m`
- `lane_width_m`
- `spawn_margin_m`
- `auto_spawn_enabled`
- `spawn_spacing_m`
- `route_grid_spacing_m`
- `route_row_count`
- `route_row_gap_m`
- `v_free_knots`
- `v_init_knots`
- `v_min_knots`
- `v_max_knots`
- `wind_enabled`
- `wind_level`
- `a_max_mps2`
- `b_max_mps2`
- `sep_min_m`
- `fifo_queue_sep_scale`
- `fifo_node_clearance_min_m`
- `fifo_node_clearance_scale`
- `fifo_hold_buffer_min_m`
- `fifo_hold_buffer_scale`
- `fifo_approach_sep_scale`
- `fifo_approach_time_s`
- `segment_length_m`
- `seg_w_overflow`
- `seg_w_tti`
- `sigma_parallel_m`
- `sigma_perp_m`
- `lookahead_L_m`
- `delay_window_T_s`
- `delayed_thr_s`
- `rho_ref`
- `cong_ref`
- `dt_s`
- `realtime_factor`

주의:

- 일부 파라미터는 모드 전용입니다. 예: FIFO 계열은 `route`에서 의미가 큽니다.
- 파라미터 적용 시 내부 정규화가 걸립니다. 예: `sigma_parallel_m`은 최소 분리 기준으로 clamp될 수 있습니다.
- 서버 응답의 `report.applied`는 정규화 후 실제 반영값입니다.

## 5. Incoming Commands

외부 시스템은 아래 메시지를 `/ws`로 보냅니다.

### 5.1 시뮬레이션 제어

#### 시작

```json
{ "action": "start" }
```

#### 일시정지

```json
{ "action": "pause" }
```

#### 리셋

```json
{ "action": "reset" }
```

#### 1 step 실행

```json
{ "action": "step" }
```

#### 모드 변경

```json
{ "action": "set_mode", "mode": "corridor" }
```

또는

```json
{ "action": "set_mode", "mode": "route" }
```

### 5.2 개별 기체 제어

#### 속도 지시

```json
{
  "action": "set_speed",
  "id": 12,
  "speed": 90
}
```

#### 우선회

```json
{
  "action": "turn",
  "id": 12,
  "diameter_m": 800
}
```

#### 추월

```json
{
  "action": "overtake",
  "id": 12,
  "lateral_offset_m": 100,
  "speed_boost_knots": 20,
  "target_id": 9
}
```

설명:

- `target_id`는 선택 사항이지만, 외부 교통관리 로직에서는 명시 지정이 권장됩니다.
- 실제 추월 가능 여부는 엔진이 다시 판단합니다.

#### 생성

직선 항로:

```json
{ "action": "spawn" }
```

Custom 항로 특정 시작 노드:

```json
{
  "action": "spawn",
  "start_node_id": "R1C0"
}
```

#### 삭제

```json
{
  "action": "delete",
  "id": 12
}
```

### 5.3 파라미터 변경

```json
{
  "action": "update_params",
  "params": {
    "sep_min_m": 250,
    "fifo_approach_time_s": 5.0
  }
}
```

서버는 `params_ack` 메시지로 결과를 돌려줍니다.

```json
{
  "type": "params_ack",
  "params": { "...": "..." },
  "report": {
    "applied": { "...": "..." },
    "errors": []
  }
}
```

## 6. External Logic Messages

외부 로직 창 또는 자체 클라이언트는 아래 액션을 사용할 수 있습니다.

### 6.1 코드 분석

```json
{
  "action": "logic_analyze",
  "code": "..."
}
```

분석 시 추가로 확인해야 하는 제약:

- 코드 길이 최대 40,000자
- `control_step(state)` 필수
- 금지 AST 구문/호출 포함 시 실패

응답:

```json
{
  "type": "logic_analysis",
  "analysis": {
    "ok": true,
    "function_name": "control_step",
    "detected_params": {},
    "errors": [],
    "warnings": [],
    "summary": []
  }
}
```

### 6.2 코드 활성화

```json
{
  "action": "logic_activate",
  "code": "...",
  "auto_apply_detected_params": true
}
```

활성화 시에는 분석 통과 후 한 번 더 probe state로 실행 검증합니다. 분석은 통과했어도 실행 검증에 실패하면 활성화되지 않습니다.

응답:

```json
{
  "type": "logic_activation",
  "ok": true,
  "analysis": {},
  "logic": {},
  "param_report": {
    "applied": {},
    "errors": []
  }
}
```

### 6.3 코드 비활성화

```json
{ "action": "logic_deactivate" }
```

응답:

```json
{
  "type": "logic_status",
  "logic": {
    "active": false
  }
}
```

### 6.4 감지된 파라미터만 적용

```json
{
  "action": "logic_apply_params",
  "params": {
    "sep_min_m": 500
  }
}
```

응답:

```json
{
  "type": "logic_params_applied",
  "params": {
    "sep_min_m": 500
  },
  "report": {
    "applied": {
      "sep_min_m": 500.0
    },
    "errors": []
  }
}
```

### 6.5 현재 로직 상태 조회

```json
{ "action": "logic_get_status" }
```

응답:

```json
{
  "type": "logic_status",
  "logic": {
    "active": true,
    "logic_name": "My Logic",
    "logic_description": "..."
  }
}
```

## 7. External Logic Code Contract

외부 코드 실행형 제어는 Python 코드 문자열을 받아 실행합니다.

### 필수 함수

```python
def control_step(state):
    return {"commands": [], "params": {}}
```

### 선택 상수

```python
LOGIC_NAME = "My Logic"
LOGIC_DESCRIPTION = "설명"
PARAM_OVERRIDES = {"sep_min_m": 500}
```

### 반환 형식

허용 형식 1:

```python
return {
    "commands": [...],
    "params": {...},
    "notes": [...]
}
```

허용 형식 2:

```python
return [
    {"action": "set_speed", "id": 1, "speed": 90}
]
```

주의:

- 한 step당 명령 최대 256개
- `notes`는 선택 사항이지만, 디버깅을 위해 권장
- `params`는 현재 step에서 즉시 파라미터 반영용

### 허용 명령

- `set_speed`
- `turn`
- `overtake`
- `spawn`
- `delete`
- `update_params`

### 안전 제약

아래는 금지됩니다.

- `import`
- `while`
- `try`
- `with`
- `async`
- `lambda`
- `class`
- dunder 이름 접근
- `open`, `eval`, `exec`, `__import__` 등 위험 호출

추가 참고:

- `math`는 이미 주입되어 있으므로 `import math`를 쓰지 않아야 합니다.
- 허용 빌트인은 `abs`, `all`, `any`, `bool`, `dict`, `enumerate`, `float`, `int`, `len`, `list`, `max`, `min`, `range`, `round`, `set`, `sorted`, `str`, `sum`, `tuple`, `zip` 정도입니다.

허용 빌트인은 제한적이며, `math` 모듈만 노출됩니다.

## 8. Recommended Logic Design Pattern

외부 TM/UATM 로직은 보통 아래 순서로 작성하면 안정적입니다.

1. `data.operations`로 현재 phase와 hold 원인을 확인
2. `data.spacing`으로 전방/후방 거리와 최근접 conflict를 확인
3. `data.fifo`로 노드 통과 가능 여부와 queue 순번을 확인
4. `data.routing`으로 현재 링크 또는 세그먼트 상황을 확인
5. `data.wind`로 종풍/횡풍 영향을 반영
6. `data.control`로 지금 명령 가능한 상태인지 확인
7. 필요 시 `data.parameters`를 기준으로 현재 운영 규칙에 맞춰 판단

## 9. Recommended Failure Handling

외부 시스템은 아래를 반드시 고려하는 편이 좋습니다.

- 특정 기체가 이미 `action != null`이면 중복 명령을 피할 것
- `can_issue_now`가 `false`인 제어는 보내지 않거나 별도 큐잉할 것
- FIFO 합류 전후에는 `wait_reason`, `can_cross_node_now`, `can_enter_next_link_now`를 같이 볼 것
- 추월은 `data.control.overtake.candidate_target_aircraft_id`와 `data.spacing`을 함께 볼 것
- `report.errors`가 있으면 외부 UI에 그대로 표시할 것

## 10. Related Docs

- [AIRCRAFT_DATA_SCHEMA.md](C:/Users/AISIMULATOR2/Desktop/Code/uam_congestion/AIRCRAFT_DATA_SCHEMA.md)
- [EXTERNAL_LOGIC_STUDIO_GUIDE.md](C:/Users/AISIMULATOR2/Desktop/Code/uam_congestion/EXTERNAL_LOGIC_STUDIO_GUIDE.md)
- [EXTERNAL_LOGIC_PROMPT_TEMPLATE.md](C:/Users/AISIMULATOR2/Desktop/Code/uam_congestion/EXTERNAL_LOGIC_PROMPT_TEMPLATE.md)
- [EXTERNAL_LOGIC_SAMPLE_ADAPTIVE_GUARD.py](C:/Users/AISIMULATOR2/Desktop/Code/uam_congestion/EXTERNAL_LOGIC_SAMPLE_ADAPTIVE_GUARD.py)

## 11. External Logic Pitfalls

- `spacing.forward_flow_relative_speed_knots` is `front - self`, not `self - front`.
- If `forward_flow_relative_speed_knots < 0`, the current aircraft is faster than the aircraft ahead.
- `control.overtake.can_issue_now` already includes engine-side candidate filtering.
- `spacing.shared_remaining_link_count` is a route conflict metric and should not be used as a mandatory corridor overtake condition.
