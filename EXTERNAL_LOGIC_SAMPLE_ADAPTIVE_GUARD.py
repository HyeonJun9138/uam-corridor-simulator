#
# Baseline external traffic-management logic for this simulator.
# When adapting this file or giving it to another code-generation model:
# - treat it as the reference structure
# - keep helper-based conservative command generation
# - interpret forward_flow_relative_speed_knots as front - self
# - do not use shared_remaining_link_count as a mandatory corridor overtake gate
# - trust control.overtake.can_issue_now as the primary engine-side feasibility signal
#

LOGIC_NAME = "Adaptive Separation Guard"
LOGIC_DESCRIPTION = (
    "500m minimum separation with progressive speed control, "
    "conservative overtake, and defensive turn fallback."
)

PARAM_OVERRIDES = {
    "sep_min_m": 500,
}


def _safe_dict(value):
    if isinstance(value, dict):
        return value
    return {}


def _num(value, default):
    if value is None:
        return default
    return value


def _clamp(value, low, high):
    return max(low, min(high, value))


def _route_mode(ac):
    data = _safe_dict(ac.get("data"))
    status = _safe_dict(data.get("status"))
    identity = _safe_dict(data.get("identity"))
    if status.get("route_mode") is True:
        return True
    return identity.get("simulation_mode") == "route"


def _sep_min(ac):
    data = _safe_dict(ac.get("data"))
    params = _safe_dict(data.get("parameters"))
    separation = _safe_dict(params.get("separation_policy"))
    return float(_num(separation.get("sep_min_m"), 500.0))


def _can_manage(ac):
    data = _safe_dict(ac.get("data"))
    status = _safe_dict(data.get("status"))
    ops = _safe_dict(data.get("operations"))

    if ops.get("is_completed", False):
        return False
    if ops.get("is_pre_departure", False):
        return False
    if ops.get("phase") not in ["enroute", "holding", "managed_action"]:
        return False
    if status.get("action") is not None:
        return False
    if status.get("wait_reason") == "start_hold":
        return False
    return True


def _build_speed_command(ac):
    data = _safe_dict(ac.get("data"))
    spacing = _safe_dict(data.get("spacing"))
    control = _safe_dict(data.get("control"))
    speed_ctrl = _safe_dict(control.get("speed"))
    flow = _safe_dict(data.get("flow"))
    wind = _safe_dict(data.get("wind"))

    if not speed_ctrl.get("can_issue_now", False):
        return None

    gap = spacing.get("forward_flow_gap_m")
    if gap is None:
        return None

    sep_min = _sep_min(ac)
    cmd_knots = float(_num(speed_ctrl.get("command_knots"), 100.0))
    free_knots = float(_num(speed_ctrl.get("default_free_knots"), cmd_knots))
    min_knots = float(_num(speed_ctrl.get("allowed_min_knots"), 60.0))
    max_knots = float(_num(speed_ctrl.get("allowed_max_knots"), max(free_knots, cmd_knots)))
    density = float(_num(flow.get("density_rho"), 0.0))
    congestion = float(_num(flow.get("congestion_c"), 0.0))
    cross_knots = abs(float(_num(wind.get("cross_knots"), 0.0)))

    ratio = 1.0
    if gap < sep_min * 0.85:
        ratio = 0.62
    elif gap < sep_min:
        ratio = 0.72
    elif gap < sep_min * 1.2:
        ratio = 0.80
    elif gap < sep_min * 1.4:
        ratio = 0.88
    elif gap < sep_min * 1.8:
        ratio = 0.94

    if congestion >= 0.45:
        ratio -= 0.04
    if density >= 0.70:
        ratio -= 0.03
    if cross_knots >= 15.0:
        ratio -= 0.03

    ratio = _clamp(ratio, 0.58, 1.00)
    target_knots = _clamp(free_knots * ratio, min_knots, max_knots)

    if abs(target_knots - cmd_knots) < 1.5:
        return None

    return {
        "action": "set_speed",
        "id": int(ac["id"]),
        "speed": round(target_knots, 1),
    }


