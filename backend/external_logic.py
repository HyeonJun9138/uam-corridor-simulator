from __future__ import annotations

import ast
import copy
import math
import time
import traceback
from typing import Any, Callable, Dict, List, Optional, Tuple


SAFE_BUILTINS = {
    "abs": abs,
    "all": all,
    "any": any,
    "bool": bool,
    "dict": dict,
    "enumerate": enumerate,
    "float": float,
    "int": int,
    "isinstance": isinstance,
    "len": len,
    "list": list,
    "max": max,
    "min": min,
    "range": range,
    "round": round,
    "set": set,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "zip": zip,
}

FORBIDDEN_CALL_NAMES = {
    "__import__",
    "compile",
    "delattr",
    "dir",
    "eval",
    "exec",
    "getattr",
    "globals",
    "help",
    "input",
    "locals",
    "memoryview",
    "open",
    "setattr",
    "vars",
}

DISALLOWED_NODE_TYPES = (
    ast.AsyncFunctionDef,
    ast.AsyncFor,
    ast.AsyncWith,
    ast.Await,
    ast.ClassDef,
    ast.Delete,
    ast.Global,
    ast.Import,
    ast.ImportFrom,
    ast.Lambda,
    ast.Nonlocal,
    ast.Raise,
    ast.Try,
    ast.While,
    ast.With,
    ast.Yield,
    ast.YieldFrom,
)

ALLOWED_COMMANDS = {
    "delete",
    "overtake",
    "set_speed",
    "spawn",
    "turn",
    "update_params",
}


class _SafetyVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self.errors: List[str] = []

    def visit(self, node: ast.AST):
        if isinstance(node, DISALLOWED_NODE_TYPES):
            self.errors.append(f"허용되지 않는 구문입니다: {type(node).__name__}")
            return
        super().visit(node)

    def visit_Name(self, node: ast.Name):
        if node.id.startswith("__"):
            self.errors.append(f"double-underscore 이름은 허용되지 않습니다: {node.id}")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        if node.attr.startswith("__"):
            self.errors.append(f"double-underscore 속성은 허용되지 않습니다: {node.attr}")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        fn = node.func
        if isinstance(fn, ast.Name) and fn.id in FORBIDDEN_CALL_NAMES:
            self.errors.append(f"허용되지 않는 호출입니다: {fn.id}()")
        self.generic_visit(node)


