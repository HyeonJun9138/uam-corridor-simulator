"""
UAM Corridor Simulation Engine
Ported from PyQt desktop app to a stateless computation module.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple

import numpy as np

try:
    from .route_network import (
        RouteGeometry,
        RouteLink,
        RouteNode,
        build_adjacency,
        build_links,
        build_route_geometry,
        build_route_grid,
        default_straight_link_pairs,
        enumerate_complete_paths,
        geometry_preview_dict,
        link_id,
        reachable_end_nodes,
        shortest_path,
        validate_link_pair,
    )
except ImportError:
    from route_network import (
        RouteGeometry,
        RouteLink,
        RouteNode,
        build_adjacency,
        build_links,
        build_route_geometry,
        build_route_grid,
        default_straight_link_pairs,
        enumerate_complete_paths,
        geometry_preview_dict,
        link_id,
        reachable_end_nodes,
        shortest_path,
        validate_link_pair,
    )

KNOT_TO_MPS = 0.514444
MPS_TO_KNOT = 1.0 / KNOT_TO_MPS
BATTERY_ENDURANCE_S = 30.0 * 60.0


def clip01(x: np.ndarray) -> np.ndarray:
    return np.clip(x, 0.0, 1.0)


def robust_norm(field: np.ndarray, p: float = 95.0, eps: float = 1e-9) -> np.ndarray:
    m = np.percentile(field, p)
    if m <= eps:
        m = np.max(field)
    if m <= eps:
        return np.zeros_like(field)
    return np.clip(field / m, 0.0, 1.0)


@dataclass
class SimParams:
    simulation_mode: str = "corridor"
    path_length_m: float = 20000.0
    lane_width_m: float = 200.0
    spawn_margin_m: float = 3000.0
    auto_spawn_enabled: bool = False
    spawn_spacing_m: float = 600.0
    route_grid_spacing_m: float = 5000.0
    route_row_count: int = 3
    route_row_gap_m: float = 1200.0
    route_samples_per_segment: int = 24
    segment_length_m: float = 10000.0
    seg_w_overflow: float = 0.3
    seg_w_tti: float = 0.7
    dt_s: float = 0.2
    realtime_factor: float = 1.0
    v_free_knots: float = 100.0
    v_init_knots: float = 100.0
    v_min_knots: float = 60.0
    v_max_knots: float = 120.0
    wind_enabled: bool = False
    wind_level: str = "normal"
    sep_min_m: float = 200.0
    fifo_queue_sep_scale: float = 1.0
    fifo_node_clearance_min_m: float = 60.0
    fifo_node_clearance_scale: float = 0.3
    fifo_hold_buffer_min_m: float = 12.0
    fifo_hold_buffer_scale: float = 0.1
    fifo_approach_sep_scale: float = 3.0
    fifo_approach_time_s: float = 4.0
    a_max_mps2: float = 1.5
    b_max_mps2: float = 2.0
    sigma_parallel_m: float = 200.0
    sigma_perp_m: float = 60.0
    lookahead_L_m: float = 2000.0
    lookahead_W_m: float = 100.0
    delay_window_T_s: float = 60.0
    delayed_thr_s: float = 10.0
    rho_ref: float = 3.0
    cong_ref: float = 3.0
    nx: int = 200
    ny: int = 30
    alpha_density: float = 0.6
    alpha_congestion: float = 0.6
    footprint_tau: float = 0.6


class Aircraft:
    def __init__(self, ac_id: int, x_m: float, y_m: float, v_cmd_knots: float,
                 v_act_knots: Optional[float] = None, sta_s: Optional[float] = None,
                 spawn_t_s: float = 0.0):
        self.id = ac_id
        self.x_m = float(x_m)
        self.y_m = float(y_m)
        self.v_cmd_knots = float(v_cmd_knots)
        init_knots = self.v_cmd_knots if v_act_knots is None else float(v_act_knots)
        self.v_act_mps = init_knots * KNOT_TO_MPS
        self.ground_vx_mps = self.v_act_mps
        self.ground_vy_mps = 0.0
        self.wind_x_mps = 0.0
        self.wind_y_mps = 0.0
        self.std_s = float(spawn_t_s)
        self.sta_s = float(sta_s) if sta_s is not None else 0.0
        self.spawn_t_s = float(spawn_t_s)
        self.has_departed: bool = self.x_m > 1e-9
        self.depart_t_s: Optional[float] = float(spawn_t_s) if self.has_departed else None
        self.heading_rad: float = 0.0
        self.action: Optional[str] = None
        self.action_phase: str = "idle"
        self.action_state: Dict[str, Any] = {}
        self.delay_incs: Deque[Tuple[float, float]] = deque()
        self.D_s: float = 0.0
        self.origin_node_id: Optional[str] = None
        self.destination_node_id: Optional[str] = None
        self.route_node_ids: List[str] = []
        self.route_link_ids: List[str] = []
        self.route_total_m: float = 0.0
        self.route_progress_m: float = 0.0
        self.route_geometry: Optional[RouteGeometry] = None
        self.active_link_id: Optional[str] = None
        self.wait_reason: Optional[str] = None
        self.route_mode: bool = False
        self.data: Dict[str, Any] = {"schema_version": 3}

    def set_command_speed(self, v_knots: float):
        self.v_cmd_knots = float(max(0.0, v_knots))

    def update_delay_window(self, t_s: float, l: float, dt_s: float, T_s: float):
        incr = float(l) * float(dt_s)
        self.delay_incs.append((t_s, incr))
        self.D_s += incr
        while self.delay_incs and (t_s - self.delay_incs[0][0]) > T_s:
            _, old = self.delay_incs.popleft()
            self.D_s -= old
        if self.D_s < 0:
            self.D_s = 0.0

    def to_dict(self):
        return {
            "id": self.id,
            "x": self.x_m,
            "y": self.y_m,
            "v_cmd_knots": self.v_cmd_knots,
            "v_act_knots": self.v_act_mps * MPS_TO_KNOT,
            "heading_rad": self.heading_rad,
            "data": self.data,
        }


class SimulationEngine:
    def __init__(self, params: SimParams):
        self.p = params
        self.t_s: float = 0.0
        self._next_id: int = 1
        self.aircraft: List[Aircraft] = []
        self.route_nodes: Dict[str, RouteNode] = {}
        self.route_links: Dict[str, RouteLink] = {}
        self.route_adjacency: Dict[str, List[str]] = {}
        self.route_preview_paths: List[dict] = []
        self.node_release_t_s: Dict[str, float] = {}
        self.node_fifo_requests: Dict[str, Dict[int, float]] = {}
        self.normalize_model_params()
        self._reset_route_network(use_default_links=True)

    def _clamp_command_knots(self, v_knots: float) -> float:
        return float(min(max(v_knots, self.p.v_min_knots), self.p.v_max_knots))

    def normalize_model_params(self):
        self.p.simulation_mode = str(getattr(self.p, "simulation_mode", "corridor")).lower()
        if self.p.simulation_mode not in {"corridor", "route"}:
            self.p.simulation_mode = "corridor"
        self.p.v_min_knots = max(0.0, float(self.p.v_min_knots))
        self.p.v_max_knots = max(self.p.v_min_knots, float(self.p.v_max_knots))
        self.p.v_free_knots = self._clamp_command_knots(float(self.p.v_free_knots))
        self.p.v_init_knots = self._clamp_command_knots(float(self.p.v_init_knots))
        self.p.sep_min_m = max(1.0, float(self.p.sep_min_m))
        self.p.fifo_queue_sep_scale = max(0.0, float(getattr(self.p, "fifo_queue_sep_scale", 1.0)))
        self.p.fifo_node_clearance_min_m = max(0.0, float(getattr(self.p, "fifo_node_clearance_min_m", 60.0)))
        self.p.fifo_node_clearance_scale = max(0.0, float(getattr(self.p, "fifo_node_clearance_scale", 0.3)))
        self.p.fifo_hold_buffer_min_m = max(0.0, float(getattr(self.p, "fifo_hold_buffer_min_m", 12.0)))
        self.p.fifo_hold_buffer_scale = max(0.0, float(getattr(self.p, "fifo_hold_buffer_scale", 0.1)))
        self.p.fifo_approach_sep_scale = max(0.0, float(getattr(self.p, "fifo_approach_sep_scale", 3.0)))
        self.p.fifo_approach_time_s = max(0.0, float(getattr(self.p, "fifo_approach_time_s", 4.0)))
        self.p.auto_spawn_enabled = bool(getattr(self.p, "auto_spawn_enabled", False))
        self.p.spawn_spacing_m = max(float(self.p.sep_min_m), float(self.p.spawn_spacing_m))
        self.p.route_grid_spacing_m = max(1000.0, float(self.p.route_grid_spacing_m))
        self.p.route_row_count = max(1, int(self.p.route_row_count))
        self.p.route_row_gap_m = max(200.0, float(self.p.route_row_gap_m))
        self.p.route_samples_per_segment = max(8, int(self.p.route_samples_per_segment))
        self.p.wind_level = str(getattr(self.p, "wind_level", "normal")).lower()
        if self.p.wind_level not in {"normal", "middle", "serious"}:
            self.p.wind_level = "normal"
        self.p.a_max_mps2 = max(0.0, float(self.p.a_max_mps2))
        self.p.b_max_mps2 = max(0.0, float(self.p.b_max_mps2))

        v_max_mps = self.p.v_max_knots * KNOT_TO_MPS
        for ac in self.aircraft:
            ac.v_cmd_knots = self._clamp_command_knots(ac.v_cmd_knots)
            ac.v_act_mps = float(min(max(ac.v_act_mps, 0.0), v_max_mps))

    def _reset_route_network(self, use_default_links: bool = True):
        self.route_nodes = build_route_grid(
            self.p.path_length_m,
            row_count=self.p.route_row_count,
            row_gap_m=self.p.route_row_gap_m,
            spacing_m=self.p.route_grid_spacing_m,
        )
        pairs = default_straight_link_pairs(self.route_nodes) if use_default_links else []
        self.route_links = build_links(self.route_nodes, pairs)
        self.route_adjacency = build_adjacency(self.route_links)
        self._reset_route_node_control()
        self._refresh_route_preview_paths()

    def _refresh_route_preview_paths(self):
        paths = enumerate_complete_paths(self.route_nodes, self.route_adjacency, max_paths=256)
        previews: List[dict] = []
        for node_ids in paths:
            geom = build_route_geometry(
                node_ids,
                self.route_nodes,
                samples_per_segment=self.p.route_samples_per_segment,
            )
            previews.append(
                geometry_preview_dict(
                    geom,
                    start_id=node_ids[0] if node_ids else None,
                    end_id=node_ids[-1] if node_ids else None,
                )
            )
        self.route_preview_paths = previews

    def clear_route_links(self):
        self.route_links = {}
        self.route_adjacency = {}
        self._reset_route_node_control()
        self._refresh_route_preview_paths()

    def reset_route_links(self):
        self._reset_route_network(use_default_links=True)

    def toggle_route_link(self, start_id: str, end_id: str) -> bool:
        if not validate_link_pair(start_id, end_id, self.route_nodes):
            return False
        key = link_id(start_id, end_id)
        if key in self.route_links:
            self.route_links.pop(key, None)
        else:
            self.route_links[key] = build_links(self.route_nodes, [(start_id, end_id)])[key]
        self.route_adjacency = build_adjacency(self.route_links)
        self._reset_route_node_control()
        self._refresh_route_preview_paths()
        return True

    def set_simulation_mode(self, mode: str):
        mode = str(mode).lower()
        if mode not in {"corridor", "route"}:
            return
        self.p.simulation_mode = mode

    def _is_route_mode(self) -> bool:
        return self.p.simulation_mode == "route"

    def _effective_spawn_spacing_m(self) -> float:
        return max(float(self.p.sep_min_m), float(self.p.spawn_spacing_m))

    def _can_auto_spawn_corridor(self) -> bool:
        spacing_m = self._effective_spawn_spacing_m()
        active_progress = [max(0.0, ac.x_m) for ac in self.aircraft if not ac.route_mode]
        if not active_progress:
            return True
        return min(active_progress) >= spacing_m - 1e-9

    def _can_auto_spawn_route_start(self, start_node_id: str) -> bool:
        if not self._reachable_route_end_nodes(start_node_id):
            return False
        spacing_m = self._effective_spawn_spacing_m()
        active_progress = [
            max(0.0, ac.route_progress_m)
            for ac in self.aircraft
            if ac.route_mode and ac.origin_node_id == start_node_id
        ]
        if not active_progress:
            return True
        return min(active_progress) >= spacing_m - 1e-9

    def attempt_auto_spawn(self) -> List[int]:
        self.normalize_model_params()
        if not self.p.auto_spawn_enabled:
            return []

        spawned_ids: List[int] = []
        if self._is_route_mode():
            for node in self._route_start_nodes():
                if not self._can_auto_spawn_route_start(node.id):
                    continue
                ac_id = self._spawn_route_aircraft(node.id)
                if ac_id is not None:
                    spawned_ids.append(ac_id)
        else:
            if self._can_auto_spawn_corridor():
                ac_id = self.spawn_aircraft()
                if ac_id is not None:
                    spawned_ids.append(ac_id)
        return spawned_ids

    def _get_wind_profile(self) -> Dict[str, float]:
        level = self.p.wind_level
        profiles = {
            "normal": {
                "label": "normal",
                "base_knots": 6.0,
                "variation_knots": 4.0,
                "cross_knots": 4.0,
                "shear_knots": 2.5,
                "max_knots": 15.0,
                "drift_gain": 0.20,
                "recenter_s": 18.0,
            },
            "middle": {
                "label": "middle",
                "base_knots": 12.0,
                "variation_knots": 7.5,
                "cross_knots": 7.0,
                "shear_knots": 4.5,
                "max_knots": 30.0,
                "drift_gain": 0.28,
                "recenter_s": 20.0,
            },
            "serious": {
                "label": "serious",
                "base_knots": 20.0,
                "variation_knots": 11.0,
                "cross_knots": 11.0,
                "shear_knots": 6.5,
                "max_knots": 45.0,
                "drift_gain": 0.38,
                "recenter_s": 24.0,
            },
        }
        profile = dict(profiles.get(level, profiles["normal"]))
        for key in ("base_knots", "variation_knots", "cross_knots", "shear_knots", "max_knots"):
            profile[key.replace("_knots", "_mps")] = profile[key] * KNOT_TO_MPS
        return profile

    def _wind_vector_mps(self, x_m: float, y_m: float, t_s: float) -> Tuple[float, float]:
        if not self.p.wind_enabled:
            return 0.0, 0.0

        cfg = self._get_wind_profile()
        x_norm = float(x_m) / 5000.0
        y_scale = max(self.p.lane_width_m * 4.0, 1200.0)
        y_norm = float(y_m) / y_scale
        t_fast = float(t_s) / 20.0
        t_slow = float(t_s) / 46.0
        t_gust = float(t_s) / 14.0

        prevailing_phase = (
            0.58 * math.sin(t_s / 28.0)
            + 0.34 * math.cos(t_s / 57.0)
            + 0.18 * math.sin(0.70 * x_norm - 0.35 * y_norm + t_s / 34.0)
        )
        prevailing_dir = math.pi * prevailing_phase
        u_base = cfg["base_mps"] * math.cos(prevailing_dir)
        v_base = cfg["base_mps"] * math.sin(prevailing_dir) * 0.65

        gust_gain = 1.0 + 0.24 * math.sin(0.9 * x_norm + t_gust) + 0.14 * math.cos(0.45 * y_norm - 0.7 * t_gust)

        u_wave = cfg["variation_mps"] * gust_gain * (
            0.60 * math.sin(0.95 * x_norm + 0.95 * t_fast + 0.45 * math.sin(0.8 * y_norm + 1.2 * t_slow))
            + 0.32 * math.cos(0.45 * x_norm - 0.2 * y_norm - 1.05 * t_slow)
        )
        v_wave = cfg["cross_mps"] * gust_gain * (
            0.82 * math.sin(0.55 * x_norm - 1.15 * t_fast)
            + 0.50 * math.cos(1.1 * x_norm + 0.7 * y_norm + 0.9 * t_slow)
        )
        shear = cfg["shear_mps"] * (
            math.sin(0.35 * x_norm + 1.15 * t_slow)
            + 0.25 * math.cos(0.55 * x_norm - 0.8 * t_fast)
        ) * math.tanh(float(y_m) / max(self.p.lane_width_m, 80.0))

        wx = u_base + u_wave + 0.35 * shear
        wy = v_base + v_wave + shear
        mag = math.hypot(wx, wy)
        if mag > cfg["max_mps"] > 1e-9:
            scale = cfg["max_mps"] / mag
            wx *= scale
            wy *= scale
        return wx, wy

    def _wind_lateral_rate_mps(self, y_m: float, wind_y_mps: float) -> float:
        if not self.p.wind_enabled:
            return 0.0
        cfg = self._get_wind_profile()
        return wind_y_mps * cfg["drift_gain"] - float(y_m) / max(cfg["recenter_s"], 1e-6)

    def _wind_lateral_limit_m(self) -> float:
        return max(self.p.lane_width_m * 3.5, 500.0)

    def _reset_route_node_control(self):
        self.node_release_t_s = {node_id: 0.0 for node_id in self.route_nodes}
        self.node_fifo_requests = {node_id: {} for node_id in self.route_nodes}

    def _cleanup_route_node_requests(self):
        active_ids = {
            ac.id
            for ac in self.aircraft
            if ac.route_mode and ac.route_geometry is not None and ac.action is None
        }
        for requests in self.node_fifo_requests.values():
            stale_ids = [ac_id for ac_id in requests.keys() if ac_id not in active_ids]
            for ac_id in stale_ids:
                requests.pop(ac_id, None)

    def _register_route_node_request(self, node_id: str, ac_id: int, request_t_s: float):
        requests = self.node_fifo_requests.setdefault(str(node_id), {})
        request_t = float(request_t_s)
        current_t = requests.get(int(ac_id))
        if current_t is None or request_t < current_t:
            requests[int(ac_id)] = request_t

    def _clear_route_node_request(self, node_id: str, ac_id: int):
        requests = self.node_fifo_requests.get(str(node_id))
        if requests is None:
            return
        requests.pop(int(ac_id), None)

    def _peek_route_node_request(self, node_id: str) -> Optional[int]:
        requests = self.node_fifo_requests.get(str(node_id), {})
        if not requests:
            return None
        return min(requests.items(), key=lambda item: (item[1], item[0]))[0]

    def _route_node_request_rank(self, node_id: str, ac_id: int) -> Optional[int]:
        requests = self.node_fifo_requests.get(str(node_id), {})
        if int(ac_id) not in requests:
            return None
        ordered = sorted(requests.items(), key=lambda item: (item[1], item[0]))
        for idx, (queued_id, _) in enumerate(ordered):
            if queued_id == int(ac_id):
                return idx
        return None

    def _route_hold_progress_limit(self, local_s: float, hold_local_s: float, dt: float,
                                   current_ground_mps: float) -> float:
        local_s = float(local_s)
        hold_local_s = max(local_s, float(hold_local_s))
        remaining_m = max(0.0, hold_local_s - local_s)
        if remaining_m <= 1e-9:
            return local_s

        stop_speed_mps = math.sqrt(
            max(0.0, 2.0 * max(self.p.b_max_mps2, 1e-6) * remaining_m)
        )
        limited_ground_mps = self._advance_speed_target(
            max(0.0, float(current_ground_mps)),
            stop_speed_mps,
            dt,
        )
        return min(hold_local_s, local_s + max(0.0, limited_ground_mps) * dt)

    def _get_flight_time_s(self, ac: Aircraft) -> float:
        if (not ac.has_departed) or ac.depart_t_s is None:
            return 0.0
        return max(0.0, self.t_s - float(ac.depart_t_s))

    def _predict_travel_time_s(self, distance_m: float, v0_mps: float, v_target_mps: float,
                               x0_m: float = 0.0, y0_m: float = 0.0, t0_s: Optional[float] = None) -> float:
        distance = max(0.0, float(distance_m))
        v0 = max(0.0, float(v0_mps))
        v_target = max(0.0, float(v_target_mps))
        if distance <= 1e-9:
            return 0.0

        dt = max(float(self.p.dt_s), 1e-9)
        v_max = self.p.v_max_knots * KNOT_TO_MPS
        v_prev = min(v0, v_max)
        v_target = min(v_target, v_max)
        a_max = max(float(self.p.a_max_mps2), 1e-9)
        b_max = max(float(self.p.b_max_mps2), 1e-9)
        elapsed = 0.0
        remaining = distance
        x_pos = float(x0_m)
        y_pos = float(y0_m)
        t_abs = self.t_s if t0_s is None else float(t0_s)

        # Match the engine's stepwise speed update so the scheduled time
        # aligns with the actual no-disturbance arrival time.
        for _ in range(100000):
            v_high = min(v_prev + a_max * dt, v_max)
            v_low = max(0.0, v_prev - b_max * dt)
            if v_target > v_high:
                v_new = v_high
            elif v_target < v_low:
                v_new = v_low
            else:
                v_new = v_target

            wx_mps, wy_mps = self._wind_vector_mps(x_pos, y_pos, t_abs + elapsed)
            ground_x_mps = max(0.0, v_new + wx_mps)
            step_dist = ground_x_mps * dt
            if step_dist >= remaining - 1e-9:
                return math.inf if ground_x_mps <= 1e-9 else elapsed + remaining / ground_x_mps

            remaining -= step_dist
            elapsed += dt
            v_prev = v_new
            x_pos += step_dist
            y_pos = float(np.clip(
                y_pos + self._wind_lateral_rate_mps(y_pos, wy_mps) * dt,
                -self._wind_lateral_limit_m(),
                self._wind_lateral_limit_m(),
            ))

        wx_mps, _ = self._wind_vector_mps(x_pos, y_pos, t_abs + elapsed)
        ground_target_mps = max(0.0, v_target + wx_mps)
        return math.inf if ground_target_mps <= 1e-9 else elapsed + remaining / ground_target_mps

    def reset(self):
        self.t_s = 0.0
        self._next_id = 1
        self.aircraft.clear()
        self._reset_route_node_control()

    def _route_start_nodes(self) -> List[RouteNode]:
        starts = [node for node in self.route_nodes.values() if node.role == "start"]
        return sorted(starts, key=lambda node: node.row)

    def _route_end_nodes(self) -> List[RouteNode]:
        ends = [node for node in self.route_nodes.values() if node.role == "end"]
        return sorted(ends, key=lambda node: node.row)

    def _reachable_route_end_nodes(self, start_node_id: str) -> List[str]:
        return reachable_end_nodes(start_node_id, self.route_nodes, self.route_adjacency)

    def _predict_route_travel_time_s(
        self,
        geometry: RouteGeometry,
        distance_m: float,
        v0_mps: float,
        v_target_mps: float,
        progress_m: float = 0.0,
        t0_s: Optional[float] = None,
    ) -> float:
        remaining = max(0.0, float(distance_m))
        if remaining <= 1e-9:
            return 0.0

        dt = max(float(self.p.dt_s), 1e-9)
        v_prev = min(max(float(v0_mps), 0.0), self.p.v_max_knots * KNOT_TO_MPS)
        v_target = min(max(float(v_target_mps), 0.0), self.p.v_max_knots * KNOT_TO_MPS)
        a_max = max(float(self.p.a_max_mps2), 1e-9)
        b_max = max(float(self.p.b_max_mps2), 1e-9)
        elapsed = 0.0
        s = max(0.0, float(progress_m))
        t_abs = self.t_s if t0_s is None else float(t0_s)

        for _ in range(100000):
            v_high = min(v_prev + a_max * dt, self.p.v_max_knots * KNOT_TO_MPS)
            v_low = max(0.0, v_prev - b_max * dt)
            if v_target > v_high:
                v_new = v_high
            elif v_target < v_low:
                v_new = v_low
            else:
                v_new = v_target

            x, y, heading = geometry.sample(s)
            wx_mps, wy_mps = self._wind_vector_mps(x, y, t_abs + elapsed)
            along_wind_mps = wx_mps * math.cos(heading) + wy_mps * math.sin(heading)
            ground_mps = max(0.0, v_new + along_wind_mps)
            step_dist = ground_mps * dt
            if step_dist >= remaining - 1e-9:
                return math.inf if ground_mps <= 1e-9 else elapsed + remaining / ground_mps

            remaining -= step_dist
            elapsed += dt
            s += step_dist
            v_prev = v_new

        x, y, heading = geometry.sample(s)
        wx_mps, wy_mps = self._wind_vector_mps(x, y, t_abs + elapsed)
        along_wind_mps = wx_mps * math.cos(heading) + wy_mps * math.sin(heading)
        ground_target_mps = max(0.0, v_target + along_wind_mps)
        return math.inf if ground_target_mps <= 1e-9 else elapsed + remaining / ground_target_mps

    def _estimate_corridor_eta_remaining_s(self, ac: Aircraft) -> float:
        remaining_m = max(0.0, self.p.path_length_m - float(ac.x_m))
        if remaining_m <= 1e-9:
            return 0.0

        target_air_mps = self._clamp_command_knots(ac.v_cmd_knots) * KNOT_TO_MPS
        wx_mps, _ = self._wind_vector_mps(ac.x_m, ac.y_m, self.t_s)
        target_ground_mps = max(0.0, target_air_mps + wx_mps)
        current_ground_mps = max(0.0, float(ac.ground_vx_mps))

        if current_ground_mps <= 1e-6:
            effective_ground_mps = target_ground_mps
        else:
            effective_ground_mps = 0.4 * current_ground_mps + 0.6 * target_ground_mps

        effective_ground_mps = max(effective_ground_mps, 1e-3)
        return remaining_m / effective_ground_mps

    def _estimate_route_eta_remaining_s(self, ac: Aircraft) -> float:
        remaining_m = max(0.0, float(ac.route_total_m - ac.route_progress_m))
        if remaining_m <= 1e-9:
            return 0.0
        if ac.route_geometry is None:
            return math.inf

        target_air_mps = self._clamp_command_knots(ac.v_cmd_knots) * KNOT_TO_MPS
        target_ground_mps = self._estimate_route_ground_speed_mps(ac, target_air_mps)
        current_ground_mps = max(0.0, math.hypot(ac.ground_vx_mps, ac.ground_vy_mps))

        if current_ground_mps <= 1e-6:
            effective_ground_mps = target_ground_mps
        else:
            effective_ground_mps = 0.4 * current_ground_mps + 0.6 * target_ground_mps

        effective_ground_mps = max(effective_ground_mps, 1e-3)
        return remaining_m / effective_ground_mps

    def _plan_route(self, start_node_id: str) -> Optional[dict]:
        reachable_ends = self._reachable_route_end_nodes(start_node_id)
        if not reachable_ends:
            return None

        end_node_id = random.choice(reachable_ends)
        node_ids = shortest_path(
            start_node_id,
            end_node_id,
            self.route_nodes,
            self.route_links,
            self.route_adjacency,
        )
        if not node_ids:
            return None

        geometry = build_route_geometry(
            node_ids,
            self.route_nodes,
            samples_per_segment=self.p.route_samples_per_segment,
        )
        return {
            "start_node_id": start_node_id,
            "end_node_id": end_node_id,
            "node_ids": node_ids,
            "geometry": geometry,
        }

    def _spawn_route_aircraft(self, start_node_id: str) -> Optional[int]:
        plan = self._plan_route(start_node_id)
        if not plan:
            return None

        start_node = self.route_nodes[start_node_id]
        geometry: RouteGeometry = plan["geometry"]
        v_cmd_knots = self.p.v_free_knots
        v_init_knots = self.p.v_init_knots
        sched_travel_s = self._predict_route_travel_time_s(
            geometry,
            geometry.total_length_m,
            v_init_knots * KNOT_TO_MPS,
            v_cmd_knots * KNOT_TO_MPS,
            progress_m=0.0,
            t0_s=self.t_s,
        )
        ac = Aircraft(
            self._next_id,
            start_node.x_m,
            start_node.y_m,
            v_cmd_knots,
            v_act_knots=v_init_knots,
            sta_s=self.t_s + sched_travel_s,
            spawn_t_s=self.t_s,
        )
        ac.route_mode = True
        ac.origin_node_id = start_node_id
        ac.destination_node_id = plan["end_node_id"]
        ac.route_node_ids = list(plan["node_ids"])
        ac.route_link_ids = list(geometry.link_ids)
        ac.route_geometry = geometry
        ac.route_total_m = float(geometry.total_length_m)
        ac.route_progress_m = 0.0
        ac.active_link_id = geometry.link_ids[0] if geometry.link_ids else None
        ac.has_departed = False
        ac.depart_t_s = None
        ac.heading_rad = 0.0
        ac.wait_reason = "route_start"
        wx_mps, wy_mps = self._wind_vector_mps(start_node.x_m, start_node.y_m, self.t_s)
        ac.wind_x_mps = wx_mps
        ac.wind_y_mps = wy_mps
        ac.ground_vx_mps = 0.0
        ac.ground_vy_mps = 0.0
        self._next_id += 1
        self.aircraft.append(ac)
        return ac.id

    def spawn_aircraft(self, start_node_id: Optional[str] = None):
        self.normalize_model_params()
        if self._is_route_mode():
            if start_node_id is None:
                starts = [node.id for node in self._route_start_nodes() if self._reachable_route_end_nodes(node.id)]
                if not starts:
                    return None
                start_node_id = random.choice(starts)
            return self._spawn_route_aircraft(start_node_id)

        x0 = 0.0
        y0 = 0.0
        v_cmd_knots = self.p.v_free_knots
        v_init_knots = self.p.v_init_knots
        sched_travel_s = self._predict_travel_time_s(
            self.p.path_length_m - x0,
            v_init_knots * KNOT_TO_MPS,
            v_cmd_knots * KNOT_TO_MPS,
            x0_m=x0,
            y0_m=y0,
            t0_s=self.t_s,
        )
        ac = Aircraft(
            self._next_id,
            x0,
            y0,
            v_cmd_knots,
            v_act_knots=v_init_knots,
            sta_s=self.t_s + sched_travel_s,
            spawn_t_s=self.t_s,
        )
        wx_mps, wy_mps = self._wind_vector_mps(x0, y0, self.t_s)
        ac.wind_x_mps = wx_mps
        ac.wind_y_mps = wy_mps
        ac.ground_vx_mps = max(0.0, ac.v_act_mps + wx_mps)
        ac.ground_vy_mps = self._wind_lateral_rate_mps(y0, wy_mps)
        self._next_id += 1
        self.aircraft.append(ac)
        return ac.id

    def _find_aircraft(self, ac_id: int) -> Optional[Aircraft]:
        for ac in self.aircraft:
            if ac.id == ac_id:
                return ac
        return None

    def _advance_speed_target(self, v_prev_mps: float, v_target_mps: float, dt: float) -> float:
        v_max_mps = self.p.v_max_knots * KNOT_TO_MPS
        v_desired = min(max(float(v_target_mps), 0.0), v_max_mps)
        v_prev = min(max(float(v_prev_mps), 0.0), v_max_mps)
        a_max = max(self.p.a_max_mps2, 1e-6)
        b_max = max(self.p.b_max_mps2, 1e-6)
        v_high = min(v_prev + a_max * dt, v_max_mps)
        v_low = max(0.0, v_prev - b_max * dt)

        if v_desired > v_high:
            return v_high
        if v_desired < v_low:
            return v_low
        return v_desired

    def _route_frame(self, geometry: RouteGeometry, progress_m: float) -> Tuple[float, float, float, float, float]:
        x_center, y_center, heading = geometry.sample(progress_m)
        tx = math.cos(heading)
        ty = math.sin(heading)
        nx = -ty
        ny = tx
        return x_center, y_center, heading, nx, ny

    def _set_route_offset_state(self, ac: Aircraft, progress_m: float, offset_m: float,
                                offset_slope: float, path_ground_mps: float):
        geometry = ac.route_geometry
        if geometry is None:
            return

        x_center, y_center, heading, nx, ny = self._route_frame(geometry, progress_m)
        x_world = x_center + nx * offset_m
        y_world = y_center + ny * offset_m
        progress_rate_mps = max(0.0, float(path_ground_mps)) / max(math.sqrt(1.0 + offset_slope * offset_slope), 1e-6)
        lateral_ground_mps = offset_slope * progress_rate_mps
        gvx = math.cos(heading) * progress_rate_mps + nx * lateral_ground_mps
        gvy = math.sin(heading) * progress_rate_mps + ny * lateral_ground_mps
        wx_mps, wy_mps = self._wind_vector_mps(x_world, y_world, self.t_s)

        ac.route_progress_m = min(max(float(progress_m), 0.0), geometry.total_length_m)
        ac.x_m = float(x_world)
        ac.y_m = float(y_world)
        ac.wind_x_mps = float(wx_mps)
        ac.wind_y_mps = float(wy_mps)
        ac.ground_vx_mps = float(gvx)
        ac.ground_vy_mps = float(gvy)
        if abs(gvx) > 1e-6 or abs(gvy) > 1e-6:
            ac.heading_rad = math.atan2(gvy, gvx)
        else:
            ac.heading_rad = float(heading)

    def _route_overtake_profile(self, progress_m: float, phase_start_progress_m: float,
                                transition_m: float, offset_m: float, invert: bool = False) -> Tuple[float, float, float]:
        prog = min(max((float(progress_m) - float(phase_start_progress_m)) / max(float(transition_m), 1e-6), 0.0), 1.0)
        smooth = self._smoothstep(prog)
        offset_value = offset_m * (1.0 - smooth) if invert else offset_m * smooth
        offset_slope = (offset_m * 6.0 * prog * (1.0 - prog)) / max(float(transition_m), 1e-6)
        if invert:
            offset_slope *= -1.0
        return prog, float(offset_value), float(offset_slope)

    def _estimate_route_ground_speed_mps(self, ac: Aircraft, airspeed_mps: float,
                                         progress_m: Optional[float] = None) -> float:
        geometry = ac.route_geometry
        if geometry is None:
            return max(0.0, float(airspeed_mps))

        s = ac.route_progress_m if progress_m is None else float(progress_m)
        x, y, heading = geometry.sample(s)
        wx_mps, wy_mps = self._wind_vector_mps(x, y, self.t_s)
        along_wind_mps = wx_mps * math.cos(heading) + wy_mps * math.sin(heading)
        return max(0.0, float(airspeed_mps) + along_wind_mps)

    def _route_shared_future_distance_m(self, ac: Aircraft, other: Aircraft) -> float:
        ac_geometry = ac.route_geometry
        other_geometry = other.route_geometry
        if ac_geometry is None or other_geometry is None:
            return 0.0
        if not ac.route_link_ids or not other.route_link_ids:
            return 0.0

        ac_idx = ac_geometry.active_link_index(ac.route_progress_m)
        other_idx = other_geometry.active_link_index(other.route_progress_m)
        if ac_idx >= len(ac.route_link_ids) or other_idx >= len(other.route_link_ids):
            return 0.0
        if ac.route_link_ids[ac_idx] != other.route_link_ids[other_idx]:
            return 0.0

        shared_m = max(0.0, float(ac_geometry.node_progress_m[ac_idx + 1] - ac.route_progress_m))
        ac_next = ac_idx + 1
        other_next = other_idx + 1
        while ac_next < len(ac.route_link_ids) and other_next < len(other.route_link_ids):
            if ac.route_link_ids[ac_next] != other.route_link_ids[other_next]:
                break
            shared_m += float(
                ac_geometry.node_progress_m[ac_next + 1] - ac_geometry.node_progress_m[ac_next]
            )
            ac_next += 1
            other_next += 1
        return shared_m

    def _route_overtake_feasibility(
        self,
        ac: Aircraft,
        lead: Aircraft,
        offset_m: float,
        boost_cmd_knots: float,
    ) -> bool:
        if (not ac.route_mode) or ac.route_geometry is None or (not lead.route_mode):
            return True

        ac_state = self._route_link_state(ac)
        lead_state = self._route_link_state(lead)
        if not ac_state or not lead_state or ac_state["link_id"] != lead_state["link_id"]:
            return False

        gap_m = float(lead.route_progress_m - ac.route_progress_m)
        if gap_m <= 0.0:
            return False

        transition_m = max(220.0, float(offset_m) * 3.0)
        node_buffer_m = max(self.p.sep_min_m * 1.25, 160.0)
        shared_future_m = self._route_shared_future_distance_m(ac, lead)
        if shared_future_m <= 1e-6:
            return False

        own_ground_mps = max(
            1.0,
            self._estimate_route_ground_speed_mps(
                ac,
                self._clamp_command_knots(boost_cmd_knots) * KNOT_TO_MPS,
            ),
        )
        lead_ground_mps = max(
            0.0,
            math.hypot(float(lead.ground_vx_mps), float(lead.ground_vy_mps)),
        )
        if lead_ground_mps <= 1e-6:
            lead_ground_mps = self._estimate_route_ground_speed_mps(lead, lead.v_act_mps)

        relative_mps = own_ground_mps - lead_ground_mps
        if relative_mps < max(0.75 * KNOT_TO_MPS, 0.5):
            return False

        lateral_time_s = (2.0 * transition_m) / own_ground_mps
        pass_distance_m = max(0.0, gap_m + self.p.sep_min_m)
        pass_time_s = pass_distance_m / max(relative_mps, 1e-6)
        total_time_s = lateral_time_s + pass_time_s
        own_required_m = own_ground_mps * total_time_s

        return shared_future_m >= own_required_m + node_buffer_m

    def command_turn(self, ac_id: int, diameter_m: float) -> bool:
        ac = self._find_aircraft(ac_id)
        if ac is None or ac.action is not None:
            return False

        radius_m = max(100.0, float(diameter_m) * 0.5)
        base_heading = float(ac.heading_rad)
        if ac.route_mode and ac.route_geometry is not None:
            _, _, base_heading = ac.route_geometry.sample(ac.route_progress_m)
        left_x = -math.sin(base_heading)
        left_y = math.cos(base_heading)
        center_x_m = float(ac.x_m + left_x * radius_m)
        center_y_m = float(ac.y_m + left_y * radius_m)
        theta_rad = math.atan2(ac.y_m - center_y_m, ac.x_m - center_x_m)
        ac.action = "turn"
        ac.action_phase = "orbit"
        ac.action_state = {
            "center_x_m": center_x_m,
            "center_y_m": center_y_m,
            "radius_m": radius_m,
            "theta_rad": theta_rad,
            "theta_end_rad": theta_rad + 2.0 * math.pi,
            "turn_sign": 1.0,
            "resume_heading_rad": base_heading,
            "resume_route_progress_m": float(ac.route_progress_m),
        }
        return True

    def _find_overtake_candidate(self, ac: Aircraft, target_id: Optional[int] = None) -> Optional[Aircraft]:
        if ac.action is not None:
            return None

        lead: Optional[Aircraft] = None
        if target_id is not None:
            target = self._find_aircraft(int(target_id))
            if target is None or target.id == ac.id or target.action is not None:
                return None
            if ac.route_mode:
                if (
                    (not target.route_mode)
                    or (target.active_link_id != ac.active_link_id)
                    or (target.route_progress_m <= ac.route_progress_m)
                ):
                    return None
            elif target.x_m <= ac.x_m:
                return None
            return target

        for other in self.aircraft:
            if other.id == ac.id or other.action is not None:
                continue
            if ac.route_mode:
                if (
                    (not other.route_mode)
                    or (other.active_link_id != ac.active_link_id)
                    or (other.route_progress_m <= ac.route_progress_m)
                ):
                    continue
            else:
                if other.x_m <= ac.x_m:
                    continue
            if lead is None:
                lead = other
            elif ac.route_mode:
                if other.route_progress_m < lead.route_progress_m:
                    lead = other
            elif other.x_m < lead.x_m:
                lead = other
        return lead

    def command_overtake(self, ac_id: int, lateral_offset_m: float = 100.0,
                         speed_boost_knots: float = 20.0, target_id: Optional[int] = None) -> bool:
        ac = self._find_aircraft(ac_id)
        if ac is None or ac.action is not None:
            return False

        lead = self._find_overtake_candidate(ac, target_id)
        if lead is None:
            return False

        offset_m = max(40.0, float(lateral_offset_m))
        transition_m = max(220.0, offset_m * 3.0)
        base_cmd_knots = self._clamp_command_knots(ac.v_cmd_knots)
        boost_cmd_knots = self._clamp_command_knots(
            max(base_cmd_knots + float(speed_boost_knots), lead.v_act_mps * MPS_TO_KNOT + 5.0)
        )
        if ac.route_mode and not self._route_overtake_feasibility(ac, lead, offset_m, boost_cmd_knots):
            return False

        ac.action = "overtake"
        ac.action_phase = "offset_out"
        ac.action_state = {
            "offset_m": offset_m,
            "transition_m": transition_m,
            "start_x_m": float(ac.x_m),
            "start_progress_m": float(ac.route_progress_m),
            "merge_start_x_m": None,
            "merge_start_progress_m": None,
            "lead_id": lead.id,
            "boost_cmd_knots": boost_cmd_knots,
        }
        return True

    def delete_aircraft(self, ac_id: int):
        self.aircraft = [ac for ac in self.aircraft if ac.id != ac_id]

    def set_aircraft_speed(self, ac_id: int, v_knots: float):
        for ac in self.aircraft:
            if ac.id == ac_id:
                ac.set_command_speed(self._clamp_command_knots(v_knots))
                return

    def _step_corridor_aircraft(self, corridor_aircraft: List[Aircraft], dt: float):
        if not corridor_aircraft:
            return

        x_old = np.array([ac.x_m for ac in corridor_aircraft], dtype=float)
        y_old = np.array([ac.y_m for ac in corridor_aircraft], dtype=float)
        v_cmd_mps = np.array(
            [self._clamp_command_knots(ac.v_cmd_knots) for ac in corridor_aircraft],
            dtype=float,
        ) * KNOT_TO_MPS
        v_max_mps = self.p.v_max_knots * KNOT_TO_MPS
        v_prev_mps = np.clip(
            np.array([ac.v_act_mps for ac in corridor_aircraft], dtype=float),
            0.0,
            v_max_mps,
        )

        order = np.argsort(-x_old)
        x_sorted = x_old[order]
        y_sorted = y_old[order]
        v_cmd_sorted = v_cmd_mps[order]
        v_prev_sorted = v_prev_mps[order]
        has_departed_sorted = np.array([ac.has_departed for ac in corridor_aircraft], dtype=bool)[order]
        wind_sorted = np.array(
            [self._wind_vector_mps(xi, yi, self.t_s) for xi, yi in zip(x_sorted, y_sorted)],
            dtype=float,
        )
        wind_x_sorted = wind_sorted[:, 0] if len(wind_sorted) else np.array([], dtype=float)
        wind_y_sorted = wind_sorted[:, 1] if len(wind_sorted) else np.array([], dtype=float)

        v_air_new_sorted = np.zeros_like(v_cmd_sorted)
        v_ground_x_sorted = np.zeros_like(v_cmd_sorted)
        y_new_sorted = np.array(y_sorted, copy=True)
        a_max = max(self.p.a_max_mps2, 1e-6)
        b_max = max(self.p.b_max_mps2, 1e-6)
        v_init_mps = self.p.v_init_knots * KNOT_TO_MPS

        for k in range(len(x_sorted)):
            wx = wind_x_sorted[k]
            wy = wind_y_sorted[k]
            is_waiting_at_start = (not has_departed_sorted[k]) and x_sorted[k] <= 1e-9

            if k == 0:
                v_desired = min(v_cmd_sorted[k], v_max_mps)
                v_high = min(v_prev_sorted[k] + a_max * dt, v_max_mps)
                v_low = max(0.0, v_prev_sorted[k] - b_max * dt)
                if v_desired > v_high:
                    v_air = v_high
                elif v_desired < v_low:
                    v_air = v_low
                else:
                    v_air = v_desired
                if is_waiting_at_start:
                    v_launch = min(v_init_mps, v_cmd_sorted[k], v_max_mps)
                    launch_ground = max(0.0, v_launch + wx)
                    if launch_ground > 1e-9:
                        v_air = max(v_air, v_launch)
                    else:
                        v_air = 0.0
                v_air_new_sorted[k] = min(max(0.0, v_air), v_max_mps)
                v_ground_x_sorted[k] = max(0.0, v_air_new_sorted[k] + wx)
                if is_waiting_at_start:
                    y_new_sorted[k] = 0.0
                else:
                    y_new_sorted[k] = float(np.clip(
                        y_sorted[k] + self._wind_lateral_rate_mps(y_sorted[k], wy) * dt,
                        -self._wind_lateral_limit_m(),
                        self._wind_lateral_limit_m(),
                    ))
                continue

            gap = x_sorted[k - 1] - x_sorted[k]
            v_lead_ground = v_ground_x_sorted[k - 1]
            target_gap = self._target_follow_gap_m(gap, dt)
            v_safe_ground = v_lead_ground + (gap - target_gap) / max(dt, 1e-6)
            v_safe_ground = max(0.0, v_safe_ground)
            v_safe_air = max(0.0, v_safe_ground - wx)
            v_desired = min(v_cmd_sorted[k], v_safe_air, v_max_mps)
            v_high = min(v_prev_sorted[k] + a_max * dt, v_max_mps)
            v_low = max(0.0, v_prev_sorted[k] - b_max * dt)
            if v_desired > v_high:
                v_air = v_high
            elif v_desired < v_low:
                v_air = v_low
            else:
                v_air = v_desired
            ground_x = max(0.0, v_air + wx)

            if is_waiting_at_start:
                v_launch = min(v_init_mps, v_cmd_sorted[k], v_max_mps)
                launch_ground = max(0.0, v_launch + wx)
                launch_gap_required = self.p.sep_min_m + max(0.0, launch_ground - v_lead_ground) * dt
                if gap + 1e-9 >= launch_gap_required and launch_ground > 1e-9:
                    v_air = max(v_air, v_launch)
                    ground_x = max(0.0, v_air + wx)
                else:
                    v_air = 0.0
                    ground_x = 0.0

            if ground_x > v_safe_ground:
                ground_x = v_safe_ground
                v_air = max(0.0, ground_x - wx)

            v_air_new_sorted[k] = min(max(0.0, v_air), v_max_mps)
            v_ground_x_sorted[k] = max(0.0, ground_x)
            if is_waiting_at_start:
                y_new_sorted[k] = 0.0
            else:
                y_new_sorted[k] = float(np.clip(
                    y_sorted[k] + self._wind_lateral_rate_mps(y_sorted[k], wy) * dt,
                    -self._wind_lateral_limit_m(),
                    self._wind_lateral_limit_m(),
                ))

        x_new_sorted = x_sorted + v_ground_x_sorted * dt

        for k in range(1, len(x_new_sorted)):
            current_gap = max(0.0, x_sorted[k - 1] - x_sorted[k])
            protected_gap = self.p.sep_min_m if current_gap >= self.p.sep_min_m else current_gap
            max_follow = x_new_sorted[k - 1] - protected_gap
            if x_new_sorted[k] > max_follow:
                if max_follow >= x_sorted[k]:
                    x_new_sorted[k] = max_follow
                    v_ground_x_sorted[k] = max(0.0, (x_new_sorted[k] - x_sorted[k]) / max(dt, 1e-6))
                    v_air_new_sorted[k] = max(0.0, v_ground_x_sorted[k] - wind_x_sorted[k])
                else:
                    x_new_sorted[k] = x_sorted[k]
                    v_ground_x_sorted[k] = 0.0
                    v_air_new_sorted[k] = 0.0

        x_new = np.empty_like(x_new_sorted)
        y_new = np.empty_like(y_new_sorted)
        v_air = np.empty_like(v_air_new_sorted)
        v_ground_x = np.empty_like(v_ground_x_sorted)
        wind_x = np.empty_like(wind_x_sorted)
        wind_y = np.empty_like(wind_y_sorted)
        x_new[order] = x_new_sorted
        y_new[order] = y_new_sorted
        v_air[order] = v_air_new_sorted
        v_ground_x[order] = v_ground_x_sorted
        wind_x[order] = wind_x_sorted
        wind_y[order] = wind_y_sorted

        for i, ac in enumerate(corridor_aircraft):
            ac.x_m = float(x_new[i])
            ac.y_m = float(y_new[i])
            ac.v_act_mps = float(max(0.0, v_air[i]))
            ac.wind_x_mps = float(wind_x[i])
            ac.wind_y_mps = float(wind_y[i])
            ac.ground_vx_mps = float(max(0.0, v_ground_x[i]))
            ac.ground_vy_mps = float((ac.y_m - y_old[i]) / max(dt, 1e-6))
            if (not ac.has_departed) and ac.x_m > 1e-9:
                ac.has_departed = True
                ac.depart_t_s = max(0.0, self.t_s - dt)
            if ac.ground_vx_mps > 1e-6 or abs(ac.ground_vy_mps) > 1e-6:
                ac.heading_rad = math.atan2(ac.ground_vy_mps, max(ac.ground_vx_mps, 1e-6))
            else:
                ac.heading_rad = 0.0

    def _smoothstep(self, x: float) -> float:
        t = min(max(float(x), 0.0), 1.0)
        return t * t * (3.0 - 2.0 * t)

    def _target_follow_gap_m(self, current_gap_m: float, dt: float) -> float:
        gap_m = max(0.0, float(current_gap_m))
        if gap_m >= self.p.sep_min_m:
            return float(self.p.sep_min_m)

        recovery_horizon_s = max(2.0, 8.0 * max(dt, 1e-6))
        gain = min(1.0, max(dt, 1e-6) / recovery_horizon_s)
        return min(float(self.p.sep_min_m), gap_m + (float(self.p.sep_min_m) - gap_m) * gain)

    def _update_turn_action(self, ac: Aircraft, dt: float):
        state = ac.action_state
        radius_m = max(float(state.get("radius_m", 400.0)), 1e-6)
        center_x_m = float(state.get("center_x_m", ac.x_m))
        center_y_m = float(state.get("center_y_m", ac.y_m + radius_m))
        theta_rad = float(state.get("theta_rad", math.pi / 2.0))
        theta_end_rad = float(state.get("theta_end_rad", theta_rad + 2.0 * math.pi))
        turn_sign = -1.0 if float(state.get("turn_sign", -1.0)) < 0.0 else 1.0

        target_mps = self._clamp_command_knots(ac.v_cmd_knots) * KNOT_TO_MPS
        ac.v_act_mps = self._advance_speed_target(ac.v_act_mps, target_mps, dt)
        omega = ac.v_act_mps / radius_m
        if omega <= 1e-9:
            ac.x_m = center_x_m + radius_m * math.cos(theta_rad)
            ac.y_m = center_y_m + radius_m * math.sin(theta_rad)
            tangent_sign = math.pi / 2.0 if turn_sign > 0.0 else -math.pi / 2.0
            ac.heading_rad = theta_rad + tangent_sign
            return

        dtheta = turn_sign * omega * dt
        finished = (theta_rad + dtheta <= theta_end_rad + 1e-9) if turn_sign < 0.0 else (theta_rad + dtheta >= theta_end_rad - 1e-9)
        if finished:
            time_to_finish = max(0.0, abs(theta_end_rad - theta_rad) / max(omega, 1e-9))
            resume_heading = float(state.get("resume_heading_rad", 0.0))
            ac.action = None
            ac.action_phase = "idle"
            ac.action_state = {}

            remaining_dt = max(0.0, dt - time_to_finish)
            if ac.route_mode and ac.route_geometry is not None:
                x_resume, y_resume, heading_resume = ac.route_geometry.sample(ac.route_progress_m)
                ac.x_m = float(x_resume)
                ac.y_m = float(y_resume)
                ac.heading_rad = float(heading_resume)
            else:
                ac.x_m = center_x_m + radius_m * math.cos(theta_end_rad)
                ac.y_m = center_y_m + radius_m * math.sin(theta_end_rad)
                ac.heading_rad = resume_heading
            if (not ac.route_mode) and remaining_dt > 1e-9:
                ac.v_act_mps = self._advance_speed_target(ac.v_act_mps, target_mps, remaining_dt)
                ac.x_m += math.cos(resume_heading) * ac.v_act_mps * remaining_dt
                ac.y_m += math.sin(resume_heading) * ac.v_act_mps * remaining_dt
                ac.heading_rad = resume_heading
            return

        theta_rad += dtheta
        state["theta_rad"] = theta_rad
        ac.x_m = center_x_m + radius_m * math.cos(theta_rad)
        ac.y_m = center_y_m + radius_m * math.sin(theta_rad)
        tangent_sign = math.pi / 2.0 if turn_sign > 0.0 else -math.pi / 2.0
        ac.heading_rad = theta_rad + tangent_sign

    def _move_along_lateral_profile(self, x_m: float, distance_m: float, start_x_m: float,
                                    transition_m: float, offset_m: float, invert: bool = False) -> Tuple[float, float, float]:
        local_x = max(0.0, x_m - start_x_m)
        progress = min(max(local_x / transition_m, 0.0), 1.0)
        slope = (offset_m * 6.0 * progress * (1.0 - progress)) / transition_m
        if invert:
            slope *= -1.0

        dx = distance_m / math.sqrt(1.0 + slope * slope)
        new_x = x_m + dx

        new_progress = min(max((new_x - start_x_m) / transition_m, 0.0), 1.0)
        smooth = self._smoothstep(new_progress)
        y = offset_m * (1.0 - smooth) if invert else offset_m * smooth
        new_slope = (offset_m * 6.0 * new_progress * (1.0 - new_progress)) / transition_m
        if invert:
            new_slope *= -1.0
        heading_rad = math.atan2(new_slope, 1.0)
        return new_x, y, heading_rad

    def _apply_managed_wind(self, ac: Aircraft, dt: float):
        wx_mps, wy_mps = self._wind_vector_mps(ac.x_m, ac.y_m, self.t_s)
        base_vx_mps = math.cos(ac.heading_rad) * ac.v_act_mps
        base_vy_mps = math.sin(ac.heading_rad) * ac.v_act_mps
        lateral_drift_mps = self._wind_lateral_rate_mps(ac.y_m, wy_mps) * 0.65
        longitudinal_wind_mps = wx_mps * 0.75

        ac.x_m += longitudinal_wind_mps * dt
        ac.y_m = float(np.clip(
            ac.y_m + lateral_drift_mps * dt,
            -self._wind_lateral_limit_m(),
            self._wind_lateral_limit_m(),
        ))
        ac.wind_x_mps = wx_mps
        ac.wind_y_mps = wy_mps
        # Managed turn actions can legitimately move through full 360 deg, including
        # temporary negative x velocity on the left side of the orbit.
        ac.ground_vx_mps = base_vx_mps + longitudinal_wind_mps
        ac.ground_vy_mps = base_vy_mps + lateral_drift_mps
        if abs(ac.ground_vx_mps) > 1e-6 or abs(ac.ground_vy_mps) > 1e-6:
            ac.heading_rad = math.atan2(ac.ground_vy_mps, ac.ground_vx_mps)

    def _predict_linear_position(self, ac: Aircraft, dt_s: float) -> Tuple[float, float]:
        return (
            float(ac.x_m + ac.ground_vx_mps * dt_s),
            float(ac.y_m + ac.ground_vy_mps * dt_s),
        )

    def _route_current_offset_m(self, ac: Aircraft) -> float:
        geometry = ac.route_geometry
        if geometry is None:
            return 0.0
        x_center, y_center, _, nx, ny = self._route_frame(geometry, ac.route_progress_m)
        return float((ac.x_m - x_center) * nx + (ac.y_m - y_center) * ny)

    def _corridor_merge_path_position(self, ac: Aircraft, start_y_m: float, transition_m: float,
                                      own_ground_mps: float, u: float) -> Tuple[float, float]:
        total_time_s = transition_m / max(own_ground_mps, 1e-6)
        t_s = total_time_s * u
        smooth = self._smoothstep(u)
        x_m = float(ac.x_m + own_ground_mps * t_s)
        y_m = float(start_y_m * (1.0 - smooth))
        return x_m, y_m

    def _route_merge_path_position(self, ac: Aircraft, start_offset_m: float, transition_m: float,
                                   own_ground_mps: float, u: float) -> Tuple[float, float]:
        geometry = ac.route_geometry
        if geometry is None:
            return float(ac.x_m), float(ac.y_m)

        progress_m = min(geometry.total_length_m, ac.route_progress_m + transition_m * u)
        _, offset_m, _ = self._route_overtake_profile(
            progress_m,
            ac.route_progress_m,
            transition_m,
            start_offset_m,
            True,
        )
        x_center, y_center, _, nx, ny = self._route_frame(geometry, progress_m)
        return (
            float(x_center + nx * offset_m),
            float(y_center + ny * offset_m),
        )

    def _get_overtake_target(self, ac: Aircraft) -> Optional[Aircraft]:
        lead_id = ac.action_state.get("lead_id") if ac.action_state else None
        if lead_id is None:
            return None
        return self._find_aircraft(int(lead_id))

    def _has_completed_corridor_overtake(self, ac: Aircraft) -> bool:
        lead = self._get_overtake_target(ac)
        if lead is None or lead.route_mode:
            return True
        pass_margin_m = self.p.sep_min_m + max(20.0, 0.1 * self.p.sep_min_m)
        return float(ac.x_m) >= float(lead.x_m) + pass_margin_m - 1e-9

    def _has_completed_route_overtake(self, ac: Aircraft) -> bool:
        lead = self._get_overtake_target(ac)
        if lead is None or (not lead.route_mode):
            return True
        pass_margin_m = self.p.sep_min_m + max(20.0, 0.1 * self.p.sep_min_m)
        return float(ac.route_progress_m) >= float(lead.route_progress_m) + pass_margin_m - 1e-9

    def _can_start_corridor_merge(self, ac: Aircraft, transition_m: float) -> bool:
        own_ground_mps = max(0.0, float(ac.ground_vx_mps))
        if own_ground_mps <= 1e-6:
            return False

        start_y_m = float(ac.y_m)
        min_required_m = self.p.sep_min_m + max(20.0, 0.1 * self.p.sep_min_m)
        steps = 10

        conflicts = [other for other in self.aircraft if other.id != ac.id and not other.route_mode]
        if not conflicts:
            return True

        for step in range(steps + 1):
            u = step / steps
            own_x_m, own_y_m = self._corridor_merge_path_position(ac, start_y_m, transition_m, own_ground_mps, u)
            t_s = (transition_m / max(own_ground_mps, 1e-6)) * u
            for other in conflicts:
                other_x_m, other_y_m = self._predict_linear_position(other, t_s)
                if math.hypot(own_x_m - other_x_m, own_y_m - other_y_m) < min_required_m - 1e-9:
                    return False
        return True

    def _can_start_route_merge(self, ac: Aircraft, transition_m: float) -> bool:
        geometry = ac.route_geometry
        if geometry is None:
            return False

        own_ground_mps = max(0.0, math.hypot(ac.ground_vx_mps, ac.ground_vy_mps))
        if own_ground_mps <= 1e-6:
            return False

        start_offset_m = self._route_current_offset_m(ac)
        min_required_m = self.p.sep_min_m + max(20.0, 0.1 * self.p.sep_min_m)
        steps = 10
        cumulative_path_m = 0.0
        prev_pos: Optional[Tuple[float, float]] = None

        conflicts = [other for other in self.aircraft if other.id != ac.id and other.route_mode]
        if not conflicts:
            return True

        for step in range(steps + 1):
            u = step / steps
            own_x_m, own_y_m = self._route_merge_path_position(ac, start_offset_m, transition_m, own_ground_mps, u)
            if prev_pos is not None:
                cumulative_path_m += math.hypot(own_x_m - prev_pos[0], own_y_m - prev_pos[1])
            prev_pos = (own_x_m, own_y_m)
            t_s = cumulative_path_m / max(own_ground_mps, 1e-6)
            for other in conflicts:
                other_x_m, other_y_m = self._predict_linear_position(other, t_s)
                if math.hypot(own_x_m - other_x_m, own_y_m - other_y_m) < min_required_m - 1e-9:
                    return False
        return True

    def _update_overtake_action(self, ac: Aircraft, dt: float):
        state = ac.action_state
        offset_m = float(state.get("offset_m", 100.0))
        transition_m = max(float(state.get("transition_m", 300.0)), 1e-6)
        boost_cmd_knots = float(state.get("boost_cmd_knots", ac.v_cmd_knots))
        target_mps = self._clamp_command_knots(boost_cmd_knots) * KNOT_TO_MPS
        ac.v_act_mps = self._advance_speed_target(ac.v_act_mps, target_mps, dt)
        travel_m = ac.v_act_mps * dt

        if ac.action_phase == "offset_out":
            start_x_m = float(state.get("start_x_m", ac.x_m))
            ac.x_m, ac.y_m, ac.heading_rad = self._move_along_lateral_profile(
                ac.x_m,
                travel_m,
                start_x_m,
                transition_m,
                offset_m,
                False,
            )
            prog = (ac.x_m - start_x_m) / transition_m
            if prog >= 1.0 - 1e-9:
                ac.action_phase = "offset_cruise"
                ac.heading_rad = 0.0
                ac.y_m = offset_m
            return

        if ac.action_phase == "offset_cruise":
            ac.x_m += travel_m
            ac.y_m = offset_m
            ac.heading_rad = 0.0
            if self._has_completed_corridor_overtake(ac) and self._can_start_corridor_merge(ac, transition_m):
                ac.action_phase = "offset_in"
                state["merge_start_x_m"] = float(ac.x_m)
            return

        merge_start_x_m = float(state.get("merge_start_x_m", ac.x_m))
        ac.x_m, ac.y_m, ac.heading_rad = self._move_along_lateral_profile(
            ac.x_m,
            travel_m,
            merge_start_x_m,
            transition_m,
            offset_m,
            True,
        )
        prog = (ac.x_m - merge_start_x_m) / transition_m
        if prog >= 1.0 - 1e-9:
            ac.y_m = 0.0
            ac.heading_rad = 0.0
            ac.action = None
            ac.action_phase = "idle"
            ac.action_state = {}

    def _update_route_overtake_action(self, ac: Aircraft, dt: float):
        geometry = ac.route_geometry
        if geometry is None:
            ac.action = None
            ac.action_phase = "idle"
            ac.action_state = {}
            return

        state = ac.action_state
        offset_m = float(state.get("offset_m", 100.0))
        transition_m = max(float(state.get("transition_m", 300.0)), 1e-6)
        boost_cmd_knots = float(state.get("boost_cmd_knots", ac.v_cmd_knots))
        target_mps = self._clamp_command_knots(boost_cmd_knots) * KNOT_TO_MPS
        ac.v_act_mps = self._advance_speed_target(ac.v_act_mps, target_mps, dt)

        x_center, y_center, heading, _, _ = self._route_frame(geometry, ac.route_progress_m)
        wx_mps, wy_mps = self._wind_vector_mps(x_center, y_center, self.t_s)
        along_wind_mps = wx_mps * math.cos(heading) + wy_mps * math.sin(heading)
        path_ground_mps = max(0.0, ac.v_act_mps + along_wind_mps)
        offset_value = 0.0
        offset_slope = 0.0

        if ac.action_phase == "offset_out":
            start_progress_m = float(state.get("start_progress_m", ac.route_progress_m))
            _, _, current_slope = self._route_overtake_profile(
                ac.route_progress_m,
                start_progress_m,
                transition_m,
                offset_m,
                False,
            )
            progress_step_m = (path_ground_mps / max(math.sqrt(1.0 + current_slope * current_slope), 1e-6)) * dt
            new_progress = min(geometry.total_length_m, ac.route_progress_m + progress_step_m)
            prog, offset_value, offset_slope = self._route_overtake_profile(
                new_progress,
                start_progress_m,
                transition_m,
                offset_m,
                False,
            )
            if prog >= 1.0 - 1e-9:
                ac.action_phase = "offset_cruise"
                offset_value = offset_m
                offset_slope = 0.0

        elif ac.action_phase == "offset_cruise":
            new_progress = min(geometry.total_length_m, ac.route_progress_m + path_ground_mps * dt)
            offset_value = offset_m
            if self._has_completed_route_overtake(ac) and self._can_start_route_merge(ac, transition_m):
                ac.action_phase = "offset_in"
                state["merge_start_progress_m"] = float(new_progress)

        else:
            merge_start_progress_m = float(state.get("merge_start_progress_m", ac.route_progress_m))
            _, _, current_slope = self._route_overtake_profile(
                ac.route_progress_m,
                merge_start_progress_m,
                transition_m,
                offset_m,
                True,
            )
            progress_step_m = (path_ground_mps / max(math.sqrt(1.0 + current_slope * current_slope), 1e-6)) * dt
            new_progress = min(geometry.total_length_m, ac.route_progress_m + progress_step_m)
            prog, offset_value, offset_slope = self._route_overtake_profile(
                new_progress,
                merge_start_progress_m,
                transition_m,
                offset_m,
                True,
            )
            if prog >= 1.0 - 1e-9:
                offset_value = 0.0
                offset_slope = 0.0
                ac.action = None
                ac.action_phase = "idle"
                ac.action_state = {}

        self._set_route_offset_state(ac, new_progress, offset_value, offset_slope, path_ground_mps)

    def _step_route_action_aircraft(self, ac: Aircraft, dt: float):
        prev_x = float(ac.x_m)
        prev_y = float(ac.y_m)

        if ac.action == "turn":
            self._update_turn_action(ac, dt)
            wx_mps, wy_mps = self._wind_vector_mps(ac.x_m, ac.y_m, self.t_s)
            ac.wind_x_mps = float(wx_mps)
            ac.wind_y_mps = float(wy_mps)
            ac.ground_vx_mps = float((ac.x_m - prev_x) / max(dt, 1e-6))
            ac.ground_vy_mps = float((ac.y_m - prev_y) / max(dt, 1e-6))
        elif ac.action == "overtake":
            self._update_route_overtake_action(ac, dt)
        else:
            ac.action = None
            ac.action_phase = "idle"
            ac.action_state = {}
            return

        if ac.route_geometry is not None and ac.route_progress_m >= ac.route_geometry.total_length_m - 1e-6:
            ac.active_link_id = None
            ac.wait_reason = None
        else:
            route_state = self._route_link_state(ac)
            ac.active_link_id = str(route_state["link_id"]) if route_state and route_state["link_id"] else None
            ac.wait_reason = None

    def _step_action_aircraft(self, ac: Aircraft, dt: float):
        if ac.action == "turn":
            self._update_turn_action(ac, dt)
        elif ac.action == "overtake":
            self._update_overtake_action(ac, dt)
        else:
            ac.action = None
            ac.action_phase = "idle"
            ac.action_state = {}
        self._apply_managed_wind(ac, dt)

    def _route_link_state(self, ac: Aircraft) -> Optional[dict]:
        geometry = ac.route_geometry
        if geometry is None or len(geometry.node_progress_m) < 2:
            return None

        idx = geometry.active_link_index(ac.route_progress_m)
        start_s = geometry.node_progress_m[idx]
        end_s = geometry.node_progress_m[idx + 1]
        local_s = max(0.0, min(end_s - start_s, ac.route_progress_m - start_s))
        return {
            "index": idx,
            "start_s": start_s,
            "end_s": end_s,
            "length_m": max(0.0, end_s - start_s),
            "local_s": local_s,
            "link_id": geometry.link_ids[idx] if idx < len(geometry.link_ids) else None,
            "entry_node_id": geometry.node_ids[idx],
            "exit_node_id": geometry.node_ids[idx + 1],
            "next_link_id": geometry.link_ids[idx + 1] if idx + 1 < len(geometry.link_ids) else None,
        }

    def _collect_route_link_occupancy(self) -> Dict[str, List[float]]:
        occupancy: Dict[str, List[float]] = {}
        for ac in self.aircraft:
            if not ac.route_mode or ac.route_geometry is None:
                continue
            state = self._route_link_state(ac)
            if not state or not state["link_id"]:
                continue
            occupancy.setdefault(state["link_id"], []).append(float(state["local_s"]))
        for positions in occupancy.values():
            positions.sort()
        return occupancy

    def _route_bounds(self) -> Tuple[float, float]:
        if not self.route_nodes:
            gap = max(self.p.route_row_gap_m, 400.0)
            return -gap, gap
        ys = [node.y_m for node in self.route_nodes.values()]
        pad = max(self.p.route_row_gap_m * 0.8, 400.0)
        return min(ys) - pad, max(ys) + pad

    def _step_route_aircraft(self, dt: float):
        route_aircraft = [
            ac for ac in self.aircraft
            if ac.route_mode and ac.route_geometry is not None and ac.action is None
        ]
        if not route_aircraft:
            return

        self._cleanup_route_node_requests()
        initial_occupancy = self._collect_route_link_occupancy()
        post_occupancy: Dict[str, List[float]] = {}
        queue_service_gap_s = (
            self.p.sep_min_m * self.p.fifo_queue_sep_scale
        ) / max(self.p.v_free_knots * KNOT_TO_MPS, 1e-6)
        node_clearance_m = max(
            self.p.fifo_node_clearance_min_m,
            self.p.fifo_node_clearance_scale * self.p.sep_min_m,
        )
        node_headway_s = node_clearance_m / max(self.p.v_free_knots * KNOT_TO_MPS, 1e-6)
        link_groups: Dict[str, List[Tuple[Aircraft, dict]]] = {}

        for ac in route_aircraft:
            link_state = self._route_link_state(ac)
            if not link_state or not link_state["link_id"]:
                continue
            link_groups.setdefault(str(link_state["link_id"]), []).append((ac, link_state))

        for link_id_value, group in link_groups.items():
            group.sort(key=lambda item: (-float(item[1]["local_s"]), item[0].id))
            lead_final_local = math.inf
            lead_initial_local = math.inf

            for ac, link_state in group:
                geometry = ac.route_geometry
                assert geometry is not None

                prev_progress = float(ac.route_progress_m)
                x_prev, y_prev, heading_prev = geometry.sample(ac.route_progress_m)
                wx_mps, wy_mps = self._wind_vector_mps(x_prev, y_prev, self.t_s)
                along_wind_mps = wx_mps * math.cos(heading_prev) + wy_mps * math.sin(heading_prev)
                target_air_mps = self._clamp_command_knots(ac.v_cmd_knots) * KNOT_TO_MPS
                ac.v_act_mps = self._advance_speed_target(ac.v_act_mps, target_air_mps, dt)
                ground_mps = max(0.0, ac.v_act_mps + along_wind_mps)
                current_ground_mps = max(0.0, math.hypot(ac.ground_vx_mps, ac.ground_vy_mps))
                proposed_local = float(link_state["local_s"]) + ground_mps * dt
                allowed_local = proposed_local
                wait_reason: Optional[str] = None
                exit_node_id = str(link_state["exit_node_id"])
                crossed_exit = False

                if math.isfinite(lead_final_local):
                    current_gap_local = max(0.0, lead_initial_local - float(link_state["local_s"]))
                    target_gap_local = self._target_follow_gap_m(current_gap_local, dt)
                    preserve_gap_local = current_gap_local
                    braking_floor_local = float(link_state["local_s"]) + max(0.0, current_ground_mps - self.p.b_max_mps2 * dt) * dt
                    braking_floor_local = min(braking_floor_local, lead_final_local - preserve_gap_local)
                    allowed_local = min(allowed_local, max(lead_final_local - target_gap_local, braking_floor_local))
                    if allowed_local < proposed_local - 1e-9:
                        wait_reason = "spacing"

                if not ac.has_departed:
                    start_release = self.node_release_t_s.get(str(link_state["entry_node_id"]), 0.0)
                    if self.t_s < start_release - 1e-9:
                        allowed_local = min(allowed_local, 0.0)
                        wait_reason = "start_hold"

                link_length = float(link_state["length_m"])
                hold_buffer_m = max(
                    self.p.fifo_hold_buffer_min_m,
                    self.p.fifo_hold_buffer_scale * self.p.sep_min_m,
                )
                hold_local = max(0.0, link_length - hold_buffer_m)
                remaining_to_node_m = max(0.0, link_length - float(link_state["local_s"]))
                approach_window_m = max(
                    self.p.sep_min_m * self.p.fifo_approach_sep_scale,
                    (max(current_ground_mps, ground_mps) ** 2) / max(2.0 * self.p.b_max_mps2, 1e-6)
                    + hold_buffer_m
                    + max(current_ground_mps, ground_mps) * self.p.fifo_approach_time_s,
                )
                if remaining_to_node_m <= approach_window_m + 1e-9 or allowed_local > link_length + 1e-9:
                    request_dt_s = max(
                        0.0,
                        remaining_to_node_m / max(max(ground_mps, current_ground_mps), 1e-6),
                    )
                    self._register_route_node_request(exit_node_id, ac.id, self.t_s + request_dt_s)

                    queue_head_id = self._peek_route_node_request(exit_node_id)
                    node_release = self.node_release_t_s.get(exit_node_id, 0.0)
                    merge_release_extra_s = 0.0
                    blocked_reason: Optional[str] = None
                    if queue_head_id != ac.id:
                        blocked_reason = "fifo_hold"
                    elif self.t_s < node_release - 1e-9:
                        blocked_reason = "node_hold"
                    else:
                        next_link_id = link_state["next_link_id"]
                        if next_link_id:
                            current_positions = initial_occupancy.get(str(next_link_id), [])
                            future_positions = post_occupancy.get(str(next_link_id), [])
                            nearest = min(current_positions + future_positions) if (current_positions or future_positions) else math.inf
                            if nearest < self.p.sep_min_m - 1e-9:
                                blocked_reason = "merge_hold"
                                merge_release_extra_s = max(
                                    0.0,
                                    (self.p.sep_min_m - nearest) / max(self.p.v_free_knots * KNOT_TO_MPS, 1e-6),
                                )

                    if blocked_reason is not None:
                        queue_rank = self._route_node_request_rank(exit_node_id, ac.id) or 0
                        scheduled_service_dt_s = max(
                            dt,
                            max(0.0, node_release - self.t_s) + queue_rank * max(node_headway_s, queue_service_gap_s),
                        )
                        if blocked_reason == "merge_hold":
                            scheduled_service_dt_s += node_headway_s + merge_release_extra_s

                        approach_local = max(
                            float(link_state["local_s"]),
                            link_length - 1.0,
                        )
                        remaining_hold_m = max(0.0, approach_local - float(link_state["local_s"]))
                        sync_target_mps = remaining_hold_m / max(scheduled_service_dt_s, 1e-6)
                        stop_target_mps = math.sqrt(
                            max(0.0, 2.0 * max(self.p.b_max_mps2, 1e-6) * remaining_hold_m)
                        )
                        target_ground_mps = min(stop_target_mps, sync_target_mps)
                        hold_limit = min(
                            approach_local,
                            float(link_state["local_s"]) + self._advance_speed_target(
                                current_ground_mps,
                                target_ground_mps,
                                dt,
                            ) * dt,
                        )
                        allowed_local = min(
                            allowed_local,
                            hold_limit,
                        )
                        if allowed_local < proposed_local - 1e-9:
                            wait_reason = blocked_reason
                    elif allowed_local > link_length + 1e-9:
                        next_link_id = link_state["next_link_id"]
                        if next_link_id:
                            crossed_exit = True
                            self.node_release_t_s[exit_node_id] = max(
                                self.node_release_t_s.get(exit_node_id, 0.0),
                                self.t_s + node_headway_s,
                            )
                        else:
                            crossed_exit = True
                            self.node_release_t_s[exit_node_id] = max(
                                self.node_release_t_s.get(exit_node_id, 0.0),
                                self.t_s + node_headway_s,
                            )

                final_local = max(0.0, allowed_local)
                new_progress = float(link_state["start_s"]) + final_local
                if not ac.has_departed and new_progress > 1.0:
                    ac.has_departed = True
                    ac.depart_t_s = self.t_s
                    self.node_release_t_s[str(link_state["entry_node_id"])] = max(
                        self.node_release_t_s.get(str(link_state["entry_node_id"]), 0.0),
                        self.t_s + node_headway_s,
                    )

                ac.route_progress_m = min(new_progress, geometry.total_length_m)
                x_new, y_new, heading_new = geometry.sample(ac.route_progress_m)
                wx_new_mps, wy_new_mps = self._wind_vector_mps(x_new, y_new, self.t_s)
                ac.x_m = float(x_new)
                ac.y_m = float(y_new)
                ac.heading_rad = float(heading_new)
                ac.wind_x_mps = float(wx_new_mps)
                ac.wind_y_mps = float(wy_new_mps)
                distance_m = max(0.0, ac.route_progress_m - prev_progress)
                ac.ground_vx_mps = math.cos(heading_new) * (distance_m / max(dt, 1e-6))
                ac.ground_vy_mps = math.sin(heading_new) * (distance_m / max(dt, 1e-6))
                ac.wait_reason = wait_reason
                if crossed_exit:
                    self._clear_route_node_request(exit_node_id, ac.id)
                if ac.route_progress_m >= geometry.total_length_m - 1e-6:
                    ac.active_link_id = None
                    ac.wait_reason = None
                    lead_final_local = math.inf
                    continue

                post_state = self._route_link_state(ac)
                if post_state and post_state["link_id"]:
                    ac.active_link_id = str(post_state["link_id"])
                    post_occupancy.setdefault(str(post_state["link_id"]), []).append(float(post_state["local_s"]))
                    post_occupancy[str(post_state["link_id"])].sort()
                    if str(post_state["link_id"]) == link_id_value:
                        lead_final_local = float(post_state["local_s"])
                    else:
                        lead_final_local = link_length + float(post_state["local_s"])
                else:
                    ac.active_link_id = None
                    ac.wait_reason = None
                    lead_final_local = math.inf
                lead_initial_local = float(link_state["local_s"])

    def step(self):
        self.normalize_model_params()
        dt = self.p.dt_s
        self.t_s += dt

        if not self.aircraft:
            return

        if self._is_route_mode():
            self._step_route_aircraft(dt)
            for ac in [item for item in self.aircraft if item.route_mode and item.route_geometry is not None and item.action is not None]:
                self._step_route_action_aircraft(ac, dt)
            self.aircraft = [
                ac for ac in self.aircraft
                if (not ac.route_mode) or ac.route_progress_m < max(ac.route_total_m - 1e-6, 0.0)
            ]
            v_free_mps = self.p.v_free_knots * KNOT_TO_MPS
            for ac in self.aircraft:
                progress_mps = math.hypot(ac.ground_vx_mps, ac.ground_vy_mps)
                l = max(0.0, 1.0 - (progress_mps / max(v_free_mps, 1e-9)))
                ac.update_delay_window(self.t_s, l, dt, self.p.delay_window_T_s)
            return

        corridor_aircraft = [ac for ac in self.aircraft if ac.action is None]
        managed_aircraft = [ac for ac in self.aircraft if ac.action is not None]

        self._step_corridor_aircraft(corridor_aircraft, dt)
        for ac in managed_aircraft:
            self._step_action_aircraft(ac, dt)

        L = self.p.path_length_m
        self.aircraft = [ac for ac in self.aircraft if ac.x_m <= L + 100.0]

        v_free_mps = self.p.v_free_knots * KNOT_TO_MPS
        for ac in self.aircraft:
            progress_mps = max(0.0, ac.ground_vx_mps)
            l = max(0.0, 1.0 - (progress_mps / max(v_free_mps, 1e-9)))
            ac.update_delay_window(self.t_s, l, dt, self.p.delay_window_T_s)

    def _empty_metrics(self) -> Dict[str, np.ndarray]:
        return {
            "id": np.array([], dtype=int),
            "x": np.array([], dtype=float),
            "y": np.array([], dtype=float),
            "remaining_m": np.array([], dtype=float),
            "v_act_knots": np.array([], dtype=float),
            "v_ground_knots": np.array([], dtype=float),
            "v_cmd_knots": np.array([], dtype=float),
            "wind_x_knots": np.array([], dtype=float),
            "wind_y_knots": np.array([], dtype=float),
            "wind_mag_knots": np.array([], dtype=float),
            "include_in_flow": np.array([], dtype=bool),
            "spawn_t_s": np.array([], dtype=float),
            "std_s": np.array([], dtype=float),
            "sta_sched_s": np.array([], dtype=float),
            "sta_s": np.array([], dtype=float),
            "eta_s": np.array([], dtype=float),
            "tti": np.array([], dtype=float),
            "flight_time_s": np.array([], dtype=float),
            "battery_remaining_s": np.array([], dtype=float),
            "battery_pct": np.array([], dtype=float),
            "l": np.array([], dtype=float),
            "D": np.array([], dtype=float),
            "rho": np.array([], dtype=float),
            "R": np.array([], dtype=float),
            "c": np.array([], dtype=float),
        }

    def _compute_route_metrics(self) -> Dict[str, np.ndarray]:
        N = len(self.aircraft)
        if N == 0:
            return self._empty_metrics()

        ids = np.array([ac.id for ac in self.aircraft], dtype=int)
        x = np.array([ac.x_m for ac in self.aircraft], dtype=float)
        y = np.array([ac.y_m for ac in self.aircraft], dtype=float)
        remaining_m = np.array([max(0.0, ac.route_total_m - ac.route_progress_m) for ac in self.aircraft], dtype=float)
        wind_x_mps = np.array([ac.wind_x_mps for ac in self.aircraft], dtype=float)
        wind_y_mps = np.array([ac.wind_y_mps for ac in self.aircraft], dtype=float)
        ground_vx_mps = np.array([ac.ground_vx_mps for ac in self.aircraft], dtype=float)
        ground_vy_mps = np.array([ac.ground_vy_mps for ac in self.aircraft], dtype=float)
        v_ground_knots = np.hypot(ground_vx_mps, ground_vy_mps) * MPS_TO_KNOT
        v_act_knots = v_ground_knots.copy()
        v_cmd_knots = np.array([ac.v_cmd_knots for ac in self.aircraft], dtype=float)
        include_in_flow = np.array([ac.action is None for ac in self.aircraft], dtype=bool)
        spawn_t_s = np.array([ac.spawn_t_s for ac in self.aircraft], dtype=float)
        std_s = np.array([ac.std_s for ac in self.aircraft], dtype=float)
        sta_sched_s = np.array([ac.sta_s for ac in self.aircraft], dtype=float)
        flight_time_s = np.array([self._get_flight_time_s(ac) for ac in self.aircraft], dtype=float)
        battery_remaining_s = np.maximum(0.0, BATTERY_ENDURANCE_S - flight_time_s)
        battery_pct = clip01(battery_remaining_s / BATTERY_ENDURANCE_S) * 100.0

        eta_remaining_s = np.array([
            self._estimate_route_eta_remaining_s(ac)
            for ac in self.aircraft
        ], dtype=float)
        eta_s = self.t_s + eta_remaining_s
        sched_total_s = np.maximum(0.0, sta_sched_s - std_s)
        est_total_s = np.maximum(0.0, eta_s - std_s)
        tti = np.where(sched_total_s > 1e-9, est_total_s / sched_total_s, 1.0)

        v_free = self.p.v_free_knots
        l = np.maximum(0.0, 1.0 - (v_ground_knots / max(v_free, 1e-9)))
        D = np.array([ac.D_s for ac in self.aircraft], dtype=float)
        rho = np.zeros_like(x, dtype=float)
        R = np.zeros_like(x, dtype=float)
        c = np.zeros_like(x, dtype=float)

        sig = max(self.p.sigma_parallel_m, 1e-6)
        dx = x.reshape(-1, 1) - x.reshape(1, -1)
        dy = y.reshape(-1, 1) - y.reshape(1, -1)
        rho = np.sum(np.exp(-0.5 * ((dx / sig) ** 2 + (dy / max(self.p.sigma_perp_m, 1e-6)) ** 2)), axis=1) - 1.0

        delayed = (D >= self.p.delayed_thr_s).astype(float)
        route_states = [self._route_link_state(ac) for ac in self.aircraft]
        route_links = [state["link_id"] if state else None for state in route_states]
        route_local_s = [float(state["local_s"]) if state else 0.0 for state in route_states]
        route_indices = [int(state["index"]) if state else 0 for state in route_states]
        remaining_link_sets = [set(ac.route_link_ids[idx:]) for ac, idx in zip(self.aircraft, route_indices)]

        for i, ac in enumerate(self.aircraft):
            current_link = route_links[i]
            current_local_s = route_local_s[i]
            remaining_links = remaining_link_sets[i]
            delayed_ahead = []
            for j, other in enumerate(self.aircraft):
                if j == i:
                    continue
                other_link = route_links[j]
                other_remaining_links = remaining_link_sets[j]
                if not (remaining_links & other_remaining_links):
                    continue
                if current_link == other_link and current_link is not None:
                    if route_local_s[j] <= current_local_s:
                        continue
                    route_gap = route_local_s[j] - current_local_s
                else:
                    route_gap = math.hypot(other.x_m - ac.x_m, other.y_m - ac.y_m)
                if route_gap <= self.p.lookahead_L_m:
                    delayed_ahead.append(delayed[j])
            R[i] = float(np.mean(delayed_ahead)) if delayed_ahead else 0.0

        rho_hat = np.minimum(1.0, rho / max(self.p.rho_ref, 1e-9))
        D_avg = D / max(self.p.delay_window_T_s, 1e-9)
        A = np.maximum(D_avg, R)
        c = rho_hat * A

        return {
            "id": ids,
            "x": x,
            "y": y,
            "remaining_m": remaining_m,
            "v_act_knots": v_act_knots,
            "v_ground_knots": v_ground_knots,
            "v_cmd_knots": v_cmd_knots,
            "wind_x_knots": wind_x_mps * MPS_TO_KNOT,
            "wind_y_knots": wind_y_mps * MPS_TO_KNOT,
            "wind_mag_knots": np.hypot(wind_x_mps, wind_y_mps) * MPS_TO_KNOT,
            "include_in_flow": include_in_flow,
            "spawn_t_s": spawn_t_s,
            "std_s": std_s,
            "sta_sched_s": sta_sched_s,
            "sta_s": sta_sched_s,
            "eta_s": eta_s,
            "tti": tti,
            "flight_time_s": flight_time_s,
            "battery_remaining_s": battery_remaining_s,
            "battery_pct": battery_pct,
            "l": l,
            "D": D,
            "rho": rho,
            "R": R,
            "c": c,
        }

    def compute_metrics(self) -> Dict[str, np.ndarray]:
        if self._is_route_mode():
            return self._compute_route_metrics()

        N = len(self.aircraft)
        if N == 0:
            return self._empty_metrics()

        ids = np.array([ac.id for ac in self.aircraft], dtype=int)
        x = np.array([ac.x_m for ac in self.aircraft], dtype=float)
        y = np.array([ac.y_m for ac in self.aircraft], dtype=float)
        remaining_m = np.maximum(0.0, self.p.path_length_m - x)
        v_air_mps = np.array([ac.v_act_mps for ac in self.aircraft], dtype=float)
        wind_x_mps = np.array([ac.wind_x_mps for ac in self.aircraft], dtype=float)
        wind_y_mps = np.array([ac.wind_y_mps for ac in self.aircraft], dtype=float)
        ground_vx_mps = np.array([ac.ground_vx_mps for ac in self.aircraft], dtype=float)
        ground_vy_mps = np.array([ac.ground_vy_mps for ac in self.aircraft], dtype=float)
        v_act_knots = np.maximum(0.0, ground_vx_mps) * MPS_TO_KNOT
        v_ground_knots = np.hypot(ground_vx_mps, ground_vy_mps) * MPS_TO_KNOT
        v_cmd_knots = np.array([ac.v_cmd_knots for ac in self.aircraft], dtype=float)
        include_in_flow = np.array([ac.action is None for ac in self.aircraft], dtype=bool)
        spawn_t_s = np.array([ac.spawn_t_s for ac in self.aircraft], dtype=float)
        std_s = np.array([ac.std_s for ac in self.aircraft], dtype=float)
        sta_sched_s = np.array([ac.sta_s for ac in self.aircraft], dtype=float)
        flight_time_s = np.array([self._get_flight_time_s(ac) for ac in self.aircraft], dtype=float)
        battery_remaining_s = np.maximum(0.0, BATTERY_ENDURANCE_S - flight_time_s)
        battery_pct = clip01(battery_remaining_s / BATTERY_ENDURANCE_S) * 100.0
        eta_remaining_s = np.array([
            self._estimate_corridor_eta_remaining_s(ac)
            for ac in self.aircraft
        ], dtype=float)
        eta_s = self.t_s + eta_remaining_s
        sched_total_s = np.maximum(0.0, sta_sched_s - std_s)
        est_total_s = np.maximum(0.0, eta_s - std_s)
        tti = np.where(sched_total_s > 1e-9, est_total_s / sched_total_s, 1.0)

        v_free = self.p.v_free_knots
        l = np.maximum(0.0, 1.0 - (v_act_knots / max(v_free, 1e-9)))
        D = np.array([ac.D_s for ac in self.aircraft], dtype=float)
        rho = np.zeros_like(x, dtype=float)
        R = np.zeros_like(x, dtype=float)
        c = np.zeros_like(x, dtype=float)

        if np.any(include_in_flow):
            x_flow = x[include_in_flow]
            D_flow = D[include_in_flow]

            sig = max(self.p.sigma_parallel_m, 1e-6)
            dx = x_flow.reshape(-1, 1) - x_flow.reshape(1, -1)
            rho_flow = np.sum(np.exp(-(dx ** 2) / (2.0 * sig ** 2)), axis=1) - 1.0
            rho[include_in_flow] = rho_flow

            delayed_flow = (D_flow >= self.p.delayed_thr_s).astype(float)
            order = np.argsort(x_flow)
            x_sorted = x_flow[order]
            delayed_sorted = delayed_flow[order]
            prefix = np.cumsum(delayed_sorted)

            R_sorted = np.zeros_like(x_sorted, dtype=float)
            Llook = self.p.lookahead_L_m

            for k in range(len(x_sorted)):
                upper = np.searchsorted(x_sorted, x_sorted[k] + Llook, side="right")
                cnt = upper - (k + 1)
                if cnt <= 0:
                    R_sorted[k] = 0.0
                else:
                    s = prefix[upper - 1] - prefix[k]
                    R_sorted[k] = s / cnt

            R_flow = np.zeros_like(R_sorted)
            R_flow[order] = R_sorted
            R[include_in_flow] = R_flow

            rho_hat_flow = np.minimum(1.0, rho_flow / max(self.p.rho_ref, 1e-9))
            D_avg_flow = D_flow / max(self.p.delay_window_T_s, 1e-9)
            A_flow = np.maximum(D_avg_flow, R_flow)
            c[include_in_flow] = rho_hat_flow * A_flow

        return {
            "id": ids,
            "x": x,
            "y": y,
            "remaining_m": remaining_m,
            "v_act_knots": v_act_knots,
            "v_ground_knots": v_ground_knots,
            "v_cmd_knots": v_cmd_knots,
            "wind_x_knots": wind_x_mps * MPS_TO_KNOT,
            "wind_y_knots": wind_y_mps * MPS_TO_KNOT,
            "wind_mag_knots": np.hypot(wind_x_mps, wind_y_mps) * MPS_TO_KNOT,
            "include_in_flow": include_in_flow,
            "spawn_t_s": spawn_t_s,
            "std_s": std_s,
            "sta_sched_s": sta_sched_s,
            "sta_s": sta_sched_s,
            "eta_s": eta_s,
            "tti": tti,
            "flight_time_s": flight_time_s,
            "battery_remaining_s": battery_remaining_s,
            "battery_pct": battery_pct,
            "l": l,
            "D": D,
            "rho": rho,
            "R": R,
            "c": c,
        }

    def compute_heatmaps(self, metrics: Dict[str, np.ndarray],
                         want_density: bool, want_congestion: bool) -> Dict[str, any]:
        include_in_flow = metrics.get("include_in_flow")
        if include_in_flow is None:
            include_in_flow = np.ones_like(metrics["x"], dtype=bool)

        x = metrics["x"][include_in_flow]
        y = metrics["y"][include_in_flow]
        c = metrics["c"][include_in_flow]

        x_min = -self.p.spawn_margin_m
        x_max = self.p.path_length_m
        if self._is_route_mode():
            y_min, y_max = self._route_bounds()
        else:
            y_min = -self.p.lane_width_m / 2.0
            y_max = self.p.lane_width_m / 2.0

        xg = np.linspace(x_min, x_max, self.p.nx)
        yg = np.linspace(y_min, y_max, self.p.ny)

        out: Dict[str, any] = {"xg": xg.tolist(), "yg": yg.tolist()}

        if len(x) == 0:
            Z = np.zeros((self.p.ny, self.p.nx), dtype=float)
            if want_density:
                out["density"] = Z.tolist()
            if want_congestion:
                out["congestion"] = Z.tolist()
            return out

        hx = max(self.p.sigma_parallel_m, 1e-6)
        hy = max(self.p.sigma_perp_m, 1e-6)

        Xg, Yg = np.meshgrid(xg, yg)
        dx_grid = Xg[None, :, :] - x[:, None, None]
        dy_grid = Yg[None, :, :] - y[:, None, None]
        W = np.exp(-0.5 * ((dx_grid / hx) ** 2 + (dy_grid / hy) ** 2))

        dens = np.sum(W, axis=0)

        if want_density:
            ref = max(self.p.rho_ref, 1e-9)
            out["density"] = np.clip(dens / ref, 0.0, 1.0).tolist()

        if want_congestion:
            cong = np.sum(c[:, None, None] * W, axis=0)
            ref = max(self.p.cong_ref, 1e-9)
            out["congestion"] = np.clip(cong / ref, 0.0, 1.0).tolist()

        return out

    def compute_route_link_congestion(self, metrics: Dict[str, np.ndarray]) -> List[dict]:
        levels: List[dict] = []
        if not self.route_links:
            return levels

        link_members: Dict[str, List[int]] = {link_key: [] for link_key in self.route_links}
        for idx, ac in enumerate(self.aircraft):
            state = self._route_link_state(ac)
            if state and state["link_id"]:
                link_members[str(state["link_id"])].append(idx)

        thresholds = [0.0, (1.0 / 0.90) - 1.0, (1.0 / 0.625) - 1.0, (1.0 / 0.35) - 1.0]
        v_free = max(self.p.v_free_knots, 1e-6)
        w_over = max(self.p.seg_w_overflow, 0.0)
        w_tti = max(self.p.seg_w_tti, 0.0)
        w_sum = max(w_over + w_tti, 1e-9)
        w_over /= w_sum
        w_tti /= w_sum

        for link_key, link in self.route_links.items():
            members = link_members.get(link_key, [])
            count = len(members)
            speeds = metrics["v_act_knots"][members] if count else np.array([], dtype=float)
            v_mean = float(np.mean(speeds)) if count else float(v_free)
            capacity = max(1.0, link.length_m / max(self.p.sep_min_m, 1e-6))
            occ = count / capacity
            overflow = max(0.0, occ - 1.0)
            tti = v_free / max(v_mean, 1e-6)
            score = w_over * overflow + w_tti * max(0.0, tti - 1.0)

            if score < thresholds[1]:
                level = 0
            elif score < thresholds[2]:
                level = 1
            elif score < thresholds[3]:
                level = 2
            else:
                level = 3

            levels.append({
                "id": link_key,
                "start_id": link.start_id,
                "end_id": link.end_id,
                "score": float(score),
                "level": int(level),
                "count": int(count),
                "v_mean": float(v_mean),
            })

        return levels

    def compute_segment_congestion(self, metrics: Dict[str, np.ndarray]) -> List[dict]:
        if self._is_route_mode():
            return self.compute_route_link_congestion(metrics)

        include_in_flow = metrics.get("include_in_flow")
        if include_in_flow is None:
            include_in_flow = np.ones_like(metrics["x"], dtype=bool)

        x = metrics["x"][include_in_flow]
        v_act = metrics["v_act_knots"][include_in_flow]
        x_min = -self.p.spawn_margin_m
        x_max = self.p.path_length_m
        seg_len = max(self.p.segment_length_m, 1e-6)
        nseg = int(math.ceil((x_max - x_min) / seg_len))
        nseg = max(1, nseg)

        counts = np.zeros(nseg, dtype=float)
        v_sum = np.zeros(nseg, dtype=float)

        for xi, vi in zip(x, v_act):
            idx = int((xi - x_min) // seg_len)
            if 0 <= idx < nseg:
                counts[idx] += 1.0
                v_sum[idx] += vi

        v_free = max(self.p.v_free_knots, 1e-6)
        v_mean = np.where(counts > 0.0, v_sum / np.maximum(counts, 1e-6), v_free)

        capacity = seg_len / max(self.p.sep_min_m, 1e-6)
        occ = counts / max(capacity, 1e-6)
        overflow = np.maximum(0.0, occ - 1.0)
        tti = v_free / np.maximum(v_mean, 1e-6)
        tti_excess = np.maximum(0.0, tti - 1.0)

        w_over = max(self.p.seg_w_overflow, 0.0)
        w_tti = max(self.p.seg_w_tti, 0.0)
        w_sum = max(w_over + w_tti, 1e-9)
        w_over /= w_sum
        w_tti /= w_sum

        seg_score = w_over * overflow + w_tti * tti_excess

        # Color thresholds (from TomTom bands)
        thresholds = [0.0, (1.0 / 0.90) - 1.0, (1.0 / 0.625) - 1.0, (1.0 / 0.35) - 1.0]

        segments = []
        for i in range(nseg):
            s = float(seg_score[i])
            if s < thresholds[1]:
                level = 0  # green
            elif s < thresholds[2]:
                level = 1  # yellow
            elif s < thresholds[3]:
                level = 2  # orange
            else:
                level = 3  # red

            segments.append({
                "x_start": float(x_min + i * seg_len),
                "x_end": float(x_min + (i + 1) * seg_len),
                "score": s,
                "level": level,
                "count": int(counts[i]),
                "v_mean": float(v_mean[i]),
            })

        return segments

    def compute_summary(self, metrics: Dict[str, np.ndarray]) -> dict:
        N = len(metrics["x"])
        if N == 0:
            return {"N": 0, "DR": 0, "TD_min": 0}

        D = metrics["D"]
        DR = float(np.mean(D >= self.p.delayed_thr_s))
        TD = float(np.sum(D))

        return {
            "N": N,
            "DR": round(DR, 3),
            "TD_min": round(TD / 60, 2),
        }

    def sample_wind_field(self) -> List[dict]:
        if not self.p.wind_enabled:
            return []

        if self._is_route_mode():
            y_min, y_max = self._route_bounds()
        else:
            y_half = max(self.p.lane_width_m * 4.0, 1200.0)
            y_min, y_max = -y_half, y_half
        x_samples = np.linspace(0.0, self.p.path_length_m, 13)
        y_samples = np.linspace(y_min, y_max, 7)
        samples: List[dict] = []

        for yi in y_samples:
            for xi in x_samples:
                wx_mps, wy_mps = self._wind_vector_mps(float(xi), float(yi), self.t_s)
                samples.append({
                    "x": float(xi),
                    "y": float(yi),
                    "u_knots": float(wx_mps * MPS_TO_KNOT),
                    "v_knots": float(wy_mps * MPS_TO_KNOT),
                    "mag_knots": float(math.hypot(wx_mps, wy_mps) * MPS_TO_KNOT),
                })

        return samples

    def get_wind_state(self) -> dict:
        cfg = self._get_wind_profile()
        center_x = 0.5 * self.p.path_length_m
        wx_mps, wy_mps = self._wind_vector_mps(center_x, 0.0, self.t_s)
        prevailing_mag_knots = math.hypot(wx_mps, wy_mps) * MPS_TO_KNOT
        prevailing_dir_deg = (math.degrees(math.atan2(wy_mps, wx_mps)) + 360.0) % 360.0 if prevailing_mag_knots > 1e-9 else 0.0
        return {
            "enabled": bool(self.p.wind_enabled),
            "level": cfg["label"],
            "display_label": {
                "normal": "보통 (Normal)",
                "middle": "중간 (Middle)",
                "serious": "심각 (Serious)",
            }.get(cfg["label"], cfg["label"]),
            "prevailing_mag_knots": round(prevailing_mag_knots, 1),
            "prevailing_dir_deg": round(prevailing_dir_deg, 1),
            "samples": self.sample_wind_field(),
            "bands": [
                {"level": "normal", "label": "Normal", "max_knots": 15},
                {"level": "middle", "label": "Middle", "max_knots": 30},
                {"level": "serious", "label": "Serious", "max_knots": 45},
            ],
        }

    def get_route_network_state(self, link_metrics: Optional[List[dict]] = None) -> dict:
        metrics_by_id = {item["id"]: item for item in (link_metrics or [])}
        starts = []
        for node in self._route_start_nodes():
            reachable_ids = self._reachable_route_end_nodes(node.id)
            starts.append({
                **node.to_dict(),
                "reachable_end_ids": reachable_ids,
                "spawn_enabled": bool(reachable_ids),
            })

        links = []
        for link in self.route_links.values():
            metric = metrics_by_id.get(link.id, {})
            links.append({
                **link.to_dict(),
                "score": float(metric.get("score", 0.0)),
                "level": int(metric.get("level", 0)),
                "count": int(metric.get("count", 0)),
                "v_mean": float(metric.get("v_mean", self.p.v_free_knots)),
            })

        return {
            "nodes": [node.to_dict() for node in sorted(self.route_nodes.values(), key=lambda item: (item.col, item.row))],
            "links": links,
            "paths": list(self.route_preview_paths),
            "start_nodes": starts,
            "grid_spacing_m": self.p.route_grid_spacing_m,
            "row_gap_m": self.p.route_row_gap_m,
            "row_count": self.p.route_row_count,
        }

    def _compute_flow_spacing_context(self, route_states: List[Optional[dict]],
                                      metrics: Dict[str, np.ndarray]) -> List[Dict[str, Any]]:
        context: List[Dict[str, Any]] = []
        for ac in self.aircraft:
            context.append({
                "flow_reference": "same_active_link" if ac.route_mode else "same_corridor_track",
                "forward_flow_aircraft_id": None,
                "forward_flow_gap_m": None,
                "forward_flow_distance_m": None,
                "forward_flow_relative_speed_knots": None,
                "forward_sep_margin_m": None,
                "rear_flow_aircraft_id": None,
                "rear_flow_gap_m": None,
                "rear_flow_distance_m": None,
                "rear_flow_relative_speed_knots": None,
                "rear_sep_margin_m": None,
            })

        if self._is_route_mode():
            link_groups: Dict[str, List[Tuple[int, float]]] = {}
            for idx, state in enumerate(route_states):
                if not state or not state.get("link_id"):
                    continue
                link_groups.setdefault(str(state["link_id"]), []).append((idx, float(state["local_s"])))
            for group in link_groups.values():
                group.sort(key=lambda item: (item[1], self.aircraft[item[0]].id))
                for pos, (idx, local_s) in enumerate(group):
                    own = context[idx]
                    if pos + 1 < len(group):
                        j, next_local_s = group[pos + 1]
                        dist = max(0.0, next_local_s - local_s)
                        own["forward_flow_aircraft_id"] = int(self.aircraft[j].id)
                        own["forward_flow_gap_m"] = round(dist, 1)
                        own["forward_flow_distance_m"] = round(
                            math.hypot(self.aircraft[j].x_m - self.aircraft[idx].x_m,
                                       self.aircraft[j].y_m - self.aircraft[idx].y_m), 1
                        )
                        own["forward_flow_relative_speed_knots"] = round(
                            float(metrics["v_ground_knots"][j] - metrics["v_ground_knots"][idx]), 3
                        )
                        own["forward_sep_margin_m"] = round(dist - float(self.p.sep_min_m), 1)
                    if pos > 0:
                        j, prev_local_s = group[pos - 1]
                        dist = max(0.0, local_s - prev_local_s)
                        own["rear_flow_aircraft_id"] = int(self.aircraft[j].id)
                        own["rear_flow_gap_m"] = round(dist, 1)
                        own["rear_flow_distance_m"] = round(
                            math.hypot(self.aircraft[j].x_m - self.aircraft[idx].x_m,
                                       self.aircraft[j].y_m - self.aircraft[idx].y_m), 1
                        )
                        own["rear_flow_relative_speed_knots"] = round(
                            float(metrics["v_ground_knots"][j] - metrics["v_ground_knots"][idx]), 3
                        )
                        own["rear_sep_margin_m"] = round(dist - float(self.p.sep_min_m), 1)
            return context

        corridor_group = [
            (idx, float(ac.x_m))
            for idx, ac in enumerate(self.aircraft)
            if not ac.route_mode
        ]
        corridor_group.sort(key=lambda item: (item[1], self.aircraft[item[0]].id))
        for pos, (idx, x_pos) in enumerate(corridor_group):
            own = context[idx]
            if pos + 1 < len(corridor_group):
                j, x_next = corridor_group[pos + 1]
                dist = max(0.0, x_next - x_pos)
                own["forward_flow_aircraft_id"] = int(self.aircraft[j].id)
                own["forward_flow_gap_m"] = round(dist, 1)
                own["forward_flow_distance_m"] = round(
                    math.hypot(self.aircraft[j].x_m - self.aircraft[idx].x_m,
                               self.aircraft[j].y_m - self.aircraft[idx].y_m), 1
                )
                own["forward_flow_relative_speed_knots"] = round(
                    float(metrics["v_ground_knots"][j] - metrics["v_ground_knots"][idx]), 3
                )
                own["forward_sep_margin_m"] = round(dist - float(self.p.sep_min_m), 1)
            if pos > 0:
                j, x_prev = corridor_group[pos - 1]
                dist = max(0.0, x_pos - x_prev)
                own["rear_flow_aircraft_id"] = int(self.aircraft[j].id)
                own["rear_flow_gap_m"] = round(dist, 1)
                own["rear_flow_distance_m"] = round(
                    math.hypot(self.aircraft[j].x_m - self.aircraft[idx].x_m,
                               self.aircraft[j].y_m - self.aircraft[idx].y_m), 1
                )
                own["rear_flow_relative_speed_knots"] = round(
                    float(metrics["v_ground_knots"][j] - metrics["v_ground_knots"][idx]), 3
                )
                own["rear_sep_margin_m"] = round(dist - float(self.p.sep_min_m), 1)
        return context

    def _compute_proximity_context(self, remaining_link_sets: List[set]) -> List[Dict[str, Any]]:
        context: List[Dict[str, Any]] = []
        for _ in self.aircraft:
            context.append({
                "nearest_aircraft_id": None,
                "nearest_aircraft_distance_m": None,
                "nearest_aircraft_sep_margin_m": None,
                "nearest_conflict_aircraft_id": None,
                "nearest_conflict_distance_m": None,
                "nearest_conflict_sep_margin_m": None,
                "shared_remaining_link_count": 0,
            })

        for i in range(len(self.aircraft)):
            for j in range(i + 1, len(self.aircraft)):
                ac_i = self.aircraft[i]
                ac_j = self.aircraft[j]
                if ac_i.route_mode != ac_j.route_mode:
                    continue
                dist = math.hypot(ac_j.x_m - ac_i.x_m, ac_j.y_m - ac_i.y_m)
                sep_margin = dist - float(self.p.sep_min_m)

                if context[i]["nearest_aircraft_distance_m"] is None or dist < context[i]["nearest_aircraft_distance_m"]:
                    context[i]["nearest_aircraft_id"] = int(ac_j.id)
                    context[i]["nearest_aircraft_distance_m"] = round(dist, 1)
                    context[i]["nearest_aircraft_sep_margin_m"] = round(sep_margin, 1)
                if context[j]["nearest_aircraft_distance_m"] is None or dist < context[j]["nearest_aircraft_distance_m"]:
                    context[j]["nearest_aircraft_id"] = int(ac_i.id)
                    context[j]["nearest_aircraft_distance_m"] = round(dist, 1)
                    context[j]["nearest_aircraft_sep_margin_m"] = round(sep_margin, 1)

                shared_link_count = 0
                is_conflict_pair = True
                if ac_i.route_mode:
                    shared_link_count = len(remaining_link_sets[i] & remaining_link_sets[j])
                    is_conflict_pair = shared_link_count > 0

                if is_conflict_pair:
                    if context[i]["nearest_conflict_distance_m"] is None or dist < context[i]["nearest_conflict_distance_m"]:
                        context[i]["nearest_conflict_aircraft_id"] = int(ac_j.id)
                        context[i]["nearest_conflict_distance_m"] = round(dist, 1)
                        context[i]["nearest_conflict_sep_margin_m"] = round(sep_margin, 1)
                        context[i]["shared_remaining_link_count"] = int(shared_link_count)
                    if context[j]["nearest_conflict_distance_m"] is None or dist < context[j]["nearest_conflict_distance_m"]:
                        context[j]["nearest_conflict_aircraft_id"] = int(ac_i.id)
                        context[j]["nearest_conflict_distance_m"] = round(dist, 1)
                        context[j]["nearest_conflict_sep_margin_m"] = round(sep_margin, 1)
                        context[j]["shared_remaining_link_count"] = int(shared_link_count)
        return context

    def _refresh_aircraft_data(self, metrics: Dict[str, np.ndarray], segment_contexts: List[dict]):
        if not self.aircraft:
            return

        route_states = [
            self._route_link_state(ac) if ac.route_mode and ac.route_geometry is not None else None
            for ac in self.aircraft
        ]
        remaining_link_sets = []
        for ac, state in zip(self.aircraft, route_states):
            if not ac.route_mode:
                remaining_link_sets.append(set())
                continue
            idx = int(state["index"]) if state else 0
            remaining_link_sets.append(set(ac.route_link_ids[idx:]))

        flow_spacing = self._compute_flow_spacing_context(route_states, metrics)
        proximity = self._compute_proximity_context(remaining_link_sets)
        route_segment_metrics = {item["id"]: item for item in segment_contexts} if self._is_route_mode() else {}
        aircraft_index_by_id = {ac.id: idx for idx, ac in enumerate(self.aircraft)}
        route_link_locals: Dict[str, List[float]] = {}
        for state in route_states:
            if state and state.get("link_id"):
                route_link_locals.setdefault(str(state["link_id"]), []).append(float(state["local_s"]))
        for locals_list in route_link_locals.values():
            locals_list.sort()

        x_min = -self.p.spawn_margin_m
        seg_len = max(self.p.segment_length_m, 1e-6)

        for i, ac in enumerate(self.aircraft):
            heading_rad = float(ac.heading_rad)
            heading_deg = (math.degrees(heading_rad) + 360.0) % 360.0
            if abs(ac.ground_vx_mps) > 1e-9 or abs(ac.ground_vy_mps) > 1e-9:
                track_rad = math.atan2(ac.ground_vy_mps, ac.ground_vx_mps)
            else:
                track_rad = heading_rad
            track_deg = (math.degrees(track_rad) + 360.0) % 360.0
            wind_mag_mps = math.hypot(ac.wind_x_mps, ac.wind_y_mps)
            wind_dir_deg = (math.degrees(math.atan2(ac.wind_y_mps, ac.wind_x_mps)) + 360.0) % 360.0 if wind_mag_mps > 1e-9 else None
            along_wind_mps = ac.wind_x_mps * math.cos(heading_rad) + ac.wind_y_mps * math.sin(heading_rad)
            cross_wind_mps = -ac.wind_x_mps * math.sin(heading_rad) + ac.wind_y_mps * math.cos(heading_rad)
            eta_s = float(metrics["eta_s"][i]) if np.isfinite(metrics["eta_s"][i]) else None
            tti = float(metrics["tti"][i]) if np.isfinite(metrics["tti"][i]) else None
            std_s = float(metrics["std_s"][i])
            sta_s = float(metrics["sta_s"][i])
            scheduled_total_s = max(0.0, sta_s - std_s)
            estimated_total_s = max(0.0, eta_s - std_s) if eta_s is not None else None
            departure_delay_s = (
                max(0.0, float(ac.depart_t_s) - std_s)
                if ac.depart_t_s is not None
                else max(0.0, self.t_s - std_s)
            )
            arrival_delay_s = (eta_s - sta_s) if eta_s is not None else None
            progress_m = float(ac.route_progress_m if ac.route_mode else max(0.0, ac.x_m))
            total_m = float(ac.route_total_m if ac.route_mode else self.p.path_length_m)
            remaining_m = float(metrics["remaining_m"][i])
            progress_ratio = (progress_m / total_m) if total_m > 1e-9 else 0.0
            idle_overtake_candidate = self._find_overtake_candidate(ac) if ac.action is None else None
            active_overtake_target = self._get_overtake_target(ac) if ac.action == "overtake" else None
            overtake_reference = active_overtake_target or idle_overtake_candidate
            overtake_flow_gap_m = None
            overtake_distance_m = None
            overtake_relative_speed_knots = None
            if overtake_reference is not None:
                if ac.route_mode and overtake_reference.route_mode and overtake_reference.active_link_id == ac.active_link_id:
                    overtake_flow_gap_m = round(float(overtake_reference.route_progress_m - ac.route_progress_m), 1)
                elif (not ac.route_mode) and (not overtake_reference.route_mode):
                    overtake_flow_gap_m = round(float(overtake_reference.x_m - ac.x_m), 1)
                overtake_distance_m = round(
                    math.hypot(overtake_reference.x_m - ac.x_m, overtake_reference.y_m - ac.y_m), 1
                )
                ref_idx = aircraft_index_by_id.get(overtake_reference.id, i)
                overtake_relative_speed_knots = round(
                    float(metrics["v_ground_knots"][ref_idx] - metrics["v_ground_knots"][i]), 3
                )

            turn_state = ac.action_state if ac.action == "turn" else {}
            turn_radius_m = float(turn_state.get("radius_m")) if turn_state.get("radius_m") is not None else None
            theta_rad = float(turn_state.get("theta_rad")) if turn_state.get("theta_rad") is not None else None
            theta_end_rad = float(turn_state.get("theta_end_rad")) if turn_state.get("theta_end_rad") is not None else None
            turn_sign = float(turn_state.get("turn_sign")) if turn_state.get("turn_sign") is not None else None
            remaining_turn_angle_rad = None
            if theta_rad is not None and theta_end_rad is not None and turn_sign is not None:
                if turn_sign >= 0.0:
                    remaining_turn_angle_rad = max(0.0, theta_end_rad - theta_rad)
                else:
                    remaining_turn_angle_rad = max(0.0, theta_rad - theta_end_rad)

            overtake_state = ac.action_state if ac.action == "overtake" else {}
            current_route_offset_m = self._route_current_offset_m(ac) if ac.route_mode else float(ac.y_m)
            overtake_pass_completed = None
            if ac.action == "overtake":
                overtake_pass_completed = (
                    self._has_completed_route_overtake(ac)
                    if ac.route_mode
                    else self._has_completed_corridor_overtake(ac)
                )

            local_context: Dict[str, Any]
            fifo_context: Dict[str, Any]
            operations_context: Dict[str, Any]
            if ac.route_mode:
                route_state = route_states[i]
                link_metric = route_segment_metrics.get(ac.active_link_id or "", {})
                route_link = self.route_links.get(ac.active_link_id or "")
                exit_node_id = str(route_state["exit_node_id"]) if route_state else None
                request_t_s = None
                if exit_node_id is not None:
                    request_t_s = self.node_fifo_requests.get(exit_node_id, {}).get(ac.id)
                queue_rank = self._route_node_request_rank(exit_node_id, ac.id) if exit_node_id is not None else None
                queue_entries = self.node_fifo_requests.get(exit_node_id, {}) if exit_node_id is not None else {}
                queue_size = len(queue_entries)
                queue_head_id = self._peek_route_node_request(exit_node_id) if exit_node_id is not None else None
                node_release_t_s = float(self.node_release_t_s.get(exit_node_id, 0.0)) if exit_node_id is not None else None
                next_link_id = str(route_state["next_link_id"]) if route_state and route_state.get("next_link_id") else None
                downstream_positions = route_link_locals.get(next_link_id, []) if next_link_id else []
                downstream_nearest_gap_m = float(min(downstream_positions)) if downstream_positions else None
                downstream_sep_margin_m = (
                    downstream_nearest_gap_m - float(self.p.sep_min_m)
                    if downstream_nearest_gap_m is not None
                    else None
                )
                downstream_link = self.route_links.get(next_link_id or "") if next_link_id else None
                downstream_capacity = (
                    float(downstream_link.length_m / max(self.p.sep_min_m, 1e-6))
                    if downstream_link is not None
                    else None
                )
                downstream_count = len(downstream_positions)
                downstream_occupancy_ratio = (
                    downstream_count / max(downstream_capacity, 1e-9)
                    if downstream_capacity is not None
                    else None
                )
                queue_head = (queue_head_id == ac.id) if queue_head_id is not None else None
                release_open = (self.t_s >= node_release_t_s - 1e-9) if node_release_t_s is not None else None
                downstream_open = (
                    downstream_nearest_gap_m is None or downstream_nearest_gap_m >= self.p.sep_min_m - 1e-9
                )
                can_cross_node_now = bool(queue_head and release_open and downstream_open)
                link_capacity = (
                    float(route_link.length_m / max(self.p.sep_min_m, 1e-6))
                    if route_link is not None
                    else None
                )
                link_count = int(link_metric.get("count", 0))
                occupancy_ratio = (
                    (link_count / max(link_capacity, 1e-9))
                    if link_capacity is not None
                    else None
                )
                local_context = {
                    "kind": "route_link",
                    "id": ac.active_link_id,
                    "index": int(route_state["index"]) if route_state else None,
                    "entry_node_id": str(route_state["entry_node_id"]) if route_state else None,
                    "exit_node_id": exit_node_id,
                    "next_link_id": next_link_id,
                    "local_progress_m": round(float(route_state["local_s"]), 1) if route_state else None,
                    "local_remaining_m": round(max(0.0, float(route_state["length_m"] - route_state["local_s"])), 1) if route_state else None,
                    "length_m": round(float(route_state["length_m"]), 1) if route_state else None,
                    "count": link_count,
                    "mean_speed_knots": round(float(link_metric.get("v_mean", self.p.v_free_knots)), 1),
                    "score": round(float(link_metric.get("score", 0.0)), 3),
                    "level": int(link_metric.get("level", 0)),
                    "capacity_aircraft": round(link_capacity, 3) if link_capacity is not None else None,
                    "occupancy_ratio": round(float(occupancy_ratio), 3) if occupancy_ratio is not None else None,
                    "overflow_ratio": round(max(0.0, float(occupancy_ratio) - 1.0), 3) if occupancy_ratio is not None else None,
                }
                fifo_context = {
                    "queue_rank": int(queue_rank) if queue_rank is not None else None,
                    "request_time_s": round(float(request_t_s), 3) if request_t_s is not None else None,
                    "request_age_s": round(float(max(0.0, self.t_s - request_t_s)), 3) if request_t_s is not None else None,
                    "queue_size": int(queue_size),
                    "queue_head_aircraft_id": int(queue_head_id) if queue_head_id is not None else None,
                    "is_queue_head": bool(queue_head) if queue_head is not None else None,
                    "entry_node_id": str(route_state["entry_node_id"]) if route_state else None,
                    "exit_node_id": exit_node_id,
                    "node_release_time_s": round(float(node_release_t_s), 3) if node_release_t_s is not None else None,
                    "node_release_in_s": round(float(max(0.0, node_release_t_s - self.t_s)), 3) if node_release_t_s is not None else None,
                    "next_link_id": next_link_id,
                    "next_link_count": int(downstream_count) if next_link_id else None,
                    "next_link_capacity_aircraft": round(float(downstream_capacity), 3) if downstream_capacity is not None else None,
                    "next_link_occupancy_ratio": round(float(downstream_occupancy_ratio), 3) if downstream_occupancy_ratio is not None else None,
                    "next_link_nearest_gap_m": round(float(downstream_nearest_gap_m), 3) if downstream_nearest_gap_m is not None else None,
                    "next_link_sep_margin_m": round(float(downstream_sep_margin_m), 3) if downstream_sep_margin_m is not None else None,
                    "can_cross_node_now": bool(can_cross_node_now),
                    "can_enter_next_link_now": bool(downstream_open),
                }
                current_link_index = int(route_state["index"]) if route_state else 0
                operations_context = {
                    "sim_time_s": round(float(self.t_s), 3),
                    "phase": (
                        "completed" if remaining_m <= 1e-6 else
                        "managed_action" if ac.action is not None else
                        "holding" if ac.wait_reason is not None else
                        "pre_departure" if not ac.has_departed else
                        "enroute"
                    ),
                    "constraint_source": ac.wait_reason if ac.wait_reason is not None else ac.action,
                    "is_pre_departure": bool(not ac.has_departed),
                    "is_completed": bool(remaining_m <= 1e-6),
                    "is_holding": bool(ac.wait_reason is not None),
                    "is_action_active": bool(ac.action is not None),
                    "hold_flags": {
                        "spacing": ac.wait_reason == "spacing",
                        "start_hold": ac.wait_reason == "start_hold",
                        "fifo_hold": ac.wait_reason == "fifo_hold",
                        "node_hold": ac.wait_reason == "node_hold",
                        "merge_hold": ac.wait_reason == "merge_hold",
                    },
                    "active_link_id": ac.active_link_id,
                    "remaining_links_count": int(len(remaining_link_sets[i])),
                    "remaining_nodes_count": int(max(0, len(ac.route_node_ids) - current_link_index - 1)),
                    "distance_to_next_node_m": round(float(max(0.0, route_state["length_m"] - route_state["local_s"])), 3) if route_state else None,
                    "distance_to_exit_node_m": round(float(max(0.0, route_state["length_m"] - route_state["local_s"])), 3) if route_state else None,
                    "is_on_final_path_element": bool(len(remaining_link_sets[i]) <= 1),
                }
            else:
                seg_idx = int((ac.x_m - x_min) // seg_len)
                seg_ctx = segment_contexts[seg_idx] if 0 <= seg_idx < len(segment_contexts) else None
                seg_capacity = seg_len / max(self.p.sep_min_m, 1e-6)
                seg_count = int(seg_ctx["count"]) if seg_ctx else 0
                occupancy_ratio = seg_count / max(seg_capacity, 1e-9)
                local_context = {
                    "kind": "corridor_segment",
                    "index": seg_idx if seg_idx >= 0 else None,
                    "id": f"seg-{seg_idx}" if seg_idx >= 0 else None,
                    "x_start_m": round(float(seg_ctx["x_start"]), 1) if seg_ctx else None,
                    "x_end_m": round(float(seg_ctx["x_end"]), 1) if seg_ctx else None,
                    "count": seg_count,
                    "mean_speed_knots": round(float(seg_ctx["v_mean"]), 1) if seg_ctx else round(float(self.p.v_free_knots), 1),
                    "score": round(float(seg_ctx["score"]), 3) if seg_ctx else 0.0,
                    "level": int(seg_ctx["level"]) if seg_ctx else 0,
                    "capacity_aircraft": round(float(seg_capacity), 3),
                    "occupancy_ratio": round(float(occupancy_ratio), 3),
                    "overflow_ratio": round(max(0.0, float(occupancy_ratio) - 1.0), 3),
                }
                fifo_context = {
                    "queue_rank": None,
                    "request_time_s": None,
                    "request_age_s": None,
                    "queue_size": None,
                    "queue_head_aircraft_id": None,
                    "is_queue_head": None,
                    "entry_node_id": None,
                    "exit_node_id": None,
                    "node_release_time_s": None,
                    "node_release_in_s": None,
                    "next_link_id": None,
                    "next_link_count": None,
                    "next_link_capacity_aircraft": None,
                    "next_link_occupancy_ratio": None,
                    "next_link_nearest_gap_m": None,
                    "next_link_sep_margin_m": None,
                    "can_cross_node_now": None,
                    "can_enter_next_link_now": None,
                }
                segment_count = len(segment_contexts)
                operations_context = {
                    "sim_time_s": round(float(self.t_s), 3),
                    "phase": (
                        "completed" if remaining_m <= 1e-6 else
                        "managed_action" if ac.action is not None else
                        "holding" if ac.wait_reason is not None else
                        "pre_departure" if not ac.has_departed else
                        "enroute"
                    ),
                    "constraint_source": ac.wait_reason if ac.wait_reason is not None else ac.action,
                    "is_pre_departure": bool(not ac.has_departed),
                    "is_completed": bool(remaining_m <= 1e-6),
                    "is_holding": bool(ac.wait_reason is not None),
                    "is_action_active": bool(ac.action is not None),
                    "hold_flags": {
                        "spacing": ac.wait_reason == "spacing",
                        "start_hold": ac.wait_reason == "start_hold",
                        "fifo_hold": False,
                        "node_hold": False,
                        "merge_hold": False,
                    },
                    "active_link_id": None,
                    "remaining_links_count": None,
                    "remaining_nodes_count": None,
                    "distance_to_next_node_m": None,
                    "distance_to_exit_node_m": None,
                    "segment_index": seg_idx if seg_idx >= 0 else None,
                    "remaining_segments_count": int(max(0, segment_count - max(seg_idx, 0) - 1)) if segment_count > 0 else None,
                    "is_on_final_path_element": bool(seg_idx >= segment_count - 1) if seg_idx >= 0 and segment_count > 0 else None,
                }

            ac.data = {
                "schema_version": 3,
                "identity": {
                    "aircraft_id": int(ac.id),
                    "simulation_mode": "route" if ac.route_mode else "corridor",
                },
                "status": {
                    "route_mode": bool(ac.route_mode),
                    "has_departed": bool(ac.has_departed),
                    "managed": bool(not metrics["include_in_flow"][i]),
                    "delayed": bool(metrics["D"][i] >= self.p.delayed_thr_s),
                    "wait_reason": ac.wait_reason,
                    "action": ac.action,
                    "action_phase": ac.action_phase,
                    "action_meta": dict(ac.action_state) if ac.action_state else None,
                },
                "mission": {
                    "origin_node_id": ac.origin_node_id,
                    "destination_node_id": ac.destination_node_id,
                    "route_node_ids": list(ac.route_node_ids),
                    "route_link_ids": list(ac.route_link_ids),
                },
                "position": {
                    "x_m": round(float(ac.x_m), 3),
                    "y_m": round(float(ac.y_m), 3),
                    "progress_m": round(progress_m, 1),
                    "remaining_m": round(remaining_m, 1),
                    "path_total_m": round(total_m, 1),
                    "progress_ratio": round(progress_ratio, 4),
                    "heading_rad": round(heading_rad, 6),
                    "heading_deg": round(heading_deg, 3),
                    "track_rad": round(track_rad, 6),
                    "track_deg": round(track_deg, 3),
                },
                "speed": {
                    "command_knots": round(float(ac.v_cmd_knots), 3),
                    "air_knots": round(float(ac.v_act_mps * MPS_TO_KNOT), 3),
                    "actual_knots": round(float(metrics["v_act_knots"][i]), 3),
                    "ground_knots": round(float(metrics["v_ground_knots"][i]), 3),
                    "ground_vx_mps": round(float(ac.ground_vx_mps), 6),
                    "ground_vy_mps": round(float(ac.ground_vy_mps), 6),
                },
                "wind": {
                    "x_mps": round(float(ac.wind_x_mps), 6),
                    "y_mps": round(float(ac.wind_y_mps), 6),
                    "x_knots": round(float(ac.wind_x_mps * MPS_TO_KNOT), 3),
                    "y_knots": round(float(ac.wind_y_mps * MPS_TO_KNOT), 3),
                    "mag_mps": round(float(wind_mag_mps), 6),
                    "mag_knots": round(float(wind_mag_mps * MPS_TO_KNOT), 3),
                    "dir_deg": round(float(wind_dir_deg), 3) if wind_dir_deg is not None else None,
                    "along_mps": round(float(along_wind_mps), 6),
                    "cross_mps": round(float(cross_wind_mps), 6),
                    "along_knots": round(float(along_wind_mps * MPS_TO_KNOT), 3),
                    "cross_knots": round(float(cross_wind_mps * MPS_TO_KNOT), 3),
                },
                "schedule": {
                    "spawn_time_s": round(float(ac.spawn_t_s), 3),
                    "std_s": round(std_s, 3),
                    "depart_time_s": round(float(ac.depart_t_s), 3) if ac.depart_t_s is not None else None,
                    "sta_s": round(sta_s, 3),
                    "eta_s": round(float(eta_s), 3) if eta_s is not None else None,
                    "scheduled_total_s": round(float(scheduled_total_s), 3),
                    "estimated_total_s": round(float(estimated_total_s), 3) if estimated_total_s is not None else None,
                    "departure_delay_s": round(float(departure_delay_s), 3),
                    "arrival_delay_s": round(float(arrival_delay_s), 3) if arrival_delay_s is not None else None,
                    "tti": round(float(tti), 6) if tti is not None else None,
                    "flight_time_s": round(float(metrics["flight_time_s"][i]), 3),
                },
                "energy": {
                    "battery_remaining_s": round(float(metrics["battery_remaining_s"][i]), 3),
                    "battery_pct": round(float(metrics["battery_pct"][i]), 3),
                    "battery_used_pct": round(float(100.0 - metrics["battery_pct"][i]), 3),
                    "endurance_s": round(float(BATTERY_ENDURANCE_S), 3),
                },
                "operations": operations_context,
                "control": {
                    "speed": {
                        "can_issue_now": True,
                        "command_knots": round(float(ac.v_cmd_knots), 3),
                        "actual_knots": round(float(metrics["v_act_knots"][i]), 3),
                        "allowed_min_knots": round(float(self.p.v_min_knots), 3),
                        "allowed_max_knots": round(float(self.p.v_max_knots), 3),
                        "default_free_knots": round(float(self.p.v_free_knots), 3),
                        "default_init_knots": round(float(self.p.v_init_knots), 3),
                    },
                    "turn": {
                        "supported": True,
                        "ui_label": "우선회",
                        "can_issue_now": ac.action is None,
                        "active": ac.action == "turn",
                        "phase": ac.action_phase if ac.action == "turn" else None,
                        "diameter_m": round(float(turn_radius_m * 2.0), 3) if turn_radius_m is not None else None,
                        "radius_m": round(float(turn_radius_m), 3) if turn_radius_m is not None else None,
                        "center_x_m": round(float(turn_state.get("center_x_m")), 3) if turn_state.get("center_x_m") is not None else None,
                        "center_y_m": round(float(turn_state.get("center_y_m")), 3) if turn_state.get("center_y_m") is not None else None,
                        "theta_rad": round(float(theta_rad), 6) if theta_rad is not None else None,
                        "theta_end_rad": round(float(theta_end_rad), 6) if theta_end_rad is not None else None,
                        "remaining_angle_rad": round(float(remaining_turn_angle_rad), 6) if remaining_turn_angle_rad is not None else None,
                        "turn_sign": round(float(turn_sign), 3) if turn_sign is not None else None,
                        "resume_heading_rad": round(float(turn_state.get("resume_heading_rad")), 6) if turn_state.get("resume_heading_rad") is not None else None,
                        "resume_route_progress_m": round(float(turn_state.get("resume_route_progress_m")), 3) if turn_state.get("resume_route_progress_m") is not None else None,
                    },
                    "overtake": {
                        "supported": True,
                        "can_issue_now": ac.action is None and idle_overtake_candidate is not None,
                        "active": ac.action == "overtake",
                        "phase": ac.action_phase if ac.action == "overtake" else None,
                        "candidate_target_aircraft_id": int(idle_overtake_candidate.id) if idle_overtake_candidate is not None else None,
                        "target_aircraft_id": int(active_overtake_target.id) if active_overtake_target is not None else None,
                        "reference_aircraft_id": int(overtake_reference.id) if overtake_reference is not None else None,
                        "reference_flow_gap_m": overtake_flow_gap_m,
                        "reference_distance_m": overtake_distance_m,
                        "reference_relative_speed_knots": overtake_relative_speed_knots,
                        "lateral_offset_m": round(float(overtake_state.get("offset_m")), 3) if overtake_state.get("offset_m") is not None else None,
                        "transition_m": round(float(overtake_state.get("transition_m")), 3) if overtake_state.get("transition_m") is not None else None,
                        "boost_command_knots": round(float(overtake_state.get("boost_cmd_knots")), 3) if overtake_state.get("boost_cmd_knots") is not None else None,
                        "start_x_m": round(float(overtake_state.get("start_x_m")), 3) if overtake_state.get("start_x_m") is not None else None,
                        "start_progress_m": round(float(overtake_state.get("start_progress_m")), 3) if overtake_state.get("start_progress_m") is not None else None,
                        "merge_start_x_m": round(float(overtake_state.get("merge_start_x_m")), 3) if overtake_state.get("merge_start_x_m") is not None else None,
                        "merge_start_progress_m": round(float(overtake_state.get("merge_start_progress_m")), 3) if overtake_state.get("merge_start_progress_m") is not None else None,
                        "current_offset_m": round(float(current_route_offset_m), 3),
                        "pass_completed": bool(overtake_pass_completed) if overtake_pass_completed is not None else None,
                    },
                    "lifecycle": {
                        "can_delete_now": True,
                    },
                },
                "flow": {
                    "include_in_flow": bool(metrics["include_in_flow"][i]),
                    "speed_loss_ratio_l": round(float(metrics["l"][i]), 6),
                    "delay_accumulated_s": round(float(metrics["D"][i]), 3),
                    "delayed_ahead_ratio_R": round(float(metrics["R"][i]), 6),
                    "density_rho": round(float(metrics["rho"][i]), 6),
                    "congestion_c": round(float(metrics["c"][i]), 6),
                    "rho_ref": round(float(self.p.rho_ref), 6),
                    "cong_ref": round(float(self.p.cong_ref), 6),
                    "delay_window_s": round(float(self.p.delay_window_T_s), 3),
                    "delayed_threshold_s": round(float(self.p.delayed_thr_s), 3),
                    "lookahead_m": round(float(self.p.lookahead_L_m), 3),
                },
                "spacing": {
                    "min_separation_m": round(float(self.p.sep_min_m), 3),
                    **flow_spacing[i],
                    **proximity[i],
                },
                "routing": local_context,
                "fifo": fifo_context,
                "parameters": {
                    "simulation": {
                        "simulation_mode": self.p.simulation_mode,
                        "dt_s": round(float(self.p.dt_s), 6),
                        "realtime_factor": round(float(self.p.realtime_factor), 6),
                    },
                    "geometry": {
                        "path_length_m": round(float(self.p.path_length_m), 3),
                        "lane_width_m": round(float(self.p.lane_width_m), 3),
                        "spawn_margin_m": round(float(self.p.spawn_margin_m), 3),
                        "route_grid_spacing_m": round(float(self.p.route_grid_spacing_m), 3),
                        "route_row_count": int(self.p.route_row_count),
                        "route_row_gap_m": round(float(self.p.route_row_gap_m), 3),
                        "route_samples_per_segment": int(self.p.route_samples_per_segment),
                    },
                    "speed_policy": {
                        "v_free_knots": round(float(self.p.v_free_knots), 3),
                        "v_init_knots": round(float(self.p.v_init_knots), 3),
                        "v_min_knots": round(float(self.p.v_min_knots), 3),
                        "v_max_knots": round(float(self.p.v_max_knots), 3),
                        "a_max_mps2": round(float(self.p.a_max_mps2), 6),
                        "b_max_mps2": round(float(self.p.b_max_mps2), 6),
                    },
                    "separation_policy": {
                        "sep_min_m": round(float(self.p.sep_min_m), 3),
                        "spawn_spacing_m": round(float(self.p.spawn_spacing_m), 3),
                    },
                    "fifo_policy": {
                        "fifo_queue_sep_scale": round(float(self.p.fifo_queue_sep_scale), 6),
                        "fifo_node_clearance_min_m": round(float(self.p.fifo_node_clearance_min_m), 3),
                        "fifo_node_clearance_scale": round(float(self.p.fifo_node_clearance_scale), 6),
                        "fifo_hold_buffer_min_m": round(float(self.p.fifo_hold_buffer_min_m), 3),
                        "fifo_hold_buffer_scale": round(float(self.p.fifo_hold_buffer_scale), 6),
                        "fifo_approach_sep_scale": round(float(self.p.fifo_approach_sep_scale), 6),
                        "fifo_approach_time_s": round(float(self.p.fifo_approach_time_s), 3),
                    },
                    "congestion_policy": {
                        "segment_length_m": round(float(self.p.segment_length_m), 3),
                        "seg_w_overflow": round(float(self.p.seg_w_overflow), 6),
                        "seg_w_tti": round(float(self.p.seg_w_tti), 6),
                        "sigma_parallel_m": round(float(self.p.sigma_parallel_m), 3),
                        "sigma_perp_m": round(float(self.p.sigma_perp_m), 3),
                        "lookahead_L_m": round(float(self.p.lookahead_L_m), 3),
                        "lookahead_W_m": round(float(self.p.lookahead_W_m), 3),
                        "delay_window_T_s": round(float(self.p.delay_window_T_s), 3),
                        "delayed_thr_s": round(float(self.p.delayed_thr_s), 3),
                        "rho_ref": round(float(self.p.rho_ref), 6),
                        "cong_ref": round(float(self.p.cong_ref), 6),
                    },
                    "wind_policy": {
                        "wind_enabled": bool(self.p.wind_enabled),
                        "wind_level": self.p.wind_level,
                    },
                },
            }

    def get_full_state(self, show_density: bool = True, show_congestion: bool = True,
                        show_segments: bool = True) -> dict:
        metrics = self.compute_metrics()
        N = len(metrics["x"])
        want_density = bool(show_density and not self._is_route_mode())
        want_congestion = False
        segment_contexts = self.compute_segment_congestion(metrics)
        self._refresh_aircraft_data(metrics, segment_contexts)

        aircraft_list = []
        for i in range(N):
            eta_s = float(metrics["eta_s"][i]) if np.isfinite(metrics["eta_s"][i]) else None
            tti = float(metrics["tti"][i]) if np.isfinite(metrics["tti"][i]) else None
            aircraft_list.append({
                "id": int(metrics["id"][i]),
                "x": float(metrics["x"][i]),
                "y": float(metrics["y"][i]),
                "heading_rad": float(self.aircraft[i].heading_rad),
                "remaining_m": round(float(metrics["remaining_m"][i]), 1),
                "v_act_knots": round(float(metrics["v_act_knots"][i]), 1),
                "v_cmd_knots": round(float(metrics["v_cmd_knots"][i]), 1),
                "sta_s": round(float(metrics["sta_s"][i]), 1),
                "eta_s": round(eta_s, 1) if eta_s is not None else None,
                "tti": round(tti, 3) if tti is not None else None,
                "battery_remaining_s": round(float(metrics["battery_remaining_s"][i]), 1),
                "battery_pct": round(float(metrics["battery_pct"][i]), 1),
                "l": round(float(metrics["l"][i]), 3),
                "D": round(float(metrics["D"][i]), 1),
                "R": round(float(metrics["R"][i]), 3),
                "c": round(float(metrics["c"][i]), 3),
                "delayed": bool(metrics["D"][i] >= self.p.delayed_thr_s),
                "managed": bool(not metrics["include_in_flow"][i]),
                "action": self.aircraft[i].action,
                "action_phase": self.aircraft[i].action_phase,
                "action_meta": dict(self.aircraft[i].action_state) if self.aircraft[i].action_state else None,
                "origin_node_id": self.aircraft[i].origin_node_id,
                "destination_node_id": self.aircraft[i].destination_node_id,
                "route_mode": bool(self.aircraft[i].route_mode),
                "route_progress_m": round(float(self.aircraft[i].route_progress_m), 1),
                "route_total_m": round(float(self.aircraft[i].route_total_m), 1),
                "route_node_ids": list(self.aircraft[i].route_node_ids),
                "active_link_id": self.aircraft[i].active_link_id,
                "wait_reason": self.aircraft[i].wait_reason,
                "data": self.aircraft[i].data,
            })

        heatmaps = self.compute_heatmaps(metrics, want_density=want_density, want_congestion=want_congestion)
        segments = segment_contexts if show_segments else []
        summary = self.compute_summary(metrics)
        wind_state = self.get_wind_state()
        route_network = self.get_route_network_state(segments if self._is_route_mode() else None)

        return {
            "t": round(self.t_s, 1),
            "mode": self.p.simulation_mode,
            "aircraft": aircraft_list,
            "heatmaps": heatmaps if (want_density or want_congestion) else None,
            "segments": segments,
            "summary": summary,
            "wind": wind_state,
            "route_network": route_network,
            "params": {
                "simulation_mode": self.p.simulation_mode,
                "path_length_m": self.p.path_length_m,
                "lane_width_m": self.p.lane_width_m,
                "spawn_margin_m": self.p.spawn_margin_m,
                "auto_spawn_enabled": self.p.auto_spawn_enabled,
                "spawn_spacing_m": self.p.spawn_spacing_m,
                "route_grid_spacing_m": self.p.route_grid_spacing_m,
                "route_row_count": self.p.route_row_count,
                "route_row_gap_m": self.p.route_row_gap_m,
                "v_free_knots": self.p.v_free_knots,
                "v_init_knots": self.p.v_init_knots,
                "v_min_knots": self.p.v_min_knots,
                "v_max_knots": self.p.v_max_knots,
                "wind_enabled": self.p.wind_enabled,
                "wind_level": self.p.wind_level,
                "a_max_mps2": self.p.a_max_mps2,
                "b_max_mps2": self.p.b_max_mps2,
                "sep_min_m": self.p.sep_min_m,
                "fifo_queue_sep_scale": self.p.fifo_queue_sep_scale,
                "fifo_node_clearance_min_m": self.p.fifo_node_clearance_min_m,
                "fifo_node_clearance_scale": self.p.fifo_node_clearance_scale,
                "fifo_hold_buffer_min_m": self.p.fifo_hold_buffer_min_m,
                "fifo_hold_buffer_scale": self.p.fifo_hold_buffer_scale,
                "fifo_approach_sep_scale": self.p.fifo_approach_sep_scale,
                "fifo_approach_time_s": self.p.fifo_approach_time_s,
                "segment_length_m": self.p.segment_length_m,
                "seg_w_overflow": self.p.seg_w_overflow,
                "seg_w_tti": self.p.seg_w_tti,
                "sigma_parallel_m": self.p.sigma_parallel_m,
                "sigma_perp_m": self.p.sigma_perp_m,
                "lookahead_L_m": self.p.lookahead_L_m,
                "delay_window_T_s": self.p.delay_window_T_s,
                "delayed_thr_s": self.p.delayed_thr_s,
                "rho_ref": self.p.rho_ref,
                "cong_ref": self.p.cong_ref,
                "dt_s": self.p.dt_s,
                "realtime_factor": self.p.realtime_factor,
            },
        }
