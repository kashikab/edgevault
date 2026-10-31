"""
EdgeVault FAKE hub (Siddharth's dev server)

Pretends to be the 4 cameras so the dashboard can be built and demoed
before the real camera code exists. Later, the real cameras will POST
their events to /event and this file keeps working as the real hub.

Run:  python server.py          (listens on http://localhost:9000)
"""
import asyncio
import random
import time

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

CAPACITY_MB = 100
CAMS = ["cam1", "cam2", "cam3", "cam4"]
CAM_NAMES = {"cam1": "Front Door", "cam2": "Hallway", "cam3": "Server Room", "cam4": "Parking"}

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# ---------- shared state ----------
state = {
    "cams": {
        c: {"name": CAM_NAMES[c], "online": True, "used_mb": random.randint(15, 40),
            "capacity_mb": CAPACITY_MB, "last_score": 0.1, "status": "calm"}
        for c in CAMS
    },
    "ledger": {c: 100.0 for c in CAMS},       # fake credits
    "stored_for_others": {c: 0 for c in CAMS},  # MB of other cameras' clips held here
}
log = []            # last events
clients = set()     # connected websockets
clip_counter = 0


async def broadcast(kind, data):
    dead = []
    for ws in clients:
        try:
            await ws.send_json({"kind": kind, "data": data})
        except Exception:
            dead.append(ws)
    for ws in dead:
        clients.discard(ws)


async def emit(cam, type_, msg, score=None, **extra):
    """type_: perceive | reason | bid | transfer | evict | compress | audit | alert | offline"""
    event = {"ts": time.strftime("%H:%M:%S"), "cam": cam, "type": type_, "msg": msg,
             "score": score, **extra}
    log.append(event)
    del log[:-200]
    await broadcast("event", event)
    await broadcast("state", state)


def next_clip():
    global clip_counter
    clip_counter += 1
    return f"c{clip_counter}"


# ---------- scripted scenarios ----------
async def calm_tick():
    cam = random.choice([c for c in CAMS if state["cams"][c]["online"]])
    clip = next_clip()
    score = round(random.uniform(0.02, 0.2), 2)
    state["cams"][cam]["last_score"] = score
    state["cams"][cam]["status"] = "calm"
    await emit(cam, "perceive", f"{clip}: empty hallway, no person", score)
    await emit(cam, "evict", f"{clip}: low score, deleted (-2 MB)", score)


async def intruder(cam="cam1"):
    c = state["cams"][cam]
    clip = next_clip()
    c["status"] = "alert"
    c["last_score"] = 0.91
    await emit(cam, "perceive", f"{clip}: YOLO sees 1 person at restricted door", 0.91)
    await asyncio.sleep(0.8)
    await emit(cam, "reason", f"Gemini: threat 0.91. Disk {c['used_mb']}% full. Decision: keep clip", 0.91)
    await asyncio.sleep(0.8)

    if c["used_mb"] < 85:
        c["used_mb"] += 20
        await emit(cam, "alert", f"{clip}: stored locally (+20 MB)", 0.91)
        return

    await emit(cam, "reason", "Disk nearly full. Calling auction_remote_storage", 0.91)
    peers = [p for p in CAMS if p != cam and state["cams"][p]["online"]]
    bids = {}
    for p in peers:
        free = CAPACITY_MB - state["cams"][p]["used_mb"]
        if free >= 20:
            bids[p] = round(random.uniform(0.8, 2.0), 2)
            await emit(p, "bid", f"Bid {bids[p]} credits for {clip} ({free} MB free)", cam_from=cam)
            await asyncio.sleep(0.5)
    if not bids:
        c["status"] = "alert"
        await emit(cam, "compress", f"{clip}: no peer has space, compressed 50%", 0.91)
        return

    winner = min(bids, key=bids.get)
    price = bids[winner]
    await emit(cam, "transfer", f"{clip}: encrypted and sent to {winner} for {price} credits", 0.91, to=winner)
    state["cams"][cam]["used_mb"] = max(0, c["used_mb"] - 20)
    state["cams"][winner]["used_mb"] += 20
    state["stored_for_others"][winner] += 20
    state["ledger"][cam] = round(state["ledger"][cam] - price, 2)
    state["ledger"][winner] = round(state["ledger"][winner] + price, 2)
    await emit(winner, "audit", f"Audit scheduled for {clip} (hash challenge in 10 s)")
    await asyncio.sleep(2)
    await emit(winner, "audit", f"{clip}: hash proof PASSED")


async def disk_full(cam="cam1"):
    state["cams"][cam]["used_mb"] = 95
    state["cams"][cam]["status"] = "full"
    await emit(cam, "alert", "Storage at 95%")


async def toggle_cam(cam):
    c = state["cams"][cam]
    c["online"] = not c["online"]
    c["status"] = "calm" if c["online"] else "offline"
    await emit(cam, "offline" if not c["online"] else "alert",
               "Camera went OFFLINE" if not c["online"] else "Camera back ONLINE")


async def reset():
    for c in CAMS:
        state["cams"][c].update(online=True, used_mb=random.randint(15, 40), last_score=0.1, status="calm")
        state["ledger"][c] = 100.0
        state["stored_for_others"][c] = 0
    log.clear()
    await broadcast("state", state)
    await emit("hub", "alert", "Demo reset")


# ---------- HTTP endpoints ----------
@app.get("/state")
def get_state():
    return {"state": state, "log": log}


@app.post("/trigger/intruder")
async def trigger_intruder(cam: str = "cam1"):
    asyncio.create_task(intruder(cam))
    return {"ok": True}


@app.post("/trigger/disk_full")
async def trigger_disk_full(cam: str = "cam1"):
    await disk_full(cam)
    return {"ok": True}


@app.post("/trigger/toggle/{cam}")
async def trigger_toggle(cam: str):
    await toggle_cam(cam)
    return {"ok": True}


@app.post("/trigger/reset")
async def trigger_reset():
    await reset()
    return {"ok": True}


@app.post("/event")
async def receive_event(body: dict):
    """Real cameras will POST here later: {"cam","type","msg","score"}"""
    extra = {k: body[k] for k in ("to", "cam_from") if k in body}   # e.g. {"to": "cam4"} on a transfer
    await emit(body.get("cam", "?"), body.get("type", "perceive"), body.get("msg", ""), body.get("score"), **extra)
    return {"ok": True}


@app.post("/camera_state")
async def camera_state(body: dict):
    """Real cameras send their numbers here: used_mb, last_score, status, online, credits, hosted_mb, thumb_url"""
    cam = body.get("cam")
    if cam not in state["cams"]:
        return {"ok": False, "error": f"unknown camera {cam}"}
    c = state["cams"][cam]
    for k in ("used_mb", "online", "last_score", "status", "thumb_url"):
        if k in body:
            c[k] = body[k]
    if "credits" in body:
        state["ledger"][cam] = body["credits"]
    if "hosted_mb" in body:
        state["stored_for_others"][cam] = body["hosted_mb"]
    await broadcast("state", state)
    return {"ok": True}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket):
    await ws.accept()
    clients.add(ws)
    await ws.send_json({"kind": "state", "data": state})
    await ws.send_json({"kind": "history", "data": log})
    try:
        while True:
            await ws.receive_text()   # keep the connection open
    except WebSocketDisconnect:
        clients.discard(ws)


# ---------- background: calm activity ----------
@app.on_event("startup")
async def startup():
    async def loop():
        while True:
            await asyncio.sleep(4)
            if clients:
                await calm_tick()
    asyncio.create_task(loop())


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=9000)
