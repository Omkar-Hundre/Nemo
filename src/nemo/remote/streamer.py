"""High-performance Screen Streaming Server for Nemo.

Enables ultra-low-latency (30-60ms) 720p live screen streaming from Windows PC
to any mobile phone browser over WebSocket and HTTP MJPEG (LAN direct).
Zero cloud exposure: All screen video frames stream strictly peer-to-peer over local network.
"""

import asyncio
import base64
import io
import json
import logging
import socket
import threading
import time
from typing import Any, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import uvicorn

from nemo.tools.builtin import capture_screen_optimized_jpeg_b64

logger = logging.getLogger(__name__)

app = FastAPI(title="Nemo Screen Streamer")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

connected_clients: Set[WebSocket] = set()


def get_local_ip() -> str:
    """Detect the PC's primary LAN IP address (192.168.x.x)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "nemo-screen-streamer",
        "local_ip": get_local_ip(),
        "active_viewers": len(connected_clients),
        "resolution": "1280x720",
    }


@app.get("/frame.jpg")
async def get_raw_frame():
    """Return single fresh 720p JPEG frame directly."""
    b64 = await asyncio.to_thread(capture_screen_optimized_jpeg_b64, 1280, 65)
    if not b64:
        return Response(status_code=503)
    raw_bytes = base64.b64decode(b64)
    return Response(content=raw_bytes, media_type="image/jpeg")


@app.get("/live.mjpg")
async def live_mjpeg_stream():
    """Direct HTTP multipart MJPEG stream - supported natively by all mobile browsers with 0 plugins."""
    async def frame_generator():
        while True:
            t0 = time.time()
            b64_frame = await asyncio.to_thread(capture_screen_optimized_jpeg_b64, 1280, 65)
            if b64_frame:
                raw_bytes = base64.b64decode(b64_frame)
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + raw_bytes + b"\r\n"
                )
            elapsed = time.time() - t0
            await asyncio.sleep(max(0.01, 0.05 - elapsed))

    return StreamingResponse(
        frame_generator(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.websocket("/stream")
async def websocket_stream(websocket: WebSocket):
    await websocket.accept()
    connected_clients.add(websocket)
    logger.info("Mobile phone connected to WebSocket live stream (%s)", websocket.client)

    fps = 15
    quality = 65
    is_running = True

    async def receive_controls():
        nonlocal fps, quality, is_running
        try:
            while is_running:
                data = await websocket.receive_text()
                try:
                    msg = json.loads(data)
                    if msg.get("action") == "set_fps":
                        fps = max(1, min(30, int(msg.get("value", 15))))
                    elif msg.get("action") == "set_quality":
                        quality = max(30, min(95, int(msg.get("value", 65))))
                    elif msg.get("action") == "pause":
                        is_running = False
                except Exception:
                    pass
        except WebSocketDisconnect:
            is_running = False
        except Exception:
            is_running = False

    control_task = asyncio.create_task(receive_controls())

    try:
        while is_running:
            start_t = time.time()
            b64_frame = await asyncio.to_thread(capture_screen_optimized_jpeg_b64, 1280, quality)
            if b64_frame:
                frame_payload = {
                    "type": "frame",
                    "data": b64_frame,
                    "ts": time.time(),
                }
                await websocket.send_text(json.dumps(frame_payload))

            elapsed = time.time() - start_t
            target_delay = 1.0 / max(1, fps)
            sleep_time = max(0.01, target_delay - elapsed)
            await asyncio.sleep(sleep_time)

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.debug("Stream error: %s", exc)
    finally:
        is_running = False
        control_task.cancel()
        connected_clients.discard(websocket)
        logger.info("Mobile phone disconnected from stream.")


_server_started = False
_server_lock = threading.Lock()


def _detect_ws_protocol() -> str:
    """Detect available websocket implementation to prevent ModuleNotFoundError."""
    try:
        import wsproto
        return "wsproto"
    except ImportError:
        try:
            import websockets
            return "websockets"
        except ImportError:
            return "none"


def run_streaming_server(host: str = "0.0.0.0", port: int = 8765):
    """Run Uvicorn streaming server with graceful websocket fallback."""
    local_ip = get_local_ip()
    ws_protocol = _detect_ws_protocol()
    logger.info("Starting Nemo Screen Streamer on ws://%s:%d/stream & http://%s:%d/live.mjpg (ws=%s)", host, port, host, port, ws_protocol)
    try:
        config = uvicorn.Config(app=app, host=host, port=port, ws=ws_protocol, log_level="warning")
        server = uvicorn.Server(config)
        server.run()
    except Exception as exc:
        logger.warning("Nemo Screen Streamer server encountered an error: %s", exc)


def start_streaming_server_thread(host: str = "0.0.0.0", port: int = 8765) -> threading.Thread | None:
    """Start streaming server in a daemon thread (singleton)."""
    global _server_started
    with _server_lock:
        if _server_started:
            return None
        _server_started = True

    t = threading.Thread(target=run_streaming_server, args=(host, port), daemon=True, name="NemoScreenStreamer")
    t.start()
    return t
