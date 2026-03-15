# External Logic Prompt Template

이 문서는 ChatGPT, Claude, Gemini 같은 LLM에 그대로 복붙해서 외부 로직 코드를 생성할 때 쓰는 템플릿입니다.

아래 프롬프트를 그대로 복사한 뒤, `[여기에 ...]` 부분만 바꿔 사용하면 됩니다.

---

## Prompt

당신은 UAM 시뮬레이터의 외부 제어 로직 작성자다.  
반드시 이 계약에 맞는 Python 코드만 출력해라.  
설명, 해설, 마크다운 코드펜스, 문장형 답변은 절대 출력하지 말고, 최종 결과는 실행 가능한 Python 코드만 출력해라.

시뮬레이터 외부 로직 계약:

1. 반드시 `control_step(state)` 함수를 정의해야 한다.
2. 선택적으로 아래 상수를 넣을 수 있다.
   - `LOGIC_NAME = "..."`
   - `LOGIC_DESCRIPTION = "..."`
   - `PARAM_OVERRIDES = {...}`
3. `control_step(state)`는 아래 둘 중 하나를 반환해야 한다.
   - `{"commands": [...], "params": {...}, "notes": [...]}`
   - 또는 `commands` 리스트만 직접 반환
4. 허용 명령은 아래뿐이다.
   - `set_speed`
   - `turn`
   - `overtake`
   - `spawn`
   - `delete`
   - `update_params`
5. 금지 사항:
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
   - `open`, `eval`, `exec`, `__import__` 같은 위험 함수
6. 사용 가능한 입력 데이터는 `state` 하나뿐이다.
7. 주요 참조 경로는 아래다.
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
8. `math`는 이미 사용 가능하므로 `import math`를 쓰지 마라.
9. 코드 길이는 40,000자 이하여야 한다.
10. 한 step에서 생성하는 명령 수는 256개 이하여야 한다.

기체 데이터 의미:

- `ac["data"]["spacing"]["forward_flow_gap_m"]`: 같은 흐름 기준 앞 기체와 거리
- `ac["data"]["spacing"]["nearest_conflict_distance_m"]`: 최근접 conflict 거리
- `ac["data"]["fifo"]["queue_rank"]`: FIFO 순번
- `ac["data"]["fifo"]["can_cross_node_now"]`: 지금 노드 통과 가능한지
- `ac["data"]["fifo"]["can_enter_next_link_now"]`: 다음 링크 진입 가능한지
- `ac["data"]["control"]["speed"]["can_issue_now"]`: 속도 지시 가능한지
- `ac["data"]["control"]["turn"]["can_issue_now"]`: 선회 지시 가능한지
- `ac["data"]["control"]["overtake"]["can_issue_now"]`: 추월 지시 가능한지
- `ac["data"]["control"]["overtake"]["candidate_target_aircraft_id"]`: 현재 추월 후보 ID
- `ac["data"]["operations"]["phase"]`: `pre_departure`, `enroute`, `holding`, `managed_action`, `completed`
- `ac["data"]["status"]["wait_reason"]`: 대기 사유
- `ac["data"]["wind"]["along_knots"]`, `cross_knots`: 종풍/횡풍

내가 원하는 로직 요구사항:

- 로직 이름: `[여기에 로직 이름]`
- 로직 설명: `[여기에 로직 설명]`
- 적용 모드: `[corridor / route / both 중 하나]`
- 핵심 목표: `[예: 최소 분리 500m 유지, 혼잡 시 감속, FIFO 우선권 강화 등]`
- 속도 정책: `[예: forward gap < 500m 이면 명령속도를 30% 낮춤]`
- 선회 정책: `[예: 특정 조건이면 turn 실행, 아니면 사용 안 함]`
- 추월 정책: `[예: 특정 조건에서만 overtake, target_id는 candidate_target_aircraft_id 사용]`
- 생성 정책: `[예: spawn 사용 안 함 / 특정 조건에만 spawn]`
- 삭제 정책: `[예: delete 사용 안 함 / 목적지 근접 시 delete]`
- 파라미터 오버라이드: `[예: {"sep_min_m": 500}]`
- 보수성: `[예: 명령 남발 금지, 이미 action 중이면 아무 명령도 보내지 않기]`

출력 규칙:

