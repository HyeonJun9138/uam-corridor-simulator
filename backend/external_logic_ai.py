from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, Optional
from urllib import error as urlerror
from urllib import request as urlrequest


ROOT_DIR = Path(__file__).resolve().parent.parent
PROMPT_PATH = ROOT_DIR / "EXTERNAL_LOGIC_ANALYSIS_PROMPT.md"
API_KEY_PATHS = (
    ROOT_DIR / "api_key.txt",
    ROOT_DIR / "api_key",
)
OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
OPENAI_MODEL = "gpt-5-mini"
OPENAI_MAX_OUTPUT_TOKENS = 2400
OPENAI_RETRY_MAX_OUTPUT_TOKENS = 4200

REVIEW_JSON_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "logic_effect_txt": {"type": "string"},
        "detected_params_txt": {"type": "string"},
        "operator_txt": {"type": "string"},
    },
    "required": [
        "logic_effect_txt",
        "detected_params_txt",
        "operator_txt",
    ],
}

PARAM_HELP = {
    "sep_min_m": "최소 분리 기준을 바꿉니다. 분리, 합류, 추월 안전 판정에 직접 영향을 줍니다.",
    "spawn_spacing_m": "자동 생성 간격을 바꿉니다. 엔진은 이 값을 sep_min_m보다 작게 두지 않습니다.",
    "v_free_knots": "자유 주행 목표 속도를 바꿉니다.",
    "v_init_knots": "새 기체의 초기 지시 속도를 바꿉니다.",
    "v_min_knots": "허용 최소 지시 속도를 바꿉니다.",
    "v_max_knots": "허용 최대 지시 속도를 바꿉니다.",
    "wind_enabled": "바람 효과를 켜거나 끕니다.",
    "wind_level": "바람 강도 프리셋을 바꿉니다.",
    "realtime_factor": "재생 배속을 바꿉니다.",
    "fifo_queue_sep_scale": "FIFO 대기열 간격에 곱해지는 분리 배수를 바꿉니다.",
    "fifo_node_clearance_min_m": "노드 통과 전후 최소 clearance 거리를 바꿉니다.",
    "fifo_node_clearance_scale": "sep_min_m 대비 추가 node clearance 배수를 바꿉니다.",
    "fifo_hold_buffer_min_m": "FIFO hold에서 downstream buffer 최소값을 바꿉니다.",
    "fifo_hold_buffer_scale": "sep_min_m 대비 추가 hold buffer 배수를 바꿉니다.",
    "fifo_approach_sep_scale": "FIFO 접근 예측에서 쓰는 분리 배수를 바꿉니다.",
    "fifo_approach_time_s": "FIFO 접근 예측 시간을 초 단위로 바꿉니다.",
    "rho_ref": "정규화된 밀도 표현 기준값을 바꿉니다.",
    "cong_ref": "정규화된 기체 혼잡 표현 기준값을 바꿉니다.",
}


def _read_api_key() -> Optional[str]:
    for path in API_KEY_PATHS:
        if not path.exists():
            continue
        key = path.read_text(encoding="utf-8").strip()
        if key:
            return key
    return None


def _safe_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def explain_detected_params(params: dict) -> str:
    if not isinstance(params, dict) or not params:
        return (
            "감지한 파라미터는 코드 안에 적힌 literal override 값입니다. 보통 `PARAM_OVERRIDES`에서 읽어옵니다.\n\n"
            "현재 코드에서는 자동으로 읽어낸 override 값이 없어서, 지금 상태에서 `적용`을 눌러도 시뮬레이터 파라미터는 바뀌지 않습니다."
        )

    lines = [
        "감지한 파라미터는 코드 안에 적힌 literal override 값입니다. 보통 `PARAM_OVERRIDES`에서 읽어옵니다.",
        "여기 있는 값은 `적용` 버튼을 누르거나 활성화 시 자동 적용을 켜두면 시뮬레이터 파라미터 세트로 들어갑니다.",
        "",
    ]
    for key in sorted(params.keys()):
        value = params[key]
        detail = PARAM_HELP.get(key, f"시뮬레이터 파라미터 `{key}`를 이 값으로 덮어씁니다.")
        lines.append(f"- {key} = {value}: {detail}")
    return "\n".join(lines)


