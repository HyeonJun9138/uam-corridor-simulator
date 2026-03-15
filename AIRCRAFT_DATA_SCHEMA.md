# Aircraft Data Schema

이 문서는 `state.aircraft[].data` 구조를 외부 API 사용자 기준으로 설명합니다.

- 소스 기준: `backend/simulation.py`
- 현재 스키마 버전: `3`
- 위치: 모든 기체는 `state.aircraft[]` 안에 있고, 상세 정보는 `data` 하위에 있습니다.

## 1. Top Level

```json
{
  "schema_version": 3,
  "identity": {},
  "status": {},
  "mission": {},
  "position": {},
  "speed": {},
  "wind": {},
  "schedule": {},
  "energy": {},
  "operations": {},
  "control": {},
  "flow": {},
  "spacing": {},
  "routing": {},
  "fifo": {},
  "parameters": {}
}
```

주의:

- `corridor` 전용 값이나 `route` 전용 값은 해당 모드가 아니면 `null`일 수 있습니다.
- 값은 매 state 생성 시점마다 갱신됩니다.

## 2. identity

```json
{
  "aircraft_id": 12,
  "simulation_mode": "route"
}
```

- `aircraft_id`: 기체 고유 ID
- `simulation_mode`: `corridor` 또는 `route`

## 3. status

```json
{
  "route_mode": true,
  "has_departed": true,
  "managed": false,
  "delayed": false,
  "wait_reason": null,
  "action": null,
  "action_phase": "idle",
  "action_meta": null
}
```

- `route_mode`: Custom 항로 여부
- `has_departed`: 실제 출발 여부
- `managed`: 현재 일반 흐름 계산 대상이 아닌 관리 액션 상태인지 여부
- `delayed`: 누적 지연이 임계치를 넘었는지 여부
- `wait_reason`: `spacing`, `start_hold`, `fifo_hold`, `node_hold`, `merge_hold` 등
- `action`: `turn`, `overtake`, 또는 `null`
- `action_phase`: 현재 액션 세부 phase
- `action_meta`: 엔진 내부 액션 상태의 원본 스냅샷

## 4. mission

```json
{
  "origin_node_id": "R1C0",
  "destination_node_id": "R2C4",
  "route_node_ids": ["R1C0", "R1C1", "R2C2", "R2C3", "R2C4"],
  "route_link_ids": ["R1C0->R1C1", "R1C1->R2C2"]
}
```

- `origin_node_id`: 시작 노드
- `destination_node_id`: 도착 노드
- `route_node_ids`: 계획된 노드 시퀀스
- `route_link_ids`: 계획된 링크 시퀀스

직선 항로에서는 노드/링크 목록이 비어 있을 수 있습니다.

## 5. position

```json
{
  "x_m": 1530.2,
  "y_m": 100.0,
  "progress_m": 1530.2,
  "remaining_m": 18469.8,
  "path_total_m": 20000.0,
  "progress_ratio": 0.0765,
  "heading_rad": 0.0,
  "heading_deg": 0.0,
  "track_rad": 0.02,
  "track_deg": 1.15
}
```

- `x_m`, `y_m`: 월드 좌표
- `progress_m`: 현재 경로 기준 누적 진행거리
- `remaining_m`: 남은 거리
- `path_total_m`: 전체 경로 길이
- `progress_ratio`: 0~1 범위 진행률
- `heading_rad`, `heading_deg`: 기수 방향
- `track_rad`, `track_deg`: 실제 지상 이동 방향

## 6. speed

```json
{
  "command_knots": 100.0,
  "air_knots": 98.2,
  "actual_knots": 95.0,
  "ground_knots": 95.0,
  "ground_vx_mps": 48.87,
  "ground_vy_mps": 0.0
}
```

- `command_knots`: 현재 지시 속도
- `air_knots`: 공기 기준 속도
- `actual_knots`: 현재 UI 기준 실제 속도
- `ground_knots`: 지상속도
- `ground_vx_mps`, `ground_vy_mps`: 지상 속도 벡터

## 7. wind

