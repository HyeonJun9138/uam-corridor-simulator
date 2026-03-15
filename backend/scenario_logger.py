from __future__ import annotations

import csv
import io
import json
import math
import shutil
import zipfile
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Deque, Dict, Iterable, List, Optional


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return int(default)
        return int(value)
    except (TypeError, ValueError):
        return int(default)


def _scenario_timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


@dataclass
class ScenarioRuntime:
    scenario_id: str
    directory: Path
    created_at_iso: str
    reason: str
    last_record_t_s: float = -math.inf
    params_map: Dict[str, Any] = field(default_factory=dict)
    summary_series: Deque[dict] = field(default_factory=deque)
    route_series: Dict[str, Deque[dict]] = field(default_factory=dict)
    link_series: Dict[str, Deque[dict]] = field(default_factory=dict)
    route_labels: Dict[str, str] = field(default_factory=dict)
    link_labels: Dict[str, str] = field(default_factory=dict)


class ScenarioLogManager:
    def __init__(
        self,
        root_dir: Path,
        *,
        max_scenarios: int = 10,
        sample_interval_s: float = 1.0,
        max_points: int = 1800,
    ):
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.max_scenarios = max(1, int(max_scenarios))
        self.sample_interval_s = max(0.2, float(sample_interval_s))
        self.max_points = max(120, int(max_points))
        self.current: Optional[ScenarioRuntime] = None

    def start_new_scenario(self, params_map: Dict[str, Any], *, reason: str = "reset") -> dict:
        scenario_id = self._next_scenario_id()
        created_at_iso = datetime.now().isoformat(timespec="seconds")
        directory = self.root_dir / scenario_id
        directory.mkdir(parents=True, exist_ok=True)

        runtime = ScenarioRuntime(
            scenario_id=scenario_id,
            directory=directory,
            created_at_iso=created_at_iso,
            reason=str(reason),
            params_map=dict(params_map or {}),
            summary_series=deque(maxlen=self.max_points),
        )
        self.current = runtime

        self._write_manifest(runtime)
        self._write_csv_header(runtime.directory / "summary_timeseries.csv", [
            "t_s", "mode", "aircraft_count", "delay_rate", "total_delay_min",
            "mean_speed_knots", "mean_congestion", "mean_delay_s", "mean_tti",
        ])
        self._write_csv_header(runtime.directory / "route_timeseries.csv", [
            "t_s", "route_key", "route_label", "origin_node_id", "destination_node_id",
            "aircraft_count", "mean_speed_knots", "mean_congestion", "mean_delay_s",
            "delayed_ratio", "mean_remaining_m",
        ])
        self._write_csv_header(runtime.directory / "link_timeseries.csv", [
            "t_s", "link_key", "link_label", "kind",
            "count", "mean_speed_knots", "score", "level",
        ])
        self._write_params_csv(runtime, runtime.params_map)
        self._prune_old_scenarios()
        return self.get_current_meta()

    def update_params(self, params_map: Dict[str, Any]) -> None:
        if self.current is None:
            return
        self.current.params_map = dict(params_map or {})
        self._write_params_csv(self.current, self.current.params_map)
        self._write_manifest(self.current)

    def record_state(self, state: Dict[str, Any]) -> None:
        runtime = self.current
        if runtime is None:
            return
        t_s = _safe_float(state.get("t"), 0.0)
        if t_s < runtime.last_record_t_s + self.sample_interval_s - 1e-9:
            return

        snapshot = self._build_snapshot(state)
        runtime.last_record_t_s = t_s
        runtime.summary_series.append(snapshot["summary"])
        self._append_csv_row(runtime.directory / "summary_timeseries.csv", snapshot["summary"])

        for row in snapshot["routes"]:
            key = row["route_key"]
            runtime.route_labels[key] = row["route_label"]
            series = runtime.route_series.get(key)
            if series is None:
                series = deque(maxlen=self.max_points)
                runtime.route_series[key] = series
            series.append(row)
            self._append_csv_row(runtime.directory / "route_timeseries.csv", row)

        for row in snapshot["links"]:
            key = row["link_key"]
            runtime.link_labels[key] = row["link_label"]
            series = runtime.link_series.get(key)
            if series is None:
                series = deque(maxlen=self.max_points)
                runtime.link_series[key] = series
            series.append(row)
            self._append_csv_row(runtime.directory / "link_timeseries.csv", row)

        self._write_manifest(runtime)

    def get_current_payload(self) -> dict:
        runtime = self.current
        if runtime is None:
            return {
                "scenario": None,
                "summary_series": [],
                "route_series": {},
                "route_labels": {},
                "link_series": {},
                "link_labels": {},
                "params": {},
                "scenarios": self.list_scenarios(),
            }

        return {
            "scenario": self.get_current_meta(),
            "summary_series": list(runtime.summary_series),
            "route_series": {
                key: list(series)
                for key, series in sorted(runtime.route_series.items())
            },
            "route_labels": dict(sorted(runtime.route_labels.items())),
            "link_series": {
                key: list(series)
                for key, series in sorted(runtime.link_series.items())
            },
            "link_labels": dict(sorted(runtime.link_labels.items())),
            "params": runtime.params_map,
            "scenarios": self.list_scenarios(),
        }

    def get_current_meta(self) -> Optional[dict]:
        runtime = self.current
        if runtime is None:
            return None
        files = self._scenario_files(runtime.directory)
        return {
            "scenario_id": runtime.scenario_id,
            "created_at": runtime.created_at_iso,
            "reason": runtime.reason,
            "files": files,
        }

    def list_scenarios(self) -> List[dict]:
        scenarios: List[dict] = []
        for directory in sorted(self.root_dir.glob("scenario_*"), reverse=True):
            manifest_path = directory / "manifest.json"
            if not manifest_path.exists():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            scenarios.append({
                "scenario_id": str(manifest.get("scenario_id") or directory.name),
                "created_at": manifest.get("created_at"),
                "reason": manifest.get("reason", "reset"),
                "files": self._scenario_files(directory),
            })
        return scenarios[: self.max_scenarios]

    def build_scenario_zip(self, scenario_id: str) -> io.BytesIO:
        directory = self._scenario_dir(scenario_id)
        if directory is None:
            raise FileNotFoundError(f"scenario not found: {scenario_id}")
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(directory.glob("*")):
                if path.is_file():
                    archive.writestr(path.name, path.read_bytes())
        buffer.seek(0)
        return buffer

    def resolve_scenario_file(self, scenario_id: str, filename: str) -> Optional[Path]:
        directory = self._scenario_dir(scenario_id)
        if directory is None:
            return None
        path = (directory / filename).resolve()
        try:
            path.relative_to(directory.resolve())
        except ValueError:
            return None
        return path if path.exists() and path.is_file() else None

    def _scenario_dir(self, scenario_id: str) -> Optional[Path]:
        directory = self.root_dir / scenario_id
        if not directory.exists() or not directory.is_dir():
            return None
        return directory

    def _scenario_files(self, directory: Path) -> List[str]:
        return sorted(path.name for path in directory.glob("*.csv"))

    def _next_scenario_id(self) -> str:
        max_idx = 0
        for directory in self.root_dir.glob("scenario_*"):
            parts = directory.name.split("_", 2)
            if len(parts) < 3:
                continue
            try:
                max_idx = max(max_idx, int(parts[1]))
            except ValueError:
                continue
        return f"scenario_{max_idx + 1:03d}_{_scenario_timestamp()}"

    def _prune_old_scenarios(self) -> None:
        directories = sorted(self.root_dir.glob("scenario_*"))
        while len(directories) > self.max_scenarios:
            victim = directories.pop(0)
            shutil.rmtree(victim, ignore_errors=True)

    def _write_manifest(self, runtime: ScenarioRuntime) -> None:
        manifest = {
            "scenario_id": runtime.scenario_id,
            "created_at": runtime.created_at_iso,
            "reason": runtime.reason,
            "last_record_t_s": round(float(runtime.last_record_t_s), 3) if math.isfinite(runtime.last_record_t_s) else None,
            "params_file": "params.csv",
            "summary_file": "summary_timeseries.csv",
            "route_file": "route_timeseries.csv",
            "link_file": "link_timeseries.csv",
        }
        (runtime.directory / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _write_params_csv(self, runtime: ScenarioRuntime, params_map: Dict[str, Any]) -> None:
        path = runtime.directory / "params.csv"
        with path.open("w", newline="", encoding="utf-8") as fp:
            writer = csv.DictWriter(fp, fieldnames=["key", "value"])
            writer.writeheader()
            for key, value in sorted((params_map or {}).items()):
                writer.writerow({
                    "key": key,
                    "value": json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value,
                })

    def _write_csv_header(self, path: Path, fieldnames: Iterable[str]) -> None:
        with path.open("w", newline="", encoding="utf-8") as fp:
            writer = csv.DictWriter(fp, fieldnames=list(fieldnames))
            writer.writeheader()

    def _append_csv_row(self, path: Path, row: Dict[str, Any]) -> None:
        with path.open("a", newline="", encoding="utf-8") as fp:
            writer = csv.DictWriter(fp, fieldnames=list(row.keys()))
            writer.writerow(row)

    def _build_snapshot(self, state: Dict[str, Any]) -> Dict[str, Any]:
        t_s = round(_safe_float(state.get("t"), 0.0), 3)
        mode = str(state.get("mode") or "corridor")
        aircraft = state.get("aircraft") or []
        summary = state.get("summary") or {}
        route_network = state.get("route_network") or {}
        node_map = {
            str(node.get("id")): node
            for node in route_network.get("nodes", [])
            if isinstance(node, dict) and node.get("id") is not None
        }
        link_map = {
            str(link.get("id")): link
            for link in route_network.get("links", [])
            if isinstance(link, dict) and link.get("id") is not None
        }

        speeds = [_safe_float(ac.get("v_act_knots"), math.nan) for ac in aircraft]
        congestions = [_safe_float(ac.get("c"), math.nan) for ac in aircraft]
        delays = [_safe_float(ac.get("D"), math.nan) for ac in aircraft]
        ttis = [_safe_float(ac.get("tti"), math.nan) for ac in aircraft]

        summary_row = {
            "t_s": t_s,
            "mode": mode,
            "aircraft_count": _safe_int(summary.get("N"), len(aircraft)),
            "delay_rate": round(_safe_float(summary.get("DR"), 0.0), 6),
            "total_delay_min": round(_safe_float(summary.get("TD_min"), 0.0), 6),
            "mean_speed_knots": round(self._mean(speeds), 6),
            "mean_congestion": round(self._mean(congestions), 6),
            "mean_delay_s": round(self._mean(delays), 6),
            "mean_tti": round(self._mean(ttis), 6),
        }

        route_groups: Dict[str, Dict[str, Any]] = defaultdict(lambda: {
            "count": 0,
            "sum_speed": 0.0,
            "sum_congestion": 0.0,
            "sum_delay": 0.0,
            "sum_remaining": 0.0,
            "delayed_count": 0,
            "origin_node_id": None,
            "destination_node_id": None,
            "route_label": "",
        })
        for ac in aircraft:
            origin = ac.get("origin_node_id")
            destination = ac.get("destination_node_id")
            if mode == "route":
                route_key = f"{origin or '?'}->{destination or '?'}"
                route_label = self._route_label(origin, destination, node_map)
            else:
                route_key = "corridor:start->end"
                route_label = "Main Terminal A -> Main Terminal B"
            row = route_groups[route_key]
            row["count"] += 1
            row["sum_speed"] += _safe_float(ac.get("v_act_knots"), 0.0)
            row["sum_congestion"] += _safe_float(ac.get("c"), 0.0)
            row["sum_delay"] += _safe_float(ac.get("D"), 0.0)
            row["sum_remaining"] += _safe_float(ac.get("remaining_m"), 0.0)
            row["delayed_count"] += 1 if ac.get("delayed") else 0
            row["origin_node_id"] = origin
            row["destination_node_id"] = destination
            row["route_label"] = route_label

        route_rows: List[dict] = []
        for route_key, row in sorted(route_groups.items()):
            count = max(1, int(row["count"]))
            route_rows.append({
                "t_s": t_s,
                "route_key": route_key,
                "route_label": row["route_label"],
                "origin_node_id": row["origin_node_id"],
                "destination_node_id": row["destination_node_id"],
                "aircraft_count": int(row["count"]),
                "mean_speed_knots": round(row["sum_speed"] / count, 6),
                "mean_congestion": round(row["sum_congestion"] / count, 6),
                "mean_delay_s": round(row["sum_delay"] / count, 6),
                "delayed_ratio": round(row["delayed_count"] / count, 6),
                "mean_remaining_m": round(row["sum_remaining"] / count, 6),
            })

        link_rows: List[dict] = []
        for idx, seg in enumerate(state.get("segments") or []):
            if mode == "route":
                link_key = str(seg.get("id") or f"link_{idx:03d}")
                link_meta = link_map.get(link_key, {})
                link_label = str(link_meta.get("display_name") or link_meta.get("short_name") or f'{seg.get("start_id", "?")} -> {seg.get("end_id", "?")}')
                kind = "route_link"
            else:
                x_start = _safe_float(seg.get("x_start"), 0.0)
                x_end = _safe_float(seg.get("x_end"), 0.0)
                link_key = f"seg_{idx:03d}"
                link_label = str(seg.get("display_name") or f"Main Segment {idx + 1} ({x_start/1000:.1f}km - {x_end/1000:.1f}km)")
                kind = "corridor_segment"
            link_rows.append({
                "t_s": t_s,
                "link_key": link_key,
                "link_label": link_label,
                "kind": kind,
                "count": _safe_int(seg.get("count"), 0),
                "mean_speed_knots": round(_safe_float(seg.get("v_mean"), 0.0), 6),
                "score": round(_safe_float(seg.get("score"), 0.0), 6),
                "level": _safe_int(seg.get("level"), 0),
            })

        return {
            "summary": summary_row,
            "routes": route_rows,
            "links": link_rows,
        }

    def _route_label(self, origin: Optional[str], destination: Optional[str], node_map: Dict[str, dict]) -> str:
        if not origin and not destination:
            return "Custom 항로"
        origin_label = self._node_label(origin, node_map)
        destination_label = self._node_label(destination, node_map)
        if origin_label and destination_label:
            return f"{origin_label} -> {destination_label}"
        return f"{origin or '?'} -> {destination or '?'}"

    def _node_label(self, node_id: Optional[str], node_map: Dict[str, dict]) -> Optional[str]:
        if not node_id:
            return None
        node = node_map.get(str(node_id))
        if not node:
            return str(node_id)
        if node.get("display_name"):
            return str(node["display_name"])
        row = _safe_int(node.get("row"), 0) + 1
        role = str(node.get("role") or "node")
        if role == "start":
            return f"출발 R{row}"
        if role == "end":
            return f"도착 R{row}"
        return f"노드 R{row}"

    def _mean(self, values: Iterable[float]) -> float:
        valid = [float(v) for v in values if math.isfinite(float(v))]
        if not valid:
            return 0.0
        return sum(valid) / max(len(valid), 1)
