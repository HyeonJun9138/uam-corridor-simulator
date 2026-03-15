"""
FastAPI + WebSocket server for UAM Corridor Simulation.
"""
import asyncio
import io
import json
import socket
import time
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Optional

try:
    from .external_logic_ai import build_logic_review
    from .external_logic import ExternalLogicController
    from .simulation import SimulationEngine, SimParams
except ImportError:
    from external_logic_ai import build_logic_review
    from external_logic import ExternalLogicController
    from simulation import SimulationEngine, SimParams


FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
PROMPT_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "EXTERNAL_LOGIC_PROMPT_TEMPLATE.md"
ROOT_DIR = Path(__file__).resolve().parent.parent

EXTERNAL_LOGIC_DOWNLOADS = {
    "sample": ROOT_DIR / "EXTERNAL_LOGIC_SAMPLE_ADAPTIVE_GUARD.py",
    "prompt": ROOT_DIR / "EXTERNAL_LOGIC_PROMPT_TEMPLATE.md",
    "api-guide": ROOT_DIR / "EXTERNAL_API_GUIDE.md",
    "schema": ROOT_DIR / "AIRCRAFT_DATA_SCHEMA.md",
}

EXTERNAL_LOGIC_KITS = {
    "starter": {
        "filename": "external_logic_starter_kit.zip",
        "files": ["sample", "prompt"],
    },
    "api": {
        "filename": "external_logic_api_kit.zip",
        "files": ["api-guide", "schema"],
    },
}

# Global simulation state
sim_engine = SimulationEngine(SimParams())
external_logic = ExternalLogicController()
sim_running = False
sim_task: Optional[asyncio.Task] = None
connected_clients: List[WebSocket] = []
STATE_PUSH_INTERVAL_S = 1.0 / 20.0


@asynccontextmanager
async def lifespan(app):
    yield
    global sim_task
    if sim_task:
        sim_task.cancel()


app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/external-logic-prompt-template", response_class=PlainTextResponse)
async def get_external_logic_prompt_template():
    return PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")


@app.get("/api/external-logic-download/{file_key}")
async def download_external_logic_file(file_key: str):
    path = EXTERNAL_LOGIC_DOWNLOADS.get(file_key)
    if path is None or not path.exists():
        raise HTTPException(status_code=404, detail="download file not found")
    return FileResponse(
        path,
        filename=path.name,
        media_type="application/octet-stream",
    )


@app.get("/api/external-logic-kit/{kit_key}.zip")
async def download_external_logic_kit(kit_key: str):
    kit = EXTERNAL_LOGIC_KITS.get(kit_key)
    if kit is None:
        raise HTTPException(status_code=404, detail="download kit not found")

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_key in kit["files"]:
            path = EXTERNAL_LOGIC_DOWNLOADS[file_key]
            archive.writestr(path.name, path.read_bytes())
    buffer.seek(0)

    headers = {
        "Content-Disposition": f'attachment; filename="{kit["filename"]}"',
    }
    return StreamingResponse(buffer, media_type="application/zip", headers=headers)


async def broadcast(data: dict):
    msg = json.dumps(data)
    disconnected = []
    for ws in connected_clients:
        try:
            await ws.send_text(msg)
        except Exception:
            disconnected.append(ws)
    for ws in disconnected:
        if ws in connected_clients:
            connected_clients.remove(ws)


def build_state_payload(show_density: bool = True, show_congestion: bool = True,
                        show_segments: bool = True) -> dict:
    state = sim_engine.get_full_state(
        show_density=show_density,
        show_congestion=show_congestion,
        show_segments=show_segments,
    )
    state["external_logic"] = external_logic.get_status()
    return state