def _build_static_logic_effect(analysis: dict) -> str:
    if not isinstance(analysis, dict) or not analysis.get("ok"):
        errors = analysis.get("errors", []) if isinstance(analysis, dict) else []
        error_text = "; ".join(str(item) for item in errors[:3]) or "정적 분석에서 막히는 문제가 발견되었습니다."
        return (
            "이 코드는 아직 실행 가능한 상태가 아닙니다.\n"
            f"분석기에서 활성화를 막는 문제를 찾았습니다: {error_text}\n"
            "이 문제가 해결되기 전에는 시뮬레이터가 이 외부 로직을 활성화하지 않습니다."
        )

    logic_name = analysis.get("logic_name") or "이름 없는 외부 로직"
    logic_description = analysis.get("logic_description") or "코드에 설명 문자열이 따로 적혀 있지 않습니다."
    summary_lines = _safe_list(analysis.get("summary"))

    lines = [
        f"이 코드는 `{logic_name}` 로직을 정의합니다.",
        logic_description,
        "외부 로직이 활성화되면 매 simulation step마다 `control_step(state)`가 실행됩니다.",
    ]
    if summary_lines:
        lines.append("정적 분석 요약: " + "; ".join(str(item) for item in summary_lines[:4]))
    lines.append(
        "즉, 실제 물리 계산, 경로 추종, 안전성 판정은 엔진이 계속 맡고, "
        "이 코드는 어떤 조건에서 속도 변경, 추월, 선회, 생성, 삭제, 파라미터 변경 명령을 낼지만 결정합니다."
    )
    return "\n".join(lines)


def _build_static_operator_text(analysis: dict) -> str:
    if not isinstance(analysis, dict) or not analysis.get("ok"):
        return (
            "운용 관점에서는 아직 이 코드를 활성화할 수 없으므로, 현재는 시뮬레이터 기본 로직만 기체를 제어하게 됩니다."
        )

    detected_params = _safe_dict(analysis.get("detected_params"))
    lines = [
        "운용 관점에서는, 이 코드를 활성화하면 코드 내부 조건에 따라 기체별 외부 제어 명령이 만들어집니다.",
    ]
    if detected_params:
        lines.append(
            "이 코드는 파라미터 override도 같이 제안하고 있으므로, 첫 기체 명령이 나가기 전부터 시뮬레이터 동작 기준이 바뀔 수 있습니다."
        )
    else:
        lines.append(
            "이 코드는 시뮬레이터 파라미터 override를 선언하지 않았으므로, 예상되는 변화는 기체별 명령 중심입니다."
        )
    lines.append(
        "다만 모든 명령은 최종적으로 엔진의 feasibility check를 한 번 더 통과해야 합니다. "
        "외부 로직이 선회나 추월을 요청하더라도, 실제 거리나 경로 조건상 불가능하면 엔진이 그 명령을 거절할 수 있습니다."
    )
    return "\n".join(lines)


def _load_prompt_template() -> str:
    if PROMPT_PATH.exists():
        return PROMPT_PATH.read_text(encoding="utf-8")
    return ""


def _render_prompt(template: str, code: str, analysis: dict) -> str:
    replacements = {
        "{{STATIC_ANALYSIS_JSON}}": json.dumps(analysis, ensure_ascii=False, indent=2),
        "{{DETECTED_PARAMS_TEXT}}": explain_detected_params(_safe_dict(analysis.get("detected_params"))),
        "{{SOURCE_CODE}}": code,
    }
    prompt = template
    for key, value in replacements.items():
        prompt = prompt.replace(key, value)
    return prompt