1. 최종 출력은 Python 코드만 출력해라.
2. `LOGIC_NAME`, `LOGIC_DESCRIPTION`, `PARAM_OVERRIDES`, `control_step(state)`를 포함해라.
3. 명령을 내리기 전에 반드시 `can_issue_now`, `action`, `wait_reason` 같은 안전 조건을 확인해라.
4. 추월을 사용할 경우 `candidate_target_aircraft_id`가 있을 때만 사용해라.
5. 코드가 비어 있거나 미완성이면 안 된다.
6. 함수 내부에서 이해 가능한 변수명과 간단한 주석만 써라.
7. `notes`도 함께 반환해라.
8. 가능하면 `params`는 꼭 필요한 경우에만 사용해라.

추가 요구:

- 외부 사용자가 그대로 붙여 넣어도 동작 가능해야 한다.
- 너무 공격적으로 명령하지 말고, 같은 기체에 매 step 과도한 중복 명령을 보내지 않도록 보수적으로 작성해라.
- `None` 방어 코드를 넣어라.
- return한 `notes`에는 왜 그런 명령을 냈는지 짧게 남겨라.
- 가능하면 최근접 전방 기체, FIFO 상태, wait 상태를 먼저 보고 명령하게 만들어라.

이제 위 조건에 맞는 최종 Python 코드만 출력해라.

---

## Example Filled Prompt

아래는 실제 사용 예입니다.

당신은 UAM 시뮬레이터의 외부 제어 로직 작성자다.  
반드시 이 계약에 맞는 Python 코드만 출력해라.  
설명, 해설, 마크다운 코드펜스, 문장형 답변은 절대 출력하지 말고, 최종 결과는 실행 가능한 Python 코드만 출력해라.

시뮬레이터 외부 로직 계약:

1. 반드시 `control_step(state)` 함수를 정의해야 한다.
2. 선택적으로 아래 상수를 넣을 수 있다.
   - `LOGIC_NAME = "..."`
   - `LOGIC_DESCRIPTION = "..."`
   - `PARAM_OVERRIDES = {...}`
3. `control_step(state)`는 아래 둘 중 하나를 반환해야 한다.
   - `{"commands": [...], "params": {...}, "notes": [...]}`
   - 또는 `commands` 리스트만 직접 반환
4. 허용 명령은 아래뿐이다.
   - `set_speed`
   - `turn`
   - `overtake`
   - `spawn`
   - `delete`
   - `update_params`
5. 금지 사항:
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
   - `open`, `eval`, `exec`, `__import__` 같은 위험 함수
6. 사용 가능한 입력 데이터는 `state` 하나뿐이다.
7. 주요 참조 경로는 아래다.
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
8. `math`는 이미 사용 가능하므로 `import math`를 쓰지 마라.
9. 코드 길이는 40,000자 이하여야 한다.
10. 한 step에서 생성하는 명령 수는 256개 이하여야 한다.

기체 데이터 의미:

- `ac["data"]["spacing"]["forward_flow_gap_m"]`: 같은 흐름 기준 앞 기체와 거리
- `ac["data"]["spacing"]["nearest_conflict_distance_m"]`: 최근접 conflict 거리
- `ac["data"]["fifo"]["queue_rank"]`: FIFO 순번
- `ac["data"]["fifo"]["can_cross_node_now"]`: 지금 노드 통과 가능한지
- `ac["data"]["fifo"]["can_enter_next_link_now"]`: 다음 링크 진입 가능한지
- `ac["data"]["control"]["speed"]["can_issue_now"]`: 속도 지시 가능한지
- `ac["data"]["control"]["turn"]["can_issue_now"]`: 선회 지시 가능한지
- `ac["data"]["control"]["overtake"]["can_issue_now"]`: 추월 지시 가능한지
- `ac["data"]["control"]["overtake"]["candidate_target_aircraft_id"]`: 현재 추월 후보 ID
- `ac["data"]["operations"]["phase"]`: `pre_departure`, `enroute`, `holding`, `managed_action`, `completed`
- `ac["data"]["status"]["wait_reason"]`: 대기 사유
- `ac["data"]["wind"]["along_knots"]`, `cross_knots`: 종풍/횡풍

내가 원하는 로직 요구사항:

