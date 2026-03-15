# External Logic Studio Guide

이 문서는 브라우저의 `외부 로직` 창을 사용해 다른 사람이 직접 작성한 Python 제어 코드를 시뮬레이터에 연결하는 방법을 설명합니다.

전용 창 진입:

- 메인 상단 `외부 로직` 버튼 클릭
- 또는 `/logic.html` 직접 열기

## 1. 목적

외부 로직 스튜디오는 아래 용도를 위한 창입니다.

- 연구자/운영자가 직접 제어 로직을 작성
- 시뮬레이터 상태를 기준으로 자동 명령 생성
- 감지한 파라미터를 자동 적용
- 코드 분석 후 안전 제약을 통과한 경우에만 활성화

즉, 이 기능은 "사용자가 직접 만든 교통관리 로직으로 시뮬레이션을 구동"하기 위한 장치입니다.

## 2. 화면 구성

### 좌측

- 코드 입력 영역
- 파일 불러오기
- 샘플 코드 로드
- 코드 분석
- 로직 활성화
- 로직 중지
- 실행 로그

### 우측

- 현재 활성 로직 상태
- 최근 실행 결과
- 분석 결과
- 감지한 파라미터
- 현재 시뮬레이션 요약
- 프롬프트 템플릿 원문과 복사 버튼

## 3. 기본 사용 절차

1. 좌측에 Python 코드를 붙여 넣습니다.
2. `코드 분석`을 눌러 문법/구조/금지 구문 여부를 확인합니다.
3. 문제가 없으면 `로직 활성화`를 누릅니다.
4. 필요하면 `감지한 파라미터 적용` 또는 자동 적용 옵션을 사용합니다.
5. 시뮬레이션을 실행하면 해당 로직이 매 step마다 호출됩니다.

## 3.1 우측 카드에서 바로 확인할 수 있는 것

### 활성 상태 카드

- 로직 이름
- 분석 상태
- 제어 함수명
- 코드 줄 수 / 문자 수
- 감지 파라미터 수
- 경고 / 오류 수
- 최근 실행 시각
- 최근 명령 수
- 최근 실행 시간
- 로직 설명

### 최근 실행 결과 카드

- action별 명령 분포
- 최근 note 수
- 최근 파라미터 반영 수
- 최근 notes 원문
- 최근 파라미터 반영값
- 최근 오류 traceback 또는 메시지

### 프롬프트 템플릿 카드

- [EXTERNAL_LOGIC_PROMPT_TEMPLATE.md](C:/Users/AISIMULATOR2/Desktop/Code/uam_congestion/EXTERNAL_LOGIC_PROMPT_TEMPLATE.md) 원문을 그대로 표시
- `복사하기` 버튼으로 클립보드 복사

## 4. 코드 계약

외부 로직 코드는 반드시 아래 함수 하나를 포함해야 합니다.

```python
def control_step(state):
    return {"commands": [], "params": {}}
```

### 선택 상수

```python
LOGIC_NAME = "My Logic"
LOGIC_DESCRIPTION = "설명"
PARAM_OVERRIDES = {
    "sep_min_m": 500
}
```

### `control_step(state)` 입력

- 인자로 현재 전체 시뮬레이션 상태를 받습니다.
- 구조는 [EXTERNAL_API_GUIDE.md](C:/Users/AISIMULATOR2/Desktop/Code/uam_congestion/EXTERNAL_API_GUIDE.md)와 [AIRCRAFT_DATA_SCHEMA.md](C:/Users/AISIMULATOR2/Desktop/Code/uam_congestion/AIRCRAFT_DATA_SCHEMA.md)를 기준으로 사용합니다.
- `math`는 이미 사용 가능하므로 별도 `import math` 없이 쓰면 됩니다.

### 반환 형식

반환은 아래 둘 중 하나입니다.

#### 형식 A

```python
return {
    "commands": [
        {"action": "set_speed", "id": 1, "speed": 90}
    ],
    "params": {
        "sep_min_m": 500
    },
    "notes": [
        "설명 메시지"
    ]
}
```

#### 형식 B

```python
return [
    {"action": "set_speed", "id": 1, "speed": 90}
]
```

추가 제약:

- 코드 길이 최대 40,000자
- step당 명령 최대 256개
- `notes`는 선택이지만 강하게 권장

## 5. 허용 명령

### set_speed

```python
{"action": "set_speed", "id": 12, "speed": 90}
```

### turn

```python
{"action": "turn", "id": 12, "diameter_m": 800}
```

### overtake

```python
{
    "action": "overtake",
    "id": 12,
    "lateral_offset_m": 100,
    "speed_boost_knots": 20,
    "target_id": 9,
}
```

### spawn

직선 항로:

```python
{"action": "spawn"}
```

Custom 항로:

```python
{"action": "spawn", "start_node_id": "R1C0"}
```

### delete

```python
{"action": "delete", "id": 12}
```

### update_params

```python
{
    "action": "update_params",
    "params": {
        "sep_min_m": 500,
        "fifo_approach_time_s": 5.0,
    }
}
```

## 6. 안전 제약

코드는 분석 단계에서 아래 제약을 통과해야 합니다.

### 금지 구문

- `import`
- `while`
- `try`
- `with`
- `async`
- `lambda`
- `class`
- `raise`
- dunder 이름 접근

### 금지 호출

- `open`
- `eval`
- `exec`
- `__import__`
- `globals`
- `locals`
- `setattr`
- `getattr`
- `vars`

### 허용 범위

- 제한된 기본 빌트인
- `math` 모듈
- 순수 Python 계산

즉, 외부 네트워크 호출이나 파일 IO는 허용되지 않습니다.

## 7. 작성 권장 패턴

외부 로직은 아래 흐름으로 작성하는 편이 안전합니다.