```json
{
  "x_mps": 2.0,
  "y_mps": -1.0,
  "x_knots": 3.89,
  "y_knots": -1.94,
  "mag_mps": 2.236,
  "mag_knots": 4.347,
  "dir_deg": 333.43,
  "along_mps": 2.0,
  "cross_mps": -1.0,
  "along_knots": 3.89,
  "cross_knots": -1.94
}
```

- `x_mps`, `y_mps`: 바람 벡터
- `mag_mps`, `mag_knots`: 바람 세기
- `dir_deg`: 바람 방향각
- `along_*`: 현재 기수 기준 종풍 성분
- `cross_*`: 현재 기수 기준 횡풍 성분

## 8. schedule

```json
{
  "spawn_time_s": 12.0,
  "std_s": 12.0,
  "depart_time_s": 12.2,
  "sta_s": 780.0,
  "eta_s": 805.4,
  "scheduled_total_s": 768.0,
  "estimated_total_s": 793.2,
  "departure_delay_s": 0.2,
  "arrival_delay_s": 25.4,
  "tti": 1.03,
  "flight_time_s": 120.0
}
```

- `spawn_time_s`: 생성 시각
- `std_s`: 계획 출발 시각
- `depart_time_s`: 실제 출발 시각
- `sta_s`: 계획 도착 시각
- `eta_s`: 현재 추정 도착 시각
- `scheduled_total_s`: 계획 비행시간
- `estimated_total_s`: 추정 비행시간
- `departure_delay_s`: 출발 지연
- `arrival_delay_s`: 도착 지연 추정
- `tti`: travel time index
- `flight_time_s`: 실제 누적 비행시간

## 9. energy

```json
{
  "battery_remaining_s": 1710.0,
  "battery_pct": 95.0,
  "battery_used_pct": 5.0,
  "endurance_s": 1800.0
}
```

- `battery_remaining_s`: 남은 endurance
- `battery_pct`: 남은 배터리 비율
- `battery_used_pct`: 사용 비율
- `endurance_s`: 총 endurance 기준

## 10. operations

현재 운용 상태와 제약 상태를 정리한 섹션입니다.

```json
{
  "sim_time_s": 120.0,
  "phase": "holding",
  "constraint_source": "fifo_hold",
  "is_pre_departure": false,
  "is_completed": false,
  "is_holding": true,
  "is_action_active": false,
  "hold_flags": {
    "spacing": false,
    "start_hold": false,
    "fifo_hold": true,
    "node_hold": false,
    "merge_hold": false
  },
  "active_link_id": "R1C1->R2C2",
  "remaining_links_count": 2,
  "remaining_nodes_count": 2,
  "distance_to_next_node_m": 420.0,
  "distance_to_exit_node_m": 420.0,
  "segment_index": null,
  "remaining_segments_count": null,
  "is_on_final_path_element": false
}
```

### 공통 필드

- `sim_time_s`
- `phase`: `pre_departure`, `enroute`, `holding`, `managed_action`, `completed`
- `constraint_source`
- `is_pre_departure`
- `is_completed`
- `is_holding`
- `is_action_active`
- `hold_flags.*`
- `is_on_final_path_element`

### route 모드 중심 필드

- `active_link_id`
- `remaining_links_count`
- `remaining_nodes_count`
- `distance_to_next_node_m`
- `distance_to_exit_node_m`

### corridor 모드 중심 필드

- `segment_index`
- `remaining_segments_count`

## 11. control

제어 가능 여부와 현재 제어 상태를 모아 둔 섹션입니다.

### 11.1 control.speed

```json
{
  "can_issue_now": true,
  "command_knots": 100.0,
  "actual_knots": 95.0,
  "allowed_min_knots": 60.0,
  "allowed_max_knots": 120.0,
  "default_free_knots": 100.0,
  "default_init_knots": 100.0
}
```

### 11.2 control.turn

```json
{
  "supported": true,
  "ui_label": "우선회",
  "can_issue_now": true,
  "active": false,
  "phase": null,
  "diameter_m": null,
  "radius_m": null,
  "center_x_m": null,
  "center_y_m": null,
  "theta_rad": null,
  "theta_end_rad": null,
  "remaining_angle_rad": null,
  "turn_sign": null,
  "resume_heading_rad": null,
  "resume_route_progress_m": null
}
```