class ExternalLogicController:
    def __init__(self) -> None:
        self.active = False
        self.source = ""
        self.namespace: Dict[str, Any] = {}
        self.control_step: Optional[Callable[[dict], Any]] = None
        self.logic_min_interval_s = 0.0
        self.next_run_t_s = 0.0
        self.analysis: Dict[str, Any] = {}
        self.analysis_explanation: Dict[str, Any] = {}
        self.analysis_explanation_source = ""
        self.last_error: Optional[str] = None
        self.last_traceback: Optional[str] = None
        self.runtime_ema_ms: Optional[float] = None
        self.slow_run_count = 0
        self.performance_warning: Optional[str] = None
        self.last_result: Dict[str, Any] = {
            "command_count": 0,
            "last_run_s": None,
            "last_runtime_ms": None,
            "skipped": False,
            "params_applied": {},
            "commands_by_action": {},
            "commands_preview": [],
            "note_count": 0,
            "notes": [],
        }
        self.logic_name = "사용자 로직"
        self.logic_description = ""

    def cache_analysis_explanation(self, source: str, explanation: dict) -> None:
        self.analysis_explanation_source = str(source or "")
        self.analysis_explanation = copy.deepcopy(explanation) if isinstance(explanation, dict) else {}

    def _attach_cached_explanation(self, source: str, analysis: Dict[str, Any]) -> Dict[str, Any]:
        if str(source or "") == self.analysis_explanation_source and self.analysis_explanation:
            analysis["explanation"] = copy.deepcopy(self.analysis_explanation)
        return analysis

    def _empty_analysis(self, source: str) -> Dict[str, Any]:
        return {
            "ok": False,
            "source_length": len(source),
            "function_name": None,
            "functions": [],
            "logic_name": None,
            "logic_description": None,
            "logic_min_interval_s": 0.0,
            "detected_params": {},
            "errors": [],
            "warnings": [],
            "summary": [],
        }

    def analyze(self, source: str) -> Dict[str, Any]:
        analysis = self._empty_analysis(source)
        if not str(source).strip():
            analysis["errors"].append("코드가 비어 있습니다.")
            return analysis
        if len(source) > 40000:
            analysis["errors"].append("코드 길이가 너무 깁니다. 40,000자 이하로 줄여주세요.")
            return analysis

        try:
            tree = ast.parse(source, mode="exec")
        except SyntaxError as exc:
            analysis["errors"].append(f"문법 오류: {exc.msg} (line {exc.lineno})")
            return analysis

        visitor = _SafetyVisitor()
        visitor.visit(tree)
        analysis["errors"].extend(visitor.errors)

        functions = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]
        analysis["functions"] = functions
        if "control_step" in functions:
            analysis["function_name"] = "control_step"
        else:
            analysis["errors"].append("필수 함수 `control_step(state)`가 없습니다.")

        for node in tree.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name):
                continue
            try:
                literal = ast.literal_eval(node.value)
            except Exception:
                literal = None
            if target.id == "PARAM_OVERRIDES":
                if isinstance(literal, dict):
                    analysis["detected_params"] = literal
                else:
                    analysis["warnings"].append("`PARAM_OVERRIDES`는 리터럴 dict일 때만 자동 분석됩니다.")
            elif target.id == "LOGIC_NAME":
                if isinstance(literal, str):
                    analysis["logic_name"] = literal
            elif target.id == "LOGIC_DESCRIPTION":
                if isinstance(literal, str):
                    analysis["logic_description"] = literal
            elif target.id == "LOGIC_MIN_INTERVAL_S":
                if isinstance(literal, (int, float)):
                    analysis["logic_min_interval_s"] = max(0.0, float(literal))
                else:
                    analysis["warnings"].append("`LOGIC_MIN_INTERVAL_S`는 숫자여야 합니다.")

        if not analysis["errors"]:
            analysis["ok"] = True
            analysis["summary"].append("문법 검사 통과")
            analysis["summary"].append("`control_step(state)` 확인")
            if analysis["detected_params"]:
                analysis["summary"].append(f"탐지 파라미터 {len(analysis['detected_params'])}개")
            else:
                analysis["summary"].append("탐지 파라미터 없음")
        return analysis

    def _build_exec_env(self) -> Dict[str, Any]:
        return {
            "__builtins__": SAFE_BUILTINS,
            "math": math,
        }

    def _build_probe_state(self, probe_state: dict) -> dict:
        if isinstance(probe_state, dict):
            base = copy.deepcopy(probe_state)
        else:
            base = {}

        if not isinstance(base.get("aircraft"), list):
            base["aircraft"] = []
        if not isinstance(base.get("params"), dict):
            base["params"] = {}
        if not isinstance(base.get("summary"), dict):
            base["summary"] = {}
        if "mode" not in base:
            base["mode"] = "corridor"
        if "t" not in base:
            base["t"] = 0.0

        if base["aircraft"]:
            return base

        base["aircraft"] = [{
            "id": 1,
            "data": {
                "identity": {"simulation_mode": str(base["mode"])},
                "status": {"route_mode": base["mode"] == "route", "action": None, "wait_reason": None},
                "operations": {"phase": "enroute", "is_completed": False, "is_pre_departure": False},
                "spacing": {
                    "forward_flow_gap_m": 480.0,
                    "forward_flow_relative_speed_knots": -8.0,
                    "nearest_conflict_distance_m": 420.0,
                    "shared_remaining_link_count": 2 if base["mode"] == "route" else 0,
                },
                "control": {
                    "speed": {
                        "can_issue_now": True,
                        "command_knots": 100.0,
                        "actual_knots": 100.0,
                        "allowed_min_knots": 60.0,
                        "allowed_max_knots": 120.0,
                        "default_free_knots": 100.0,
                    },
                    "turn": {"supported": True, "can_issue_now": True},
                    "overtake": {
                        "supported": True,
                        "can_issue_now": True,
                        "candidate_target_aircraft_id": 2,
                    },
                },
                "flow": {
                    "congestion_c": 0.45,
                    "density_rho": 0.70,
                    "delayed_ahead_ratio_R": 0.35,
                },
                "fifo": {
                    "can_cross_node_now": True,
                    "can_enter_next_link_now": True,
                },
                "routing": {"occupancy_ratio": 0.5},
                "wind": {"cross_knots": 2.0, "along_knots": 0.0},
                "parameters": {"separation_policy": {"sep_min_m": 500.0}},
            },
        }]
        return base

    def _summarize_commands(self, commands: List[dict]) -> Tuple[Dict[str, int], List[dict]]:
        counts: Dict[str, int] = {}
        preview: List[dict] = []
        for command in commands:
            action = str(command.get("action", "")).strip()
            counts[action] = counts.get(action, 0) + 1
            if len(preview) < 8:
                preview.append(copy.deepcopy(command))
        return counts, preview

    def _validate_command(self, command: dict, index: int) -> dict:
        if not isinstance(command, dict):
            raise ValueError(f"commands[{index}]는 dict여야 합니다.")
        action = str(command.get("action", "")).strip()
        if action not in ALLOWED_COMMANDS:
            raise ValueError(f"commands[{index}]의 action `{action}`은 허용되지 않습니다.")

        normalized = dict(command)
        normalized["action"] = action

        if action == "set_speed":
            if "id" not in normalized or "speed" not in normalized:
                raise ValueError("set_speed는 `id`, `speed`가 필요합니다.")
            normalized["id"] = int(normalized["id"])
            normalized["speed"] = float(normalized["speed"])
        elif action == "turn":
            if "id" not in normalized:
                raise ValueError("turn은 `id`가 필요합니다.")
            normalized["id"] = int(normalized["id"])
            normalized["diameter_m"] = float(normalized.get("diameter_m", 800.0))
        elif action == "overtake":
            if "id" not in normalized:
                raise ValueError("overtake는 `id`가 필요합니다.")
            normalized["id"] = int(normalized["id"])
            normalized["lateral_offset_m"] = float(normalized.get("lateral_offset_m", 100.0))
            normalized["speed_boost_knots"] = float(normalized.get("speed_boost_knots", 20.0))
            if normalized.get("target_id") is not None:
                normalized["target_id"] = int(normalized["target_id"])
        elif action == "spawn":
            if normalized.get("start_node_id") is not None:
                normalized["start_node_id"] = str(normalized["start_node_id"])
        elif action == "delete":
            if "id" not in normalized:
                raise ValueError("delete는 `id`가 필요합니다.")
            normalized["id"] = int(normalized["id"])
        elif action == "update_params":
            params = normalized.get("params", {})
            if not isinstance(params, dict):
                raise ValueError("update_params는 dict `params`가 필요합니다.")
            normalized["params"] = dict(params)

        return normalized

    def _normalize_output(self, output: Any) -> Dict[str, Any]:
        if output is None:
            return {"commands": [], "params": {}, "notes": []}
        if isinstance(output, list):
            commands = output
            params = {}
            notes = []
        elif isinstance(output, dict):
            commands = output.get("commands", [])
            params = output.get("params", {})
            notes = output.get("notes", [])
        else:
            raise ValueError("`control_step`는 list 또는 dict를 반환해야 합니다.")

        if not isinstance(commands, list):
            raise ValueError("반환값의 `commands`는 list여야 합니다.")
        if len(commands) > 256:
            raise ValueError("한 step에서 256개를 넘는 명령은 허용되지 않습니다.")
        if not isinstance(params, dict):
            raise ValueError("반환값의 `params`는 dict여야 합니다.")
        if not isinstance(notes, list):
            raise ValueError("반환값의 `notes`는 list여야 합니다.")

        normalized_commands = [self._validate_command(command, idx) for idx, command in enumerate(commands)]
        return {"commands": normalized_commands, "params": dict(params), "notes": list(notes)}

    def activate(self, source: str, probe_state: dict) -> Dict[str, Any]:
        analysis = self.analyze(source)
        self._attach_cached_explanation(source, analysis)
        if not analysis["ok"]:
            self.analysis = analysis
            return {"ok": False, "analysis": analysis, "logic": self.get_status()}

        env = self._build_exec_env()
        try:
            exec(compile(source, "<external-logic>", "exec"), env, env)
            control_step = env.get("control_step")
            if not callable(control_step):
                raise ValueError("`control_step`가 callable이 아닙니다.")
            runtime_params = env.get("PARAM_OVERRIDES")
            if isinstance(runtime_params, dict):
                analysis["detected_params"] = dict(runtime_params)
            logic_name = env.get("LOGIC_NAME")
            logic_description = env.get("LOGIC_DESCRIPTION")
            logic_min_interval_s = env.get("LOGIC_MIN_INTERVAL_S")
            if isinstance(logic_name, str) and logic_name.strip():
                analysis["logic_name"] = logic_name.strip()
            if isinstance(logic_description, str) and logic_description.strip():
                analysis["logic_description"] = logic_description.strip()
            if isinstance(logic_min_interval_s, (int, float)):
                analysis["logic_min_interval_s"] = max(0.0, float(logic_min_interval_s))

            probe_output = control_step(self._build_probe_state(probe_state))
            self._normalize_output(probe_output)
        except Exception as exc:
            analysis["ok"] = False
            analysis["errors"].append(f"활성화 검증 실패: {exc}")
            self.analysis = analysis
            self.last_error = str(exc)
            self.last_traceback = traceback.format_exc(limit=8)
            return {"ok": False, "analysis": analysis, "logic": self.get_status()}

        self.active = True
        self.source = source
        self.namespace = env
        self.control_step = control_step
        self.analysis = analysis
        self.last_error = None
        self.last_traceback = None
        self.logic_name = analysis.get("logic_name") or "사용자 로직"
        self.logic_description = analysis.get("logic_description") or ""
        self.logic_min_interval_s = max(0.0, float(analysis.get("logic_min_interval_s", 0.0) or 0.0))
        self.next_run_t_s = 0.0
        self.runtime_ema_ms = None
        self.slow_run_count = 0
        self.performance_warning = None
        self.last_result = {
            "command_count": 0,
            "last_run_s": None,
            "last_runtime_ms": None,
            "skipped": False,
            "params_applied": {},
            "commands_by_action": {},
            "commands_preview": [],
            "note_count": 0,
            "notes": [],
        }
        return {"ok": True, "analysis": analysis, "logic": self.get_status()}

    def deactivate(self) -> Dict[str, Any]:
        self.active = False
        self.namespace = {}
        self.control_step = None
        self.logic_min_interval_s = 0.0
        self.next_run_t_s = 0.0
        return self.get_status()

    def should_skip_for_cadence(self, sim_t: float) -> bool:
        return self.logic_min_interval_s > 0.0 and float(sim_t) + 1e-9 < self.next_run_t_s

    def record_cadence_skip(self, sim_t: float) -> None:
        self.last_result = {
            "command_count": 0,
            "last_run_s": time.time(),
            "last_runtime_ms": 0.0,
            "skipped": True,
            "params_applied": {},
            "commands_by_action": {},
            "commands_preview": [],
            "note_count": 0,
            "notes": [f"cadence_skip at t={round(float(sim_t), 3)} until {round(self.next_run_t_s, 3)}"],
        }

    def run_step(self, state: dict) -> Dict[str, Any]:
        if not self.active or self.control_step is None:
            return {"ok": False, "commands": [], "params": {}, "notes": []}

        sim_t = 0.0
        if isinstance(state, dict):
            try:
                sim_t = float(state.get("t", 0.0))
            except (TypeError, ValueError):
                sim_t = 0.0

        if self.logic_min_interval_s > 0.0 and sim_t + 1e-9 < self.next_run_t_s:
            self.record_cadence_skip(sim_t)
            return {"ok": True, "commands": [], "params": {}, "notes": [], "skipped": True}

        started = time.perf_counter()
        try:
            output = self.control_step(state)
            result = self._normalize_output(output)
            runtime_ms = (time.perf_counter() - started) * 1000.0
            if self.logic_min_interval_s > 0.0:
                self.next_run_t_s = sim_t + self.logic_min_interval_s
            self.runtime_ema_ms = (
                runtime_ms if self.runtime_ema_ms is None else (0.8 * self.runtime_ema_ms + 0.2 * runtime_ms)
            )
            if runtime_ms >= 20.0:
                self.slow_run_count += 1
            else:
                self.slow_run_count = max(0, self.slow_run_count - 1)
            if self.runtime_ema_ms >= 20.0 or self.slow_run_count >= 5:
                self.performance_warning = (
                    f"external logic is slow ({round(self.runtime_ema_ms, 2)} ms avg). "
                    "Use simpler loops or set LOGIC_MIN_INTERVAL_S."
                )
            else:
                self.performance_warning = None
            commands_by_action, commands_preview = self._summarize_commands(result["commands"])
            self.last_result = {
                "command_count": len(result["commands"]),
                "last_run_s": time.time(),
                "last_runtime_ms": round(runtime_ms, 3),
                "skipped": False,
                "params_applied": dict(result["params"]),
                "commands_by_action": commands_by_action,
                "commands_preview": commands_preview,
                "note_count": len(result["notes"]),
                "notes": list(result["notes"]),
            }
            self.last_error = None
            self.last_traceback = None
            return {"ok": True, **result}
        except Exception as exc:
            self.active = False
            self.last_error = str(exc)
            self.last_traceback = traceback.format_exc(limit=8)
            return {"ok": False, "commands": [], "params": {}, "notes": [], "error": str(exc)}

    def get_status(self) -> Dict[str, Any]:
        analysis = copy.deepcopy(self.analysis)
        functions = analysis.get("functions", []) if isinstance(analysis, dict) else []
        detected_params = analysis.get("detected_params", {}) if isinstance(analysis, dict) else {}
        warnings = analysis.get("warnings", []) if isinstance(analysis, dict) else []
        errors = analysis.get("errors", []) if isinstance(analysis, dict) else []
        source_text = self.source or ""
        return {
            "active": bool(self.active),
            "logic_name": self.logic_name,
            "logic_description": self.logic_description,
            "logic_min_interval_s": round(float(self.logic_min_interval_s), 3),
            "source_length": len(source_text),
            "source_line_count": len(source_text.splitlines()) if source_text else 0,
            "analysis_ok": bool(analysis.get("ok")) if isinstance(analysis, dict) else False,
            "function_name": analysis.get("function_name") if isinstance(analysis, dict) else None,
            "function_count": len(functions),
            "detected_param_count": len(detected_params) if isinstance(detected_params, dict) else 0,
            "warning_count": len(warnings),
            "error_count": len(errors),
            "analysis": analysis,
            "last_error": self.last_error,
            "last_traceback": self.last_traceback,
            "runtime_ema_ms": round(float(self.runtime_ema_ms), 3) if self.runtime_ema_ms is not None else None,
            "slow_run_count": int(self.slow_run_count),
            "performance_warning": self.performance_warning,
            "last_result": copy.deepcopy(self.last_result),
        }
