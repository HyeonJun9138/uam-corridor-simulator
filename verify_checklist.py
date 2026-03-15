from __future__ import annotations

import math
from pathlib import Path
from typing import Callable, List, Tuple

from fastapi.testclient import TestClient

from backend.simulation import SimulationEngine, SimParams
import backend.server as server


Result = Tuple[str, bool, str]


def check(results: List[Result], name: str, condition: bool, detail: str = ""):
    results.append((name, bool(condition), detail))


def route_merge_engine() -> SimulationEngine:
    engine = SimulationEngine(
        SimParams(
            simulation_mode="route",
            wind_enabled=False,
            path_length_m=20000.0,
            route_grid_spacing_m=5000.0,
            route_row_count=3,
            route_row_gap_m=1200.0,
        )
    )
    engine.clear_route_links()
    for start_id, end_id in [
        ("N0_0", "N1_1"),
        ("N0_2", "N1_1"),
        ("N1_1", "N2_1"),
        ("N2_1", "N3_1"),
        ("N3_1", "N4_1"),
    ]:
        assert engine.toggle_route_link(start_id, end_id)
    return engine


def run_sim_steps(engine: SimulationEngine, steps: int):
    for _ in range(steps):
        engine.step()


def test_mode_labels(results: List[Result]):
    html = Path("frontend/index.html").read_text(encoding="utf-8")
    app_js = Path("frontend/js/app.js").read_text(encoding="utf-8")
    check(results, "Mode label renamed to 직선 항로", "직선 항로" in html)
    check(results, "Mode label renamed to Custom 항로", "Custom 항로" in html)
    check(results, "STD removed from detail panel markup", 'id="detail-std"' not in html)
    check(results, "Right-turn label renamed to 우선회", "우선회 1회 실행" in html and "우선회 비행 중" in app_js)


def test_wind_bidirectional(results: List[Result]):
    engine = SimulationEngine(SimParams(wind_enabled=True, wind_level="middle"))
    wx_values = [engine._wind_vector_mps(10000.0, 0.0, float(t))[0] for t in range(0, 481, 5)]
    check(
        results,
        "Wind model produces tailwind and headwind along corridor axis",
        min(wx_values) < 0.0 < max(wx_values),
        f"min_wx={min(wx_values):.3f}, max_wx={max(wx_values):.3f}",
    )


def test_route_merge_separation(results: List[Result]):
    engine = route_merge_engine()
    first = engine.spawn_aircraft("N0_0")
    second = engine.spawn_aircraft("N0_2")
    assert first and second

    violation = None
    for step in range(260):
        engine.step()
        grouped = {}
        for ac in engine.aircraft:
            if ac.active_link_id:
                grouped.setdefault(ac.active_link_id, []).append(ac)
        for link_id, members in grouped.items():
            members.sort(key=lambda ac: ac.route_progress_m, reverse=True)
            for lead, trail in zip(members, members[1:]):
                gap = lead.route_progress_m - trail.route_progress_m
                if gap < engine.p.sep_min_m - 1e-6:
                    violation = f"step={step}, link={link_id}, gap={gap:.2f}"
                    break
            if violation:
                break
        if violation:
            break

    check(results, "Merged route links maintain minimum separation", violation is None, violation or "")


def test_route_turn_geometry(results: List[Result]):
    engine = SimulationEngine(
        SimParams(
            simulation_mode="route",
            wind_enabled=False,
            path_length_m=10000.0,
            route_grid_spacing_m=5000.0,
            route_row_count=3,
            route_row_gap_m=1200.0,
        )
    )
    engine.clear_route_links()
    assert engine.toggle_route_link("N0_0", "N1_1")
    assert engine.toggle_route_link("N1_1", "N2_2")
    ac_id = engine.spawn_aircraft("N0_0")
    assert ac_id is not None
    run_sim_steps(engine, 12)
    ac = next(ac for ac in engine.aircraft if ac.id == ac_id)
    before_heading = ac.heading_rad
    ok_cmd = engine.command_turn(ac_id, 800.0)
    run_sim_steps(engine, 4)
    ac = next(ac for ac in engine.aircraft if ac.id == ac_id)
    state = ac.action_state
    radius = float(state.get("radius_m", 400.0))
    center_x = float(state.get("center_x_m", ac.x_m))
    center_y = float(state.get("center_y_m", ac.y_m))
    right_normal = (math.sin(before_heading), -math.cos(before_heading))
    center_offset = (center_x - ac.x_m, center_y - ac.y_m)
    right_dot = right_normal[0] * center_offset[0] + right_normal[1] * center_offset[1]
    radius_error = abs(math.hypot(ac.x_m - center_x, ac.y_m - center_y) - radius)
    check(
        results,
        "Route right turn uses heading-right circle center on diagonal route",
        ok_cmd and right_dot > 0.0 and radius_error < 5.0,
        f"cmd={ok_cmd}, right_dot={right_dot:.2f}, radius_error={radius_error:.2f}",
    )