def _build_overtake_command(ac):
    data = _safe_dict(ac.get("data"))
    status = _safe_dict(data.get("status"))
    spacing = _safe_dict(data.get("spacing"))
    control = _safe_dict(data.get("control"))
    overtake_ctrl = _safe_dict(control.get("overtake"))
    flow = _safe_dict(data.get("flow"))
    wind = _safe_dict(data.get("wind"))

    if not overtake_ctrl.get("supported", False):
        return None
    if not overtake_ctrl.get("can_issue_now", False):
        return None

    wait_reason = status.get("wait_reason")
    if wait_reason in ["fifo_hold", "node_hold", "merge_hold", "start_hold"]:
        return None

    target_id = overtake_ctrl.get("candidate_target_aircraft_id")
    if target_id is None:
        return None

    gap = spacing.get("forward_flow_gap_m")
    if gap is None:
        return None

    sep_min = _sep_min(ac)
    rel_speed = float(_num(spacing.get("forward_flow_relative_speed_knots"), 0.0))
    congestion = float(_num(flow.get("congestion_c"), 0.0))
    delayed_ratio = float(_num(flow.get("delayed_ahead_ratio_R"), 0.0))
    cross_knots = abs(float(_num(wind.get("cross_knots"), 0.0)))

    if gap > sep_min * 1.25:
        return None
    if rel_speed > 2.0 and congestion < 0.35 and delayed_ratio < 0.25:
        return None
    if _route_mode(ac) and cross_knots >= 20.0:
        return None

    offset_m = 120.0 if _route_mode(ac) else 110.0
    if gap < sep_min or congestion >= 0.55:
        offset_m += 20.0

    boost_knots = 10.0
    if gap < sep_min:
        boost_knots = 14.0
    if congestion >= 0.55 or delayed_ratio >= 0.35:
        boost_knots = max(boost_knots, 16.0)

    return {
        "action": "overtake",
        "id": int(ac["id"]),
        "target_id": int(target_id),
        "lateral_offset_m": round(offset_m, 1),
        "speed_boost_knots": round(boost_knots, 1),
    }


def _build_turn_command(ac, overtake_ready):
    if overtake_ready:
        return None

    data = _safe_dict(ac.get("data"))
    status = _safe_dict(data.get("status"))
    spacing = _safe_dict(data.get("spacing"))
    control = _safe_dict(data.get("control"))
    turn_ctrl = _safe_dict(control.get("turn"))
    flow = _safe_dict(data.get("flow"))
    fifo = _safe_dict(data.get("fifo"))

    if not turn_ctrl.get("supported", False):
        return None
    if not turn_ctrl.get("can_issue_now", False):
        return None

    sep_min = _sep_min(ac)
    gap = spacing.get("forward_flow_gap_m")
    conflict_distance = spacing.get("nearest_conflict_distance_m")
    congestion = float(_num(flow.get("congestion_c"), 0.0))
    density = float(_num(flow.get("density_rho"), 0.0))
    delayed_ratio = float(_num(flow.get("delayed_ahead_ratio_R"), 0.0))
    wait_reason = status.get("wait_reason")
    blocked = (fifo.get("can_cross_node_now") is False) or (fifo.get("can_enter_next_link_now") is False)

    severe_conflict = conflict_distance is not None and conflict_distance < sep_min * 0.85
    compressed_flow = gap is not None and gap < sep_min * 0.80
    congestion_high = congestion >= 0.55 or density >= 0.85 or delayed_ratio >= 0.45
    hold_block = wait_reason in ["fifo_hold", "node_hold", "merge_hold"]

    if not (
        severe_conflict
        or (compressed_flow and congestion_high and blocked)
        or (hold_block and congestion_high)
    ):
        return None

    diameter_m = 800.0
    if severe_conflict:
        diameter_m = 900.0
    elif hold_block:
        diameter_m = 700.0

    return {
        "action": "turn",
        "id": int(ac["id"]),
        "diameter_m": round(diameter_m, 1),
    }


def control_step(state):
    commands = []
    notes = []

    for ac in state.get("aircraft", []):
        if len(commands) >= 256:
            break
        if not _can_manage(ac):
            continue

        overtake_cmd = _build_overtake_command(ac)
        turn_cmd = _build_turn_command(ac, overtake_cmd is not None)
        speed_cmd = None if (overtake_cmd or turn_cmd) else _build_speed_command(ac)

        if speed_cmd is not None and len(commands) < 256:
            commands.append(speed_cmd)
            notes.append("ac {} speed_guard {}".format(ac["id"], speed_cmd["speed"]))

        if overtake_cmd is not None and len(commands) < 256:
            commands.append(overtake_cmd)
            notes.append("ac {} overtake target {}".format(ac["id"], overtake_cmd["target_id"]))
        elif turn_cmd is not None and len(commands) < 256:
            commands.append(turn_cmd)
            notes.append("ac {} defensive_turn {}".format(ac["id"], turn_cmd["diameter_m"]))

    return {
        "commands": commands,
        "params": {},
        "notes": notes,
    }