def apply_param_updates(params: dict) -> dict:
    p = sim_engine.p
    applied = {}
    errors = []
    for key, val in params.items():
        if not hasattr(p, key):
            errors.append(f"unknown param: {key}")
            continue
        current = getattr(p, key)
        try:
            if isinstance(current, bool):
                if isinstance(val, str):
                    parsed = val.strip().lower() in {"1", "true", "yes", "on"}
                else:
                    parsed = bool(val)
            elif isinstance(current, int) and not isinstance(current, bool):
                parsed = int(val)
            elif isinstance(current, float):
                parsed = float(val)
            elif isinstance(current, str):
                parsed = str(val)
            else:
                parsed = type(current)(val)
        except (TypeError, ValueError) as exc:
            errors.append(f"{key}: {exc}")
            continue
        setattr(p, key, parsed)
        applied[key] = parsed
    sigpar_max = max(2.0 * p.sep_min_m, 50.0)
    if p.sigma_parallel_m > sigpar_max:
        p.sigma_parallel_m = sigpar_max
    sim_engine.normalize_model_params()
    for key in list(applied.keys()):
        applied[key] = getattr(p, key)
    return {"applied": applied, "errors": errors}


def apply_control_command(command: dict) -> dict:
    action = str(command.get("action", "")).strip().lower()
    if action == "set_speed":
        ac_id = command.get("id")
        speed = command.get("speed")
        if ac_id is None or speed is None:
            return {"ok": False, "reason": "set_speed requires id and speed"}
        sim_engine.set_aircraft_speed(int(ac_id), float(speed))
        return {"ok": True}
    if action == "turn":
        ac_id = command.get("id")
        diameter_m = command.get("diameter_m", 800)
        if ac_id is None:
            return {"ok": False, "reason": "turn requires id"}
        return {"ok": bool(sim_engine.command_turn(int(ac_id), float(diameter_m)))}
    if action == "overtake":
        ac_id = command.get("id")
        if ac_id is None:
            return {"ok": False, "reason": "overtake requires id"}
        ok = sim_engine.command_overtake(
            int(ac_id),
            float(command.get("lateral_offset_m", 100)),
            float(command.get("speed_boost_knots", 20)),
            command.get("target_id"),
        )
        return {"ok": bool(ok)}
    if action == "spawn":
        ac_id = sim_engine.spawn_aircraft(start_node_id=command.get("start_node_id"))
        return {"ok": ac_id is not None, "spawned_id": ac_id}
    if action == "delete":
        ac_id = command.get("id")
        if ac_id is None:
            return {"ok": False, "reason": "delete requires id"}
        sim_engine.delete_aircraft(int(ac_id))
        return {"ok": True}
    if action == "update_params":
        params = command.get("params", {})
        if not isinstance(params, dict):
            return {"ok": False, "reason": "update_params requires params"}
        report = apply_param_updates(params)
        return {"ok": not report["errors"], "report": report}
    return {"ok": False, "reason": f"unsupported action: {action}"}


def run_external_logic_step():
    if not external_logic.active:
        return
    logic_state = build_state_payload(show_density=False, show_congestion=False, show_segments=True)
    result = external_logic.run_step(logic_state)
    if not result.get("ok"):
        return
    params = result.get("params", {})
    if params:
        apply_param_updates(params)
    for command in result.get("commands", []):
        apply_control_command(command)