def test_route_overtake_rules(results: List[Result]):
    engine = SimulationEngine(SimParams(simulation_mode="route", wind_enabled=False))
    lead_id = engine.spawn_aircraft("N0_1")
    assert lead_id is not None
    run_sim_steps(engine, 12)
    trail_id = engine.spawn_aircraft("N0_1")
    assert trail_id is not None
    run_sim_steps(engine, 25)
    near_ok = engine.command_overtake(trail_id, 120.0, 15.0, target_id=lead_id)

    engine_far = SimulationEngine(SimParams(simulation_mode="route", wind_enabled=False))
    lead_far_id = engine_far.spawn_aircraft("N0_1")
    assert lead_far_id is not None
    run_sim_steps(engine_far, 75)
    trail_far_id = engine_far.spawn_aircraft("N0_1")
    assert trail_far_id is not None
    run_sim_steps(engine_far, 10)
    far_ok = engine_far.command_overtake(trail_far_id, 120.0, 15.0, target_id=lead_far_id)

    engine_node = SimulationEngine(SimParams(simulation_mode="route", wind_enabled=False))
    lead_node_id = engine_node.spawn_aircraft("N0_1")
    trail_node_id = engine_node.spawn_aircraft("N0_1")
    assert lead_node_id is not None and trail_node_id is not None
    run_sim_steps(engine_node, 170)
    near_node_ok = engine_node.command_overtake(trail_node_id, 120.0, 15.0, target_id=lead_node_id)

    check(
        results,
        "Route overtake is allowed for feasible same-link near target",
        near_ok,
        f"near_ok={near_ok}",
    )
    check(
        results,
        "Route overtake rejects impractical far target or near-node maneuver",
        (not far_ok) and (not near_node_ok),
        f"far_ok={far_ok}, near_node_ok={near_node_ok}",
    )


def test_websocket_controls(results: List[Result]):
    original_engine = server.sim_engine
    original_running = server.sim_running
    original_task = server.sim_task
    server.sim_engine = SimulationEngine(SimParams())
    server.sim_running = False
    server.sim_task = None

    try:
        with TestClient(server.app) as client:
            with client.websocket_connect("/ws") as ws:
                initial = ws.receive_json()
                ws.send_json({"action": "set_mode", "mode": "route"})
                state = ws.receive_json()
                status = ws.receive_json()
                ws.send_json({"action": "spawn", "start_node_id": "N0_1"})
                spawned = ws.receive_json()
                ws.send_json({"action": "update_params", "params": {"realtime_factor": 5}})
                update_state = ws.receive_json()
                ack = ws.receive_json()

        check(results, "WebSocket initial state received", initial.get("type") == "state")
        check(
            results,
            "WebSocket route mode switching resets sim and reports paused status",
            state.get("mode") == "route" and status.get("type") == "status" and status.get("running") is False,
        )
        check(
            results,
            "WebSocket route spawn from selected start node works",
            spawned.get("type") == "state" and spawned.get("spawned_id") is not None,
        )
        check(
            results,
            "WebSocket parameter update acknowledges realtime factor",
            update_state.get("type") == "state"
            and update_state.get("params", {}).get("realtime_factor") == 5
            and ack.get("type") == "params_ack"
            and ack.get("params", {}).get("realtime_factor") == 5,
        )
    finally:
        server.sim_engine = original_engine
        server.sim_running = original_running
        server.sim_task = original_task


def main():
    results: List[Result] = []
    tests: List[Callable[[List[Result]], None]] = [
        test_mode_labels,
        test_wind_bidirectional,
        test_route_merge_separation,
        test_route_turn_geometry,
        test_route_overtake_rules,
        test_websocket_controls,
    ]
    for test in tests:
        test(results)

    failed = [item for item in results if not item[1]]
    for name, ok, detail in results:
        status = "PASS" if ok else "FAIL"
        suffix = f" | {detail}" if detail else ""
        print(f"[{status}] {name}{suffix}")

    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