설명:

- `can_issue_now`: 현재 선회 명령 가능 여부
- `active`: 현재 선회 액션 수행 중인지 여부
- `resume_*`: 선회 종료 후 복귀 기준

### 11.3 control.overtake

```json
{
  "supported": true,
  "can_issue_now": true,
  "active": false,
  "phase": null,
  "candidate_target_aircraft_id": 9,
  "target_aircraft_id": null,
  "reference_aircraft_id": 9,
  "reference_flow_gap_m": 620.0,
  "reference_distance_m": 620.0,
  "reference_relative_speed_knots": -5.0,
  "lateral_offset_m": null,
  "transition_m": null,
  "boost_command_knots": null,
  "start_x_m": null,
  "start_progress_m": null,
  "merge_start_x_m": null,
  "merge_start_progress_m": null,
  "current_offset_m": 0.0,
  "pass_completed": null
}
```

설명:

- `candidate_target_aircraft_id`: 지금 추월 명령을 넣었을 때 기본 후보
- `target_aircraft_id`: 현재 실제 추월 중인 대상
- `reference_flow_gap_m`: 흐름 기준 앞 기체와 간격
- `reference_distance_m`: 실제 2D 거리
- `current_offset_m`: 중심선 대비 현재 횡방향 오프셋
- `pass_completed`: 추월 완료 여부

### 11.4 control.lifecycle

```json
{
  "can_delete_now": true
}
```

## 12. flow

혼잡 계산과 관련된 핵심 지표입니다.

```json
{
  "include_in_flow": true,
  "speed_loss_ratio_l": 0.05,
  "delay_accumulated_s": 3.2,
  "delayed_ahead_ratio_R": 0.20,
  "density_rho": 0.42,
  "congestion_c": 0.18,
  "rho_ref": 3.0,
  "cong_ref": 3.0,
  "delay_window_s": 60.0,
  "delayed_threshold_s": 10.0,
  "lookahead_m": 2000.0
}
```

- `include_in_flow`: 혼잡 계산 대상 포함 여부
- `speed_loss_ratio_l`
- `delay_accumulated_s`
- `delayed_ahead_ratio_R`
- `density_rho`
- `congestion_c`

## 13. spacing

분리와 근접도 판단용 핵심 섹션입니다.

```json
{
  "min_separation_m": 200.0,
  "flow_reference": "same_active_link",
  "forward_flow_aircraft_id": 9,
  "forward_flow_gap_m": 620.0,
  "forward_flow_distance_m": 623.5,
  "forward_flow_relative_speed_knots": -5.0,
  "forward_sep_margin_m": 420.0,
  "rear_flow_aircraft_id": 14,
  "rear_flow_gap_m": 700.0,
  "rear_flow_distance_m": 700.4,
  "rear_flow_relative_speed_knots": 3.0,
  "rear_sep_margin_m": 500.0,
  "nearest_aircraft_id": 9,
  "nearest_aircraft_distance_m": 623.5,
  "nearest_aircraft_sep_margin_m": 423.5,
  "nearest_conflict_aircraft_id": null,
  "nearest_conflict_distance_m": null,
  "nearest_conflict_sep_margin_m": null,
  "shared_remaining_link_count": 2
}
```

### 의미

- `flow_reference`: `same_corridor_track` 또는 `same_active_link`
- `forward_*`: 같은 흐름 기준 전방 기체
- `rear_*`: 같은 흐름 기준 후방 기체
- `nearest_*`: 전체 근접 기체 기준
- `nearest_conflict_*`: 충돌 위험 기준 최근접 기체
- `shared_remaining_link_count`: Custom 항로에서 앞으로 공유하는 링크 수

## 14. routing

현재 기체가 속한 로컬 운항 구간 컨텍스트입니다.

### route 모드 예시

```json
{
  "kind": "route_link",
  "id": "R1C1->R2C2",
  "index": 1,
  "entry_node_id": "R1C1",
  "exit_node_id": "R2C2",
  "next_link_id": "R2C2->R2C3",
  "local_progress_m": 1800.0,
  "local_remaining_m": 3200.0,
  "length_m": 5000.0,
  "count": 3,
  "mean_speed_knots": 98.2,
  "score": 0.22,
  "level": 1,
  "capacity_aircraft": 25.0,
  "occupancy_ratio": 0.12,
  "overflow_ratio": 0.0
}
```