- 로직 이름: `500m Separation Guard`
- 로직 설명: `앞 기체 분리가 500m 아래로 줄면 지시 속도를 30% 낮춘다`
- 적용 모드: `both`
- 핵심 목표: `최소 분리 500m 유지`
- 속도 정책: `forward gap < 500m 이면 명령속도를 30% 낮춤`
- 선회 정책: `사용 안 함`
- 추월 정책: `사용 안 함`
- 생성 정책: `사용 안 함`
- 삭제 정책: `사용 안 함`
- 파라미터 오버라이드: `{"sep_min_m": 500}`
- 보수성: `이미 action 중이거나 wait_reason이 있으면 추가 명령을 보내지 않음`

출력 규칙:

1. 최종 출력은 Python 코드만 출력해라.
2. `LOGIC_NAME`, `LOGIC_DESCRIPTION`, `PARAM_OVERRIDES`, `control_step(state)`를 포함해라.
3. 명령을 내리기 전에 반드시 `can_issue_now`, `action`, `wait_reason` 같은 안전 조건을 확인해라.
4. 추월을 사용할 경우 `candidate_target_aircraft_id`가 있을 때만 사용해라.
5. 코드가 비어 있거나 미완성이면 안 된다.
6. 함수 내부에서 이해 가능한 변수명과 간단한 주석만 써라.
7. `notes`도 함께 반환해라.
8. 가능하면 `params`는 꼭 필요한 경우에만 사용해라.

추가 요구:

- 외부 사용자가 그대로 붙여 넣어도 동작 가능해야 한다.
- 너무 공격적으로 명령하지 말고, 같은 기체에 매 step 과도한 중복 명령을 보내지 않도록 보수적으로 작성해라.
- `None` 방어 코드를 넣어라.
- return한 `notes`에는 왜 그런 명령을 냈는지 짧게 남겨라.
- 가능하면 최근접 전방 기체, FIFO 상태, wait 상태를 먼저 보고 명령하게 만들어라.

이제 위 조건에 맞는 최종 Python 코드만 출력해라.

## Related Docs

- [EXTERNAL_API_GUIDE.md](C:/Users/AISIMULATOR2/Desktop/Code/uam_congestion/EXTERNAL_API_GUIDE.md)
- [AIRCRAFT_DATA_SCHEMA.md](C:/Users/AISIMULATOR2/Desktop/Code/uam_congestion/AIRCRAFT_DATA_SCHEMA.md)
- [EXTERNAL_LOGIC_STUDIO_GUIDE.md](C:/Users/AISIMULATOR2/Desktop/Code/uam_congestion/EXTERNAL_LOGIC_STUDIO_GUIDE.md)
- [EXTERNAL_LOGIC_SAMPLE_ADAPTIVE_GUARD.py](C:/Users/AISIMULATOR2/Desktop/Code/uam_congestion/EXTERNAL_LOGIC_SAMPLE_ADAPTIVE_GUARD.py)

## Internal Design Rules For Generated Logic

Use [EXTERNAL_LOGIC_SAMPLE_ADAPTIVE_GUARD.py](C:/Users/AISIMULATOR2/Desktop/Code/uam_congestion/EXTERNAL_LOGIC_SAMPLE_ADAPTIVE_GUARD.py) as the baseline style and structure unless the user explicitly asks for a very different policy.

Always preserve these simulator-specific rules inside generated code:

1. `spacing.forward_flow_relative_speed_knots` means `front - self`.
2. Negative `forward_flow_relative_speed_knots` means the current aircraft is faster than the aircraft ahead.
3. `control.overtake.can_issue_now` already reflects engine-side feasibility and should be treated as the primary overtake availability signal.
4. `control.overtake.candidate_target_aircraft_id` should be preferred as the default overtake target when present.
5. `spacing.shared_remaining_link_count` is mainly meaningful for route conflict context and must not be used as a mandatory corridor overtake gate.
6. Generated logic should be conservative, helper-based, and should avoid stacking multiple commands for the same aircraft in a single step unless explicitly required.
7. Generated logic should prefer this priority unless the user overrides it:
   - safety and spacing recovery
   - overtake when clearly beneficial and issuable
   - turn only as a defensive fallback when overtake is unavailable or inappropriate

If the user only asks for a new traffic-management policy, generate code by modifying the baseline sample around these fixed rules instead of redesigning the entire control contract.