async def sim_loop():
    global sim_running
    last_tick = time.perf_counter()
    last_push = 0.0
    accumulated_sim_s = 0.0
    while sim_running:
        now = time.perf_counter()
        real_dt = max(0.0, now - last_tick)
        last_tick = now
        playback = max(0.1, sim_engine.p.realtime_factor)
        step_dt = max(float(sim_engine.p.dt_s), 1e-6)
        accumulated_sim_s = min(accumulated_sim_s + real_dt * playback, step_dt * 120.0)

        steps = 0
        while accumulated_sim_s + 1e-12 >= step_dt and steps < 120:
            run_external_logic_step()
            sim_engine.attempt_auto_spawn()
            sim_engine.step()
            accumulated_sim_s -= step_dt
            steps += 1

        if steps > 0 and (now - last_push >= STATE_PUSH_INTERVAL_S):
            state = build_state_payload(
                show_density=True,
                show_congestion=True,
                show_segments=True,
            )
            state["type"] = "state"
            await broadcast(state)
            last_push = time.perf_counter()

        await asyncio.sleep(0.016)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    global sim_running, sim_task
    await ws.accept()
    connected_clients.append(ws)

    # Send initial state
    state = build_state_payload()
    state["type"] = "state"
    await ws.send_text(json.dumps(state))

    try:
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            action = msg.get("action")

            if action == "start":
                if not sim_running:
                    sim_running = True
                    sim_task = asyncio.create_task(sim_loop())
                await broadcast({"type": "status", "running": True})

            elif action == "pause":
                sim_running = False
                if sim_task:
                    sim_task.cancel()
                    sim_task = None
                await broadcast({"type": "status", "running": False})

            elif action == "reset":
                sim_running = False
                if sim_task:
                    sim_task.cancel()
                    sim_task = None
                sim_engine.reset()
                state = build_state_payload()
                state["type"] = "state"
                await broadcast(state)
                await broadcast({"type": "status", "running": False})

            elif action == "spawn":
                start_node_id = msg.get("start_node_id")
                ac_id = sim_engine.spawn_aircraft(start_node_id=start_node_id)
                if ac_id is not None:
                    state = build_state_payload()
                    state["type"] = "state"
                    state["spawned_id"] = ac_id
                    await broadcast(state)

            elif action == "delete":
                ac_id = msg.get("id")
                if ac_id is not None:
                    sim_engine.delete_aircraft(ac_id)
                    state = build_state_payload()
                    state["type"] = "state"
                    await broadcast(state)

            elif action == "set_speed":
                ac_id = msg.get("id")
                speed = msg.get("speed")
                if ac_id is not None and speed is not None:
                    sim_engine.set_aircraft_speed(ac_id, speed)
                    if not sim_running:
                        state = build_state_payload()
                        state["type"] = "state"
                        await broadcast(state)

            elif action == "turn":
                ac_id = msg.get("id")
                diameter_m = msg.get("diameter_m", 800)
                if ac_id is not None and sim_engine.command_turn(ac_id, diameter_m):
                    state = build_state_payload()
                    state["type"] = "state"
                    await broadcast(state)

            elif action == "overtake":
                ac_id = msg.get("id")
                lateral_offset_m = msg.get("lateral_offset_m", 100)
                speed_boost_knots = msg.get("speed_boost_knots", 20)
                target_id = msg.get("target_id")
                if ac_id is not None and sim_engine.command_overtake(
                    ac_id,
                    lateral_offset_m,
                    speed_boost_knots,
                    target_id,
                ):
                    state = build_state_payload()
                    state["type"] = "state"
                    await broadcast(state)

            elif action == "update_params":
                params = msg.get("params", {})
                report = apply_param_updates(params)
                if not sim_running:
                    state = build_state_payload()
                    state["type"] = "state"
                    await broadcast(state)
                await broadcast({"type": "params_ack", "params": msg.get("params", {}), "report": report})

            elif action == "set_mode":
                sim_running = False
                if sim_task:
                    sim_task.cancel()
                    sim_task = None
                mode = msg.get("mode", "corridor")
                sim_engine.set_simulation_mode(mode)
                sim_engine.reset()
                state = build_state_payload()
                state["type"] = "state"
                await broadcast(state)
                await broadcast({"type": "status", "running": False})

            elif action == "toggle_route_link":
                start_id = msg.get("start_id")
                end_id = msg.get("end_id")
                if start_id and end_id and sim_engine.toggle_route_link(start_id, end_id):
                    sim_running = False
                    if sim_task:
                        sim_task.cancel()
                        sim_task = None
                    sim_engine.reset()
                    state = build_state_payload()
                    state["type"] = "state"
                    await broadcast(state)
                    await broadcast({"type": "status", "running": False})

            elif action == "clear_route_links":
                sim_running = False
                if sim_task:
                    sim_task.cancel()
                    sim_task = None
                sim_engine.clear_route_links()
                sim_engine.reset()
                state = build_state_payload()
                state["type"] = "state"
                await broadcast(state)
                await broadcast({"type": "status", "running": False})

            elif action == "reset_route_links":
                sim_running = False
                if sim_task:
                    sim_task.cancel()
                    sim_task = None
                sim_engine.reset_route_links()
                sim_engine.reset()
                state = build_state_payload()
                state["type"] = "state"
                await broadcast(state)
                await broadcast({"type": "status", "running": False})

            elif action == "step":
                # Single step
                run_external_logic_step()
                sim_engine.attempt_auto_spawn()
                sim_engine.step()
                state = build_state_payload()
                state["type"] = "state"
                await broadcast(state)

            elif action == "logic_get_status":
                await ws.send_text(json.dumps({"type": "logic_status", "logic": external_logic.get_status()}))

            elif action == "logic_analyze":
                code = str(msg.get("code", ""))
                analysis = external_logic.analyze(code)
                explanation = await asyncio.to_thread(
                    build_logic_review,
                    code,
                    analysis,
                    build_state_payload(show_density=False, show_congestion=False, show_segments=True),
                )
                if isinstance(explanation, dict):
                    analysis["explanation"] = explanation
                    external_logic.cache_analysis_explanation(code, explanation)
                await ws.send_text(json.dumps({"type": "logic_analysis", "analysis": analysis}))

            elif action == "logic_activate":
                code = str(msg.get("code", ""))
                auto_apply = bool(msg.get("auto_apply_detected_params", True))
                result = external_logic.activate(
                    code,
                    build_state_payload(show_density=False, show_congestion=False, show_segments=True),
                )
                param_report = {"applied": {}, "errors": []}
                if result.get("ok") and auto_apply:
                    detected_params = result.get("analysis", {}).get("detected_params", {})
                    if detected_params:
                        param_report = apply_param_updates(detected_params)
                state = build_state_payload()
                state["type"] = "state"
                await broadcast(state)
                await ws.send_text(json.dumps({
                    "type": "logic_activation",
                    "ok": bool(result.get("ok")),
                    "analysis": result.get("analysis"),
                    "logic": external_logic.get_status(),
                    "param_report": param_report,
                }))

            elif action == "logic_deactivate":
                logic = external_logic.deactivate()
                state = build_state_payload()
                state["type"] = "state"
                await broadcast(state)
                await ws.send_text(json.dumps({"type": "logic_status", "logic": logic}))

            elif action == "logic_apply_params":
                params = msg.get("params", {})
                report = {"applied": {}, "errors": ["params must be an object"]}
                if isinstance(params, dict):
                    report = apply_param_updates(params)
                    state = build_state_payload()
                    state["type"] = "state"
                    await broadcast(state)
                await ws.send_text(json.dumps({"type": "logic_params_applied", "params": params, "report": report}))

    except WebSocketDisconnect:
        pass
    finally:
        if ws in connected_clients:
            connected_clients.remove(ws)


def run():
    import uvicorn
    host = "0.0.0.0"
    port = _find_available_port(host=host, start_port=8000)
    if port != 8000:
        print(f"Port 8000 is in use. Starting server on port {port}.")
    print("Open one of these URLs:")
    for url in _get_access_urls(port):
        print(f"  {url}")
    uvicorn.run(app, host=host, port=port)


def _find_available_port(host: str, start_port: int, max_tries: int = 50) -> int:
    for port in range(start_port, start_port + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            try:
                sock.bind((host, port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No available port found in range {start_port}-{start_port + max_tries - 1}")


def _get_access_urls(port: int) -> List[str]:
    urls = [f"http://127.0.0.1:{port}", f"http://localhost:{port}"]

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
    except OSError:
        ip = None

    if ip and not ip.startswith("127."):
        urls.append(f"http://{ip}:{port}")

    seen = set()
    unique_urls = []
    for url in urls:
        if url not in seen:
            unique_urls.append(url)
            seen.add(url)
    return unique_urls


# Serve frontend
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

if __name__ == "__main__":
    run()