### corridor 모드 예시

```json
{
  "kind": "corridor_segment",
  "id": "SEG-1",
  "index": 1,
  "count": 4,
  "mean_speed_knots": 93.0,
  "score": 0.35,
  "level": 2,
  "capacity_aircraft": 50.0,
  "occupancy_ratio": 0.08,
  "overflow_ratio": 0.0,
  "x_start_m": 0.0,
  "x_end_m": 10000.0
}
```

## 15. fifo

Custom 항로에서만 의미가 있는 합류/교차 노드 관리 정보입니다.

```json
{
  "queue_rank": 1,
  "request_time_s": 122.0,
  "request_age_s": 4.2,
  "queue_size": 3,
  "queue_head_aircraft_id": 7,
  "is_queue_head": false,
  "entry_node_id": "R1C1",
  "exit_node_id": "R2C2",
  "node_release_time_s": 128.5,
  "node_release_in_s": 2.3,
  "next_link_id": "R2C2->R2C3",
  "next_link_count": 2,
  "next_link_capacity_aircraft": 25.0,
  "next_link_occupancy_ratio": 0.08,
  "next_link_nearest_gap_m": 310.0,
  "next_link_sep_margin_m": 110.0,
  "can_cross_node_now": false,
  "can_enter_next_link_now": true
}
```

핵심 의미:

- `queue_rank`: 현재 FIFO 순번
- `queue_head_aircraft_id`: 현재 통과 우선권 기체
- `node_release_*`: 노드 통과 가능한 시각
- `can_cross_node_now`: 지금 즉시 노드 진입 가능한지
- `can_enter_next_link_now`: downstream 링크 진입 가능한지

## 16. parameters

각 기체에 복제된 현재 운용 파라미터 스냅샷입니다.

### parameters.simulation

- `simulation_mode`
- `dt_s`
- `realtime_factor`

### parameters.geometry

- `path_length_m`
- `lane_width_m`
- `spawn_margin_m`
- `route_grid_spacing_m`
- `route_row_count`
- `route_row_gap_m`
- `route_samples_per_segment`

### parameters.speed_policy

- `v_free_knots`
- `v_init_knots`
- `v_min_knots`
- `v_max_knots`
- `a_max_mps2`
- `b_max_mps2`

### parameters.separation_policy

- `sep_min_m`
- `spawn_spacing_m`

### parameters.fifo_policy

- `fifo_queue_sep_scale`
- `fifo_node_clearance_min_m`
- `fifo_node_clearance_scale`
- `fifo_hold_buffer_min_m`
- `fifo_hold_buffer_scale`
- `fifo_approach_sep_scale`
- `fifo_approach_time_s`

### parameters.congestion_policy

- `segment_length_m`
- `seg_w_overflow`
- `seg_w_tti`
- `sigma_parallel_m`
- `sigma_perp_m`
- `lookahead_L_m`
- `lookahead_W_m`
- `delay_window_T_s`
- `delayed_thr_s`
- `rho_ref`
- `cong_ref`

### parameters.wind_policy

- `wind_enabled`
- `wind_level`

## 17. External Controller Recommended Read Order

외부 교통관리 로직에서는 보통 아래 순서로 읽는 편이 안정적입니다.

1. `status`, `operations`
2. `position`, `speed`, `wind`
3. `spacing`
4. `routing`
5. `fifo`
6. `control`
7. `flow`
8. `schedule`
9. `parameters`

## 18. External Logic Notes

- `spacing.forward_flow_relative_speed_knots` and `spacing.rear_flow_relative_speed_knots` use `other - self`.
- A negative `forward_flow_relative_speed_knots` means the current aircraft is faster than the aircraft ahead and the gap is closing.
- `spacing.shared_remaining_link_count` is only meaningful for route conflict context.
- In corridor mode, `shared_remaining_link_count` can stay `0` even when overtake is valid, so do not use it as a straight-corridor overtake gate.
