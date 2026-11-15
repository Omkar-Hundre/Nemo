"""Worldwide Device-Locked Cloud Stream Broadcaster for Nemo.

Enables secure, real-time screen streaming to an authorized mobile phone from anywhere
in the world via Supabase cloud sync, with zero local or public IP exposure.
Only the user's phone with the matching Device Key can view the live screen.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import threading
import time
import urllib.parse
import urllib.request
from typing import Any

from nemo.config.settings import get_settings
from nemo.remote.auth import get_device_key
from nemo.tools.builtin import capture_screen_optimized_jpeg_b64

logger = logging.getLogger(__name__)


class NemoCloudStreamer:
    """Streams live 720p/540p desktop frames to authorized phone when viewer is active."""

    def __init__(self, fps: float = 2.0, resolution: int = 1024, quality: int = 50) -> None:
        settings = get_settings()
        self.supabase_url = settings.supabase_url.rstrip("/")
        self.supabase_key = settings.supabase_key
        self.device_key = get_device_key()
        self.fps = max(0.5, min(5.0, fps))
        self.resolution = resolution
        self.quality = quality
        self._stop_event = threading.Event()
        self._frame_seq = 0
        self._is_active = False

    def _headers(self) -> dict[str, str]:
        return {
            "apikey": self.supabase_key,
            "Authorization": f"Bearer {self.supabase_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def register_device(self) -> bool:
        """Register current device_key in Supabase nemo_device_stream table."""
        url = f"{self.supabase_url}/rest/v1/nemo_device_stream?id=eq.primary"
        now_iso = datetime.now(timezone.utc).isoformat()
        body = {
            "device_key": self.device_key,
            "updated_at": now_iso,
        }
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=self._headers(), method="PATCH")
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                success = 200 <= resp.status < 300
                if success:
                    logger.info("Nemo live stream registered with device key: %s", self.device_key)
                return success
        except Exception as exc:
            logger.debug("Failed to register device key in Supabase: %s", exc)
            return False

    def check_viewer_active(self) -> bool:
        """Check if an authorized viewer with matching device_key is active on the stream."""
        params = urllib.parse.urlencode({
            "id": "eq.primary",
            "device_key": f"eq.{self.device_key}",
            "select": "viewer_active_at,frame_seq",
        })
        url = f"{self.supabase_url}/rest/v1/nemo_device_stream?{params}"
        req = urllib.request.Request(url, headers=self._headers(), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                if 200 <= resp.status < 300:
                    payload = resp.read().decode("utf-8")
                    rows = json.loads(payload) if payload else []
                    if rows and rows[0].get("viewer_active_at"):
                        active_str = rows[0]["viewer_active_at"]
                        active_dt = datetime.fromisoformat(active_str.replace("Z", "+00:00"))
                        now = datetime.now(timezone.utc)
                        delta = (now - active_dt).total_seconds()
                        return delta < 6.0
        except Exception:
            pass
        return False

    def push_frame(self, frame_b64: str) -> bool:
        """Push a fresh frame to Supabase."""
        self._frame_seq += 1
        query = urllib.parse.urlencode({
            "id": "eq.primary",
            "device_key": f"eq.{self.device_key}",
        })
        url = f"{self.supabase_url}/rest/v1/nemo_device_stream?{query}"
        now_iso = datetime.now(timezone.utc).isoformat()
        body = {
            "frame_b64": frame_b64,
            "frame_seq": self._frame_seq,
            "updated_at": now_iso,
        }
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=self._headers(), method="PATCH")
        try:
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                return 200 <= resp.status < 300
        except Exception as exc:
            logger.debug("Failed to push screen frame to Supabase: %s", exc)
            return False

    def run_loop(self) -> None:
        """Continuous background streaming loop."""
        self.register_device()
        target_delay = 1.0 / self.fps

        while not self._stop_event.is_set():
            try:
                is_active = self.check_viewer_active()
                self._is_active = is_active

                if is_active:
                    t0 = time.time()
                    b64 = capture_screen_optimized_jpeg_b64(self.resolution, self.quality)
                    if b64:
                        self.push_frame(b64)
                    elapsed = time.time() - t0
                    sleep_time = max(0.05, target_delay - elapsed)
                    time.sleep(sleep_time)
                else:
                    # Idle sleep: phone is not viewing the stream
                    time.sleep(1.5)
            except Exception as exc:
                logger.debug("Cloud streamer loop error: %s", exc)
                time.sleep(2.0)

    def stop(self) -> None:
        """Stop the cloud streaming worker."""
        self._stop_event.set()


_cloud_streamer_instance: NemoCloudStreamer | None = None
_cloud_streamer_thread: threading.Thread | None = None
_cloud_streamer_lock = threading.Lock()


def start_cloud_streamer_thread(fps: float = 2.0) -> NemoCloudStreamer:
    """Start the worldwide cloud streaming worker thread (singleton)."""
    global _cloud_streamer_instance, _cloud_streamer_thread
    with _cloud_streamer_lock:
        if _cloud_streamer_instance is None:
            _cloud_streamer_instance = NemoCloudStreamer(fps=fps)
            _cloud_streamer_thread = threading.Thread(
                target=_cloud_streamer_instance.run_loop,
                daemon=True,
                name="NemoCloudStreamer",
            )
            _cloud_streamer_thread.start()
        return _cloud_streamer_instance
