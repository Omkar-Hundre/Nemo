"""Microsoft Natural Neural Voice Text-to-Speech Engine for NEMO."""

# 1. Standard library imports
import asyncio
import ctypes
import os
from pathlib import Path
import tempfile
import time

# 2. Third-party imports
import edge_tts

# 3. Local / internal imports
# (None)

# 4. Types, Protocols, Schemas
# (None)

# 5. Core logic / classes / functions
class VoiceSpeaker:
    """Generates and plays natural Microsoft Neural speech using edge-tts and native Windows WinMM."""

    VOICE_MAP: dict[str, str] = {
        "jenny": "en-US-JennyNeural",
        "guy": "en-US-GuyNeural",
        "aria": "en-US-AriaNeural",
        "prabhat": "en-IN-PrabhatNeural",
        "neerja": "en-IN-NeerjaNeural",
        "christopher": "en-US-ChristopherNeural",
        "sonia": "en-GB-SoniaNeural",
        "ryan": "en-GB-RyanNeural",
    }

    DEFAULT_VOICE = "en-US-JennyNeural"
    DEFAULT_RATE = "+15%"

    def __init__(self, default_voice: str = DEFAULT_VOICE, default_rate: str = DEFAULT_RATE) -> None:
        self.default_voice = self.resolve_voice(default_voice)
        self.default_rate = default_rate

    @classmethod
    def resolve_voice(cls, name_or_alias: str) -> str:
        """Resolve short persona alias (e.g. 'jenny', 'guy') to full Microsoft Neural voice ID."""
        key = name_or_alias.lower().strip()
        return cls.VOICE_MAP.get(key, name_or_alias)

    async def generate_speech(
        self,
        text: str,
        voice: str | None = None,
        rate: str | None = None,
        output_file: Path | str | None = None,
    ) -> Path:
        """Synthesize natural speech audio to an MP3 file."""
        selected_voice = self.resolve_voice(voice) if voice else self.default_voice
        selected_rate = rate or self.default_rate

        if output_file:
            out_path = Path(output_file).resolve()
        else:
            fd, tmp_path = tempfile.mkstemp(prefix="nemo_voice_", suffix=".mp3")
            os.close(fd)
            out_path = Path(tmp_path)

        communicate = edge_tts.Communicate(text, voice=selected_voice, rate=selected_rate)
        await communicate.save(str(out_path))
        return out_path

    def play_audio(self, file_path: Path | str, wait: bool = True) -> bool:
        """Play MP3 audio file through native Windows Multimedia API (winmm.dll) without external players."""
        resolved = Path(file_path).resolve()
        if not resolved.exists():
            return False

        try:
            winmm = ctypes.windll.winmm
            alias = f"nemo_tts_{os.getpid()}_{int(time.time() * 1000)}"

            # Open media device
            open_cmd = f'open "{resolved.as_posix()}" type mpegvideo alias {alias}'
            res_open = winmm.mciSendStringW(open_cmd, None, 0, None)
            if res_open != 0:
                return False

            # Play audio
            wait_flag = " wait" if wait else ""
            res_play = winmm.mciSendStringW(f"play {alias}{wait_flag}", None, 0, None)

            # Close media device
            winmm.mciSendStringW(f"close {alias}", None, 0, None)
            return res_play == 0

        except Exception:
            return False

    async def speak(
        self,
        text: str,
        voice: str | None = None,
        rate: str | None = None,
        wait: bool = True,
    ) -> bool:
        """Synthesize speech and play immediately, automatically cleaning up temporary files."""
        if not text or not text.strip():
            return False

        audio_path = None
        try:
            audio_path = await self.generate_speech(text=text, voice=voice, rate=rate)
            # Run blocking WinMM playback in background thread if wait=False, or directly if wait=True
            if wait:
                return self.play_audio(audio_path, wait=True)
            else:
                loop = asyncio.get_running_loop()
                loop.run_in_executor(None, self.play_audio, audio_path, True)
                return True
        except Exception:
            return False
        finally:
            if audio_path and audio_path.exists() and wait:
                try:
                    audio_path.unlink(missing_ok=True)
                except Exception:
                    pass


# 6. Public exports
__all__ = ["VoiceSpeaker"]