def _extract_response_text(payload: dict) -> str:
    direct = payload.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct.strip()

    chunks = []
    for item in _safe_list(payload.get("output")):
        content_items = _safe_list(_safe_dict(item).get("content"))
        for content in content_items:
            content_dict = _safe_dict(content)
            text = content_dict.get("text")
            if isinstance(text, str) and text.strip():
                chunks.append(text.strip())
    return "\n".join(chunks).strip()


def _strip_code_fences(text: str) -> str:
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    while lines and lines[-1].startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def _parse_review_json(text: str) -> Optional[Dict[str, Any]]:
    cleaned = _strip_code_fences(text)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        cleaned = cleaned[start:end + 1]
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _call_openai_once(prompt: str, max_output_tokens: int) -> Dict[str, Any]:
    api_key = _read_api_key()
    if not api_key:
        return {"ok": False, "error": "API key file not found. Put the key in api_key.txt or api_key."}

    payload = {
        "model": OPENAI_MODEL,
        "input": prompt,
        "max_output_tokens": max_output_tokens,
        "reasoning": {
            "effort": "minimal",
        },
        "text": {
            "format": {
                "type": "json_schema",
                "name": "external_logic_review",
                "strict": True,
                "schema": REVIEW_JSON_SCHEMA,
            },
        },
    }
    req = urlrequest.Request(
        OPENAI_RESPONSES_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlrequest.urlopen(req, timeout=45) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urlerror.HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8")
        except Exception:
            detail = str(exc)
        return {"ok": False, "error": f"OpenAI HTTP {exc.code}: {detail}"}
    except Exception as exc:
        return {"ok": False, "error": f"OpenAI request failed: {exc}"}

    if body.get("status") == "incomplete":
        return {
            "ok": False,
            "error": f"OpenAI response incomplete: {body.get('incomplete_details')}",
            "retryable": _safe_dict(body.get("incomplete_details")).get("reason") == "max_output_tokens",
        }

    text = _extract_response_text(body)
    if not text:
        return {"ok": False, "error": "OpenAI response did not contain output text."}

    parsed = _parse_review_json(text)
    if parsed is None:
        return {
            "ok": False,
            "error": "OpenAI response was not valid JSON.",
        }

    return {"ok": True, "review": parsed, "model": OPENAI_MODEL}


def _call_openai(prompt: str) -> Dict[str, Any]:
    first = _call_openai_once(prompt, OPENAI_MAX_OUTPUT_TOKENS)
    if first.get("ok"):
        return first
    if not first.get("retryable"):
        return first
    second = _call_openai_once(prompt, OPENAI_RETRY_MAX_OUTPUT_TOKENS)
    if second.get("ok"):
        return second
    return second


def build_logic_review(source: str, analysis: dict, state: dict) -> Dict[str, Any]:
    _ = state
    static_review = {
        "source": "static",
        "model": None,
        "logic_effect_txt": _build_static_logic_effect(analysis),
        "detected_params_txt": explain_detected_params(_safe_dict(analysis.get("detected_params"))),
        "operator_txt": _build_static_operator_text(analysis),
        "error": None,
    }

    if not isinstance(analysis, dict) or not analysis.get("ok"):
        return static_review

    template = _load_prompt_template()
    if not template.strip():
        static_review["error"] = "Analysis prompt file was not found."
        return static_review

    prompt = _render_prompt(template, source, analysis)
    llm_result = _call_openai(prompt)
    if not llm_result.get("ok"):
        static_review["error"] = llm_result.get("error")
        return static_review

    review = copy.deepcopy(static_review)
    review["source"] = "openai"
    review["model"] = llm_result.get("model")
    review["error"] = None

    parsed = _safe_dict(llm_result.get("review"))
    for key in ("logic_effect_txt", "detected_params_txt", "operator_txt"):
        value = parsed.get(key)
        if isinstance(value, str) and value.strip():
            review[key] = value.strip()

    return review
