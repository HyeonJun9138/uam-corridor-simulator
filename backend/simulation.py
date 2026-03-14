"""
UAM Corridor Simulation Engine
Ported from PyQt desktop app to a stateless computation module.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple

import numpy as np

KNOT_TO_MPS = 0.514444
MPS_TO_KNOT = 1.0 / KNOT_TO_MPS


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
    path_length_m: float = 20000.0
    lane_width_m: float = 200.0
    spawn_margin_m: float = 3000.0
    spawn_spacing_m: float = 600.0
    segment_length_m: float = 10000.0
    seg_w_overflow: float = 0.3
    seg_w_tti: float = 0.7
    dt_s: float = 0.2
    realtime_factor: float = 1.0
    v_free_knots: float = 100.0
    sep_min_m: float = 200.0
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
    def __init__(self, ac_id: int, x_m: float, y_m: float, v_cmd_knots: float):
        self.id = ac_id
        self.x_m = float(x_m)
        self.y_m = float(y_m)
        self.v_cmd_knots = float(v_cmd_knots)
        self.v_act_mps = self.v_cmd_knots * KNOT_TO_MPS
        self.delay_incs: Deque[Tuple[float, float]] = deque()
        self.D_s: float = 0.0

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
        }


class SimulationEngine:
    def __init__(self, params: SimParams):
        self.p = params
        self.t_s: float = 0.0
        self._next_id: int = 1
        self.aircraft: List[Aircraft] = []

    def reset(self):
        self.t_s = 0.0
        self._next_id = 1
        self.aircraft.clear()

    def spawn_aircraft(self):
        x0 = 0.0
        y0 = 0.0
        ac = Aircraft(self._next_id, x0, y0, self.p.v_free_knots)
        self._next_id += 1
        self.aircraft.append(ac)
        return ac.id

    def delete_aircraft(self, ac_id: int):
        self.aircraft = [ac for ac in self.aircraft if ac.id != ac_id]

    def set_aircraft_speed(self, ac_id: int, v_knots: float):
        for ac in self.aircraft:
            if ac.id == ac_id:
                ac.set_command_speed(v_knots)
                return

    def step(self):
        dt = self.p.dt_s
        self.t_s += dt

        if not self.aircraft:
            return

        x_old = np.array([ac.x_m for ac in self.aircraft], dtype=float)
        v_cmd_mps = np.array([ac.v_cmd_knots for ac in self.aircraft], dtype=float) * KNOT_TO_MPS
        v_prev_mps = np.array([ac.v_act_mps for ac in self.aircraft], dtype=float)

        order = np.argsort(-x_old)
        x_sorted = x_old[order]
        v_cmd_sorted = v_cmd_mps[order]
        v_prev_sorted = v_prev_mps[order]

        v_new_sorted = np.zeros_like(v_cmd_sorted)
        a_max = max(self.p.a_max_mps2, 1e-6)
        b_max = max(self.p.b_max_mps2, 1e-6)

        for k in range(len(x_sorted)):
            if k == 0:
                v_desired = v_cmd_sorted[k]
                v_high = v_prev_sorted[k] + a_max * dt
                v_low = max(0.0, v_prev_sorted[k] - b_max * dt)
                if v_desired > v_high:
                    v_new_sorted[k] = v_high
                elif v_desired < v_low:
                    v_new_sorted[k] = v_low
                else:
                    v_new_sorted[k] = v_desired
                continue

            gap = x_sorted[k - 1] - x_sorted[k]
            v_lead = v_new_sorted[k - 1]
            v_safe = v_lead + (gap - self.p.sep_min_m) / max(dt, 1e-6)
            v_safe = max(0.0, v_safe)
            v_desired = min(v_cmd_sorted[k], v_safe)
            v_high = v_prev_sorted[k] + a_max * dt
            v_low = max(0.0, v_prev_sorted[k] - b_max * dt)
            if v_desired > v_high:
                v_new = v_high
            elif v_desired < v_low:
                v_new = v_low
            else:
                v_new = v_desired
            if v_new > v_safe:
                v_new = v_safe
            v_new_sorted[k] = max(0.0, v_new)

        x_new_sorted = x_sorted + v_new_sorted * dt

        for k in range(1, len(x_new_sorted)):
            max_follow = x_new_sorted[k - 1] - self.p.sep_min_m
            if x_new_sorted[k] > max_follow:
                if max_follow >= x_sorted[k]:
                    x_new_sorted[k] = max_follow
                    v_new_sorted[k] = max(0.0, (x_new_sorted[k] - x_sorted[k]) / max(dt, 1e-6))
                else:
                    x_new_sorted[k] = x_sorted[k]
                    v_new_sorted[k] = 0.0

        x_new = np.empty_like(x_new_sorted)
        v_act_mps = np.empty_like(v_new_sorted)
        x_new[order] = x_new_sorted
        v_act_mps[order] = v_new_sorted

        for i, ac in enumerate(self.aircraft):
            ac.x_m = float(x_new[i])
            ac.v_act_mps = float(max(0.0, v_act_mps[i]))

        L = self.p.path_length_m
        self.aircraft = [ac for ac in self.aircraft if ac.x_m <= L + 100.0]

        v_free_mps = self.p.v_free_knots * KNOT_TO_MPS
        for ac in self.aircraft:
            l = max(0.0, 1.0 - (ac.v_act_mps / max(v_free_mps, 1e-9)))
            ac.update_delay_window(self.t_s, l, dt, self.p.delay_window_T_s)

    def compute_metrics(self) -> Dict[str, np.ndarray]:
        N = len(self.aircraft)
        if N == 0:
            return {
                "id": np.array([], dtype=int),
                "x": np.array([], dtype=float),
                "y": np.array([], dtype=float),
                "v_act_knots": np.array([], dtype=float),
                "v_cmd_knots": np.array([], dtype=float),
                "l": np.array([], dtype=float),
                "D": np.array([], dtype=float),
                "rho": np.array([], dtype=float),
                "R": np.array([], dtype=float),
                "c": np.array([], dtype=float),
            }

        ids = np.array([ac.id for ac in self.aircraft], dtype=int)
        x = np.array([ac.x_m for ac in self.aircraft], dtype=float)
        y = np.array([ac.y_m for ac in self.aircraft], dtype=float)
        v_act_knots = np.array([ac.v_act_mps for ac in self.aircraft], dtype=float) * MPS_TO_KNOT
        v_cmd_knots = np.array([ac.v_cmd_knots for ac in self.aircraft], dtype=float)

        v_free = self.p.v_free_knots
        l = np.maximum(0.0, 1.0 - (v_act_knots / max(v_free, 1e-9)))
        D = np.array([ac.D_s for ac in self.aircraft], dtype=float)

        sig = max(self.p.sigma_parallel_m, 1e-6)
        dx = x.reshape(-1, 1) - x.reshape(1, -1)
        rho = np.sum(np.exp(-(dx ** 2) / (2.0 * sig ** 2)), axis=1) - 1.0

        delayed = (D >= self.p.delayed_thr_s).astype(float)
        order = np.argsort(x)
        x_sorted = x[order]
        delayed_sorted = delayed[order]
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

        R = np.zeros_like(R_sorted)
        R[order] = R_sorted

        rho_hat = np.minimum(1.0, rho / max(self.p.rho_ref, 1e-9))
        D_avg = D / max(self.p.delay_window_T_s, 1e-9)
        A = np.maximum(D_avg, R)
        c = rho_hat * A

        return {
            "id": ids,
            "x": x,
            "y": y,
            "v_act_knots": v_act_knots,
            "v_cmd_knots": v_cmd_knots,
            "l": l,
            "D": D,
            "rho": rho,
            "R": R,
            "c": c,
        }

    def compute_heatmaps(self, metrics: Dict[str, np.ndarray],
                         want_density: bool, want_congestion: bool) -> Dict[str, any]:
        x = metrics["x"]
        y = metrics["y"]
        c = metrics["c"]

        x_min = -self.p.spawn_margin_m
        x_max = self.p.path_length_m
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

    def compute_segment_congestion(self, metrics: Dict[str, np.ndarray]) -> List[dict]:
        x = metrics["x"]
        v_act = metrics["v_act_knots"]
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
            return {"N": 0, "DR": 0, "TD": 0, "area_km2": 0, "queue_km": 0}

        D = metrics["D"]
        DR = float(np.mean(D >= self.p.delayed_thr_s))
        TD = float(np.sum(D))

        return {
            "N": N,
            "DR": round(DR, 3),
            "TD_min": round(TD / 60, 2),
        }

    def get_full_state(self, show_density: bool = True, show_congestion: bool = True,
                        show_segments: bool = True) -> dict:
        metrics = self.compute_metrics()
        N = len(metrics["x"])

        aircraft_list = []
        for i in range(N):
            aircraft_list.append({
                "id": int(metrics["id"][i]),
                "x": float(metrics["x"][i]),
                "y": float(metrics["y"][i]),
                "v_act_knots": round(float(metrics["v_act_knots"][i]), 1),
                "v_cmd_knots": round(float(metrics["v_cmd_knots"][i]), 1),
                "l": round(float(metrics["l"][i]), 3),
                "D": round(float(metrics["D"][i]), 1),
                "R": round(float(metrics["R"][i]), 3),
                "c": round(float(metrics["c"][i]), 3),
                "delayed": bool(metrics["D"][i] >= self.p.delayed_thr_s),
            })

        heatmaps = self.compute_heatmaps(metrics, want_density=show_density, want_congestion=show_congestion)
        segments = self.compute_segment_congestion(metrics) if show_segments else []
        summary = self.compute_summary(metrics)

        return {
            "t": round(self.t_s, 1),
            "aircraft": aircraft_list,
            "heatmaps": heatmaps if (show_density or show_congestion) else None,
            "segments": segments,
            "summary": summary,
            "params": {
                "path_length_m": self.p.path_length_m,
                "lane_width_m": self.p.lane_width_m,
                "spawn_margin_m": self.p.spawn_margin_m,
                "v_free_knots": self.p.v_free_knots,
                "sep_min_m": self.p.sep_min_m,
                "segment_length_m": self.p.segment_length_m,
                "delayed_thr_s": self.p.delayed_thr_s,
            },
        }