1. `state["aircraft"]`를 순회
2. 각 기체의 `data.status`, `data.operations`로 현재 상태 확인
3. `data.spacing`으로 전방/후방 간격 및 conflict 확인
4. `data.fifo`로 합류/교차 노드 통과 가능 여부 확인
5. `data.control`로 지금 명령 가능한지 확인
6. 조건 만족 시에만 명령 생성

예:

```python
def control_step(state):
    commands = []
    for ac in state.get("aircraft", []):
        data = ac.get("data", {})
        control = data.get("control", {})
        spacing = data.get("spacing", {})

        if not control.get("speed", {}).get("can_issue_now", False):
            continue

        forward_gap = spacing.get("forward_flow_gap_m")
        if forward_gap is not None and forward_gap < 500:
            commands.append({
                "action": "set_speed",
                "id": ac["id"],
                "speed": 80
            })

    return {"commands": commands}
```

## 8. 자주 쓰는 state 경로

### 기체 상태

- `ac["data"]["status"]`
- `ac["data"]["operations"]`

### 속도와 성능

- `ac["data"]["speed"]`
- `ac["data"]["wind"]`
- `ac["data"]["flow"]`

### 분리와 충돌 위험

- `ac["data"]["spacing"]["forward_flow_gap_m"]`
- `ac["data"]["spacing"]["rear_flow_gap_m"]`
- `ac["data"]["spacing"]["nearest_conflict_distance_m"]`

### Custom 항로 합류/교차

- `ac["data"]["fifo"]["queue_rank"]`
- `ac["data"]["fifo"]["can_cross_node_now"]`
- `ac["data"]["fifo"]["can_enter_next_link_now"]`

### 제어 가능 여부

- `ac["data"]["control"]["speed"]["can_issue_now"]`
- `ac["data"]["control"]["turn"]["can_issue_now"]`
- `ac["data"]["control"]["overtake"]["can_issue_now"]`

## 9. 감지한 파라미터

코드 상단에 `PARAM_OVERRIDES`를 두면 스튜디오가 이를 자동 감지합니다.

```python
PARAM_OVERRIDES = {
    "sep_min_m": 500,
    "fifo_approach_time_s": 6.0,
}
```

가능한 사용 예:

- 최소 분리를 실험별로 고정
- FIFO 접근 시간 조정
- 혼잡 기준치 변경
- 최대/최저 속도 정책 실험

주의:

- 감지된 값은 자동 적용 옵션이 켜져 있으면 활성화 시점에 반영됩니다.
- 내부 정규화가 걸릴 수 있습니다.
- 실제 적용 결과는 우측 로그와 응답의 `param_report`를 기준으로 확인하면 됩니다.

## 10. 디버깅 팁

- 활성화가 안 되면 먼저 `코드 분석`에서 `errors`를 확인합니다.
- 활성화 후 바로 비활성화되면 런타임 오류일 가능성이 큽니다.
- 로그에 `로직 오류`가 뜨면 해당 예외를 수정합니다.
- 우측 `최근 실행 결과` 카드에서 `명령 분포`, `최근 노트`, `최근 오류`를 같이 확인합니다.
- 명령이 먹지 않으면 `can_issue_now`, `action`, `wait_reason`을 먼저 확인합니다.
- 추월 명령은 후보가 없거나 공유 경로가 부족하면 엔진이 거부할 수 있습니다.

## 11. 예시 시나리오

### 최소 분리 500m 유지형 감속 로직

```python
LOGIC_NAME = "500m Separation Guard"
LOGIC_DESCRIPTION = "앞 기체 분리가 500m 아래로 줄면 지시 속도를 30% 낮춘다."

PARAM_OVERRIDES = {
    "sep_min_m": 500,
}

def control_step(state):
    commands = []

    for ac in state.get("aircraft", []):
        data = ac.get("data", {})
        spacing = data.get("spacing", {})
        speed_ctrl = data.get("control", {}).get("speed", {})

        if not speed_ctrl.get("can_issue_now", False):
            continue

        forward_gap = spacing.get("forward_flow_gap_m")
        if forward_gap is None or forward_gap >= 500:
            continue

        current_cmd = speed_ctrl.get("command_knots", 100)
        min_speed = speed_ctrl.get("allowed_min_knots", 60)
        reduced = max(min_speed, current_cmd * 0.7)

        commands.append({
            "action": "set_speed",
            "id": ac["id"],
            "speed": reduced,
        })

    return {"commands": commands}
```

## 12. 관련 문서

- [EXTERNAL_API_GUIDE.md](C:/Users/AISIMULATOR2/Desktop/Code/uam_congestion/EXTERNAL_API_GUIDE.md)
- [AIRCRAFT_DATA_SCHEMA.md](C:/Users/AISIMULATOR2/Desktop/Code/uam_congestion/AIRCRAFT_DATA_SCHEMA.md)
- [EXTERNAL_LOGIC_PROMPT_TEMPLATE.md](C:/Users/AISIMULATOR2/Desktop/Code/uam_congestion/EXTERNAL_LOGIC_PROMPT_TEMPLATE.md)
- [EXTERNAL_LOGIC_SAMPLE_ADAPTIVE_GUARD.py](C:/Users/AISIMULATOR2/Desktop/Code/uam_congestion/EXTERNAL_LOGIC_SAMPLE_ADAPTIVE_GUARD.py)

## 13. Common External Logic Mistakes

- Do not interpret `spacing.forward_flow_relative_speed_knots` as `self - front`. The field is `front - self`.
- Do not block corridor overtakes with `spacing.shared_remaining_link_count`. That field is mainly useful in route conflict context.
- If `control.overtake.can_issue_now` is already `true`, avoid rebuilding all engine feasibility checks in external code unless you need a stricter policy.
