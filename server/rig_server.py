"""
RigLink Network Server — CAT + Scope + Audio über WebSocket.
Läuft auf Raspi/PC, Client verbindet per Browser oder App.

Usage:
    python rig_server.py --port 8080 --rig ic705 --serial /dev/ttyACM0 --baud 115200
"""

import os
import sys
import json
import time
import asyncio
import argparse
import threading
from typing import Set

# RigLink Module
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.cat import create_cat_handler
from core.cat.icom import RIG_ADDRESSES

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.staticfiles import StaticFiles
    from fastapi.responses import FileResponse
    import uvicorn
except ImportError:
    print("pip install fastapi uvicorn")
    sys.exit(1)

app = FastAPI(title="RigLink Server")

# ── State ──────────────────────────────────────────────────────────

cat_handler = None
connected = False
clients: Set[WebSocket] = set()

# Live-Daten (werden vom Polling-Thread aktualisiert)
live_data = {
    "freq": 0,
    "mode": "",
    "smeter": 0,
    "power": 0,
    "spectrum": [],
    "scope_center": 0,
    "scope_span": 0,
    "preamp": "OFF",
}


# ── CAT Polling Thread ─────────────────────────────────────────────

def polling_loop():
    """Pollt den TRX wie die App (150ms Interval)."""
    global live_data
    count = 0
    while connected and cat_handler:
        count += 1
        try:
            # Scope (jeder Tick)
            if hasattr(cat_handler, '_flush_scope_from_serial'):
                cat_handler._flush_scope_from_serial()
            spectrum = cat_handler.scope_read()
            if spectrum:
                live_data["spectrum"] = spectrum
                sc = getattr(cat_handler, '_scope_center_hz', 0)
                ss = getattr(cat_handler, '_scope_span_hz', 0)
                if sc > 0:
                    live_data["scope_center"] = sc
                if ss > 0:
                    live_data["scope_span"] = ss

            # Frequenz (alle 5 Ticks)
            if count <= 10 or count % 5 == 0:
                freq = cat_handler.get_frequency()
                if freq:
                    live_data["freq"] = freq

            # S-Meter (alle 3 Ticks)
            if count % 3 == 0:
                raw = cat_handler.get_smeter()
                if raw is not None:
                    live_data["smeter"] = raw

            # Mode + Power (anfangs + alle 50 Ticks)
            if count <= 5 or count % 50 == 0:
                mode = cat_handler.get_mode()
                if mode:
                    live_data["mode"] = mode
                pwr = cat_handler.get_power_raw()
                if pwr is not None:
                    live_data["power"] = pwr
                preamp = cat_handler.get_preamp()
                if preamp:
                    live_data["preamp"] = preamp

        except Exception as e:
            print(f"Polling error: {e}")

        time.sleep(0.1)


# ── WebSocket Broadcast ────────────────────────────────────────────

async def broadcast_loop():
    """Sendet Live-Daten an alle verbundenen Clients (80ms)."""
    global clients
    while True:
        if len(clients) > 0 and connected:
            msg = json.dumps(live_data, separators=(',', ':'))
            dead = set()
            for ws in clients.copy():
                try:
                    await ws.send_text(msg)
                except Exception:
                    dead.add(ws)
            clients -= dead
        await asyncio.sleep(0.08)


# ── API Endpoints ──────────────────────────────────────────────────

@app.get("/api/status")
async def get_status():
    return {"connected": connected, "data": live_data}


@app.post("/api/connect")
async def connect_rig(config: dict = None):
    global cat_handler, connected

    if connected:
        return {"ok": False, "error": "Already connected"}

    cfg = config or {}
    rig = cfg.get("rig", "ic705")
    port = cfg.get("port", "/dev/ttyACM0")
    baud = cfg.get("baud", 115200)
    stop_bits = cfg.get("stop_bits", 2)

    civ_addr = RIG_ADDRESSES.get(rig, 0xA4)

    cat_handler = create_cat_handler(
        "icom",
        port=port,
        baud=baud,
        data_bits=8,
        stop_bits=stop_bits,
        parity="N",
        timeout=0.5,
        civ_address=civ_addr
    )

    ok = cat_handler.connect()
    if ok:
        connected = True
        threading.Thread(target=polling_loop, daemon=True).start()
        return {"ok": True, "rig": rig, "port": port, "baud": baud}
    else:
        cat_handler = None
        return {"ok": False, "error": "Connection failed"}


@app.post("/api/disconnect")
async def disconnect_rig():
    global cat_handler, connected
    connected = False
    if cat_handler:
        cat_handler.disconnect()
        cat_handler = None
    return {"ok": True}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    clients.add(ws)
    print(f"Client connected ({len(clients)} total)")
    try:
        while True:
            # Empfange Commands vom Client (Read-Only → ignorieren)
            data = await ws.receive_text()
            # Für später: hier könnten Tune-Commands reinkommen
    except WebSocketDisconnect:
        clients.discard(ws)
        print(f"Client disconnected ({len(clients)} total)")


# Static files (CSS, JS, HTML) — muss NACH allen API routes kommen
docs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs")
if os.path.isdir(docs_dir):
    app.mount("/", StaticFiles(directory=docs_dir, html=True), name="static")


# ── Startup ────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    asyncio.create_task(broadcast_loop())


def main():
    parser = argparse.ArgumentParser(description="RigLink Network Server")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address")
    parser.add_argument("--port", type=int, default=8080, help="HTTP port")
    parser.add_argument("--rig", default="ic705", help="Rig type")
    parser.add_argument("--serial", default="/dev/ttyACM0", help="Serial port")
    parser.add_argument("--baud", type=int, default=115200, help="Baud rate")
    parser.add_argument("--auto-connect", action="store_true", help="Auto-connect on startup")
    args = parser.parse_args()

    if args.auto_connect:
        _auto_cfg = {"rig": args.rig, "port": args.serial, "baud": args.baud}
        @app.on_event("startup")
        async def auto_connect():
            await connect_rig(_auto_cfg)

    print(f"RigLink Server starting on http://{args.host}:{args.port}")
    print(f"Rig: {args.rig} | Serial: {args.serial} @ {args.baud}")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
