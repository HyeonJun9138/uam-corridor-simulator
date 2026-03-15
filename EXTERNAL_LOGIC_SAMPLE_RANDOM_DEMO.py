#
# Demo external logic for verifying that outside code can control
# individual aircraft in visible ways. This intentionally prefers
# frequent, pseudo-random commands over operational realism.
#

LOGIC_NAME = "Random Control Demo"
LOGIC_DESCRIPTION = (
    "Pseudo-random external control demo that issues visible speed, "
    "overtake, and turn commands for individual aircraft."
)

PARAM_OVERRIDES = {
    "sep_min_m": 200,
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


def _fract(value):
    return value - int(value)


def _noise(seed_value):
    return _fract(math.sin(seed_value) * 43758.5453123)


def _route_mode(ac):
    data = _safe_dict(ac.get("data"))
    identity = _safe_dict(data.get("identity"))
    status = _safe_dict(data.get("status"))
    if status.get("route_mode") is True:
        return True
    return identity.get("simulation_mode") == "route"


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


def _speed_command(ac, data, level):
    speed_ctrl = _safe_dict(_safe_dict(data.get("control")).get("speed"))
    if not speed_ctrl.get("can_issue_now", False):
        return None

    cmd_knots = float(_num(speed_ctrl.get("command_knots"), 100.0))
    free_knots = float(_num(speed_ctrl.get("default_free_knots"), cmd_knots))
    min_knots = float(_num(speed_ctrl.get("allowed_min_knots"), 60.0))
    max_knots = float(_num(speed_ctrl.get("allowed_max_knots"), 120.0))

    if level < 0.33:
        target_knots = free_knots * 0.78
    elif level < 0.66:
        target_knots = free_knots * 0.92
    else:
        target_knots = free_knots * 1.05

    target_knots = _clamp(target_knots, min_knots, max_knots)
    if abs(target_knots - cmd_knots) < 1.0:
        return None

    return {
        "action": "set_speed",
        "id": int(ac["id"]),
        "speed": round(target_knots, 1),
    }


def _overtake_command(ac, data, level):
    status = _safe_dict(data.get("status"))
    control = _safe_dict(data.get("control"))
    overtake_ctrl = _safe_dict(control.get("overtake"))
    spacing = _safe_dict(data.get("spacing"))

    if not overtake_ctrl.get("supported", False):
        return None
    if not overtake_ctrl.get("can_issue_now", False):
        return None

    wait_reason = status.get("wait_reason")
    if wait_reason in ["fifo_hold", "node_hold", "merge_hold", "start_hold"]:
        return None

    target_id = overtake_ctrl.get("candidate_target_aircraft_id")
    gap = spacing.get("forward_flow_gap_m")
    if target_id is None or gap is None:
        return None
    if gap > 1400.0:
        return None

    offset_m = 110.0 if not _route_mode(ac) else 130.0
    boost_knots = 12.0

    if level < 0.33:
        offset_m += 0.0
        boost_knots += 0.0
    elif level < 0.66:
        offset_m += 15.0
        boost_knots += 3.0
    else:
        offset_m += 30.0
        boost_knots += 6.0

    if gap < 800.0:
        offset_m += 10.0
        boost_knots += 2.0

    return {
        "action": "overtake",
        "id": int(ac["id"]),
        "target_id": int(target_id),
        "lateral_offset_m": round(offset_m, 1),
        "speed_boost_knots": round(boost_knots, 1),
    }


def _turn_command(ac, data, level):
    control = _safe_dict(data.get("control"))
    turn_ctrl = _safe_dict(control.get("turn"))

    if not turn_ctrl.get("supported", False):
        return None
    if not turn_ctrl.get("can_issue_now", False):
        return None

    if level < 0.33:
        diameter_m = 620.0
    elif level < 0.66:
        diameter_m = 720.0
    else:
        diameter_m = 820.0

    return {
        "action": "turn",
        "id": int(ac["id"]),
        "diameter_m": round(diameter_m, 1),
    }


def control_step(state):
    commands = []
    notes = []
    issued_ids = set()

    sim_time_s = float(_num(state.get("t"), 0.0))
    decision_tick = int(sim_time_s / 2.0)

    for ac in state.get("aircraft", []):
        if len(commands) >= 256:
            break
        if not _can_manage(ac):
            continue

        ac_id = int(ac["id"])
        if ac_id in issued_ids:
            continue

        data = _safe_dict(ac.get("data"))
        base_seed = decision_tick * 0.73 + ac_id * 1.917
        action_roll = _noise(base_seed)
        level_roll = _noise(base_seed + 9.731)
        issue_roll = _noise(base_seed + 21.173)

        command = None
        label = None

        if issue_roll < 0.38:
            continue

        if action_roll < 0.05:
            command = _turn_command(ac, data, level_roll)
            label = "turn"
        elif action_roll < 0.48:
            command = _overtake_command(ac, data, level_roll)
            label = "overtake"
        elif action_roll < 0.86:
            command = _speed_command(ac, data, level_roll)
            label = "speed"
        else:
            command = _overtake_command(ac, data, level_roll)
            label = "overtake"
            if command is None:
                command = _speed_command(ac, data, level_roll)
                label = "speed"

        if command is None:
            continue

        commands.append(command)
        notes.append("ac {} random_{}".format(ac_id, label))
        issued_ids.add(ac_id)

    return {
        "commands": commands,
        "params": {},
        "notes": notes,
    }
