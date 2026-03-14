"""
FastAPI + WebSocket server for UAM Corridor Simulation.
"""
import asyncio
import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import Optional

from simulation import SimulationEngine, SimParams

# Global simulation state
sim_engine = SimulationEngine(SimParams())
sim_running = False
sim_task: Optional[asyncio.Task] = None
connected_clients: list[WebSocket] = []


@asynccontextmanager
async def lifespan(app):
    yield
    global sim_task
    if sim_task:
        sim_task.cancel()


app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


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


async def sim_loop():
    global sim_running
    while sim_running:
        sim_engine.step()
        state = sim_engine.get_full_state(
            show_density=True,
            show_congestion=True,
            show_segments=True,
        )
        state["type"] = "state"
        await broadcast(state)

        playback = max(0.1, sim_engine.p.realtime_factor)
        interval = sim_engine.p.dt_s / playback
        await asyncio.sleep(max(0.016, interval))


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    global sim_running, sim_task
    await ws.accept()
    connected_clients.append(ws)

    # Send initial state
    state = sim_engine.get_full_state()
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
                state = sim_engine.get_full_state()
                state["type"] = "state"
                await broadcast(state)
                await broadcast({"type": "status", "running": False})

            elif action == "spawn":
                ac_id = sim_engine.spawn_aircraft()
                state = sim_engine.get_full_state()
                state["type"] = "state"
                state["spawned_id"] = ac_id
                await broadcast(state)

            elif action == "delete":
                ac_id = msg.get("id")
                if ac_id is not None:
                    sim_engine.delete_aircraft(ac_id)
                    state = sim_engine.get_full_state()
                    state["type"] = "state"
                    await broadcast(state)

            elif action == "set_speed":
                ac_id = msg.get("id")
                speed = msg.get("speed")
                if ac_id is not None and speed is not None:
                    sim_engine.set_aircraft_speed(ac_id, speed)
                    if not sim_running:
                        state = sim_engine.get_full_state()
                        state["type"] = "state"
                        await broadcast(state)

            elif action == "update_params":
                params = msg.get("params", {})
                p = sim_engine.p
                for key, val in params.items():
                    if hasattr(p, key):
                        setattr(p, key, type(getattr(p, key))(val))
                # Cap sigma_parallel to 2x sep_min
                sigpar_max = max(2.0 * p.sep_min_m, 50.0)
                if p.sigma_parallel_m > sigpar_max:
                    p.sigma_parallel_m = sigpar_max
                if not sim_running:
                    state = sim_engine.get_full_state()
                    state["type"] = "state"
                    await broadcast(state)
                await broadcast({"type": "params_ack", "params": msg.get("params", {})})

            elif action == "step":
                # Single step
                sim_engine.step()
                state = sim_engine.get_full_state()
                state["type"] = "state"
                await broadcast(state)

    except WebSocketDisconnect:
        pass
    finally:
        if ws in connected_clients:
            connected_clients.remove(ws)


# Serve frontend
app.mount("/", StaticFiles(directory="../frontend", html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
