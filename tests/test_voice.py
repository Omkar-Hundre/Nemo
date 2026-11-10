"""Production-grade test suite for Microsoft Natural Voice and SpeakTool."""

# 1. Standard library imports
import asyncio
from pathlib import Path
import tempfile

# 2. Third-party imports
import pytest

# 3. Local / internal imports
from nemo.tools.builtin import SpeakTool
from nemo.voice.speaker import VoiceSpeaker

# 4. Types, Protocols, Schemas
# (None)

# 5. Core logic / classes / functions
def test_voice_speaker_persona_mapping():
    """Verify short persona aliases resolve to Microsoft Neural voice names."""
    assert VoiceSpeaker.resolve_voice("jenny") == "en-US-JennyNeural"
    assert VoiceSpeaker.resolve_voice("guy") == "en-US-GuyNeural"
    assert VoiceSpeaker.resolve_voice("aria") == "en-US-AriaNeural"
    assert VoiceSpeaker.resolve_voice("prabhat") == "en-IN-PrabhatNeural"
    assert VoiceSpeaker.resolve_voice("neerja") == "en-IN-NeerjaNeural"
    # Fallback to direct name if unmapped
    assert VoiceSpeaker.resolve_voice("custom-voice-xyz") == "custom-voice-xyz"


@pytest.mark.asyncio
async def test_voice_speaker_synthesize_file():
    """Verify VoiceSpeaker synthesizes valid audio MP3 data using Microsoft Edge TTS."""
    speaker = VoiceSpeaker(default_voice="jenny", default_rate="+15%")

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        out = await speaker.generate_speech(
            text="Nemo developer runtime voice test.",
            voice="jenny",
            rate="+15%",
            output_file=tmp_path,
        )
        assert out.exists()
        assert out.stat().st_size > 1000  # Valid MP3 with audio headers and frames
    finally:
        tmp_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_speak_tool_definition():
    """Verify SpeakTool parameters and schema."""
    tool = SpeakTool()
    defn = tool.get_definition()
    assert defn.name == "voice_speak"
    assert "text" in defn.parameters["properties"]
    assert "voice" in defn.parameters["properties"]
    assert "rate" in defn.parameters["properties"]
    assert "save_to" in defn.parameters["properties"]
    assert "text" in defn.parameters["required"]


@pytest.mark.asyncio
async def test_speak_tool_execute_to_file():
    """Verify SpeakTool synthesizes audio to target file without playing."""
    tool = SpeakTool()

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp_path = Path(tmp.name)

    try:
        res = await tool.execute(
            {
                "text": "Hello Omkar, running SpeakTool test.",
                "voice": "guy",
                "rate": "+15%",
                "save_to": str(tmp_path),
                "play": False,
            },
            {},
        )
        assert res.success
        assert res.data["action"] == "synthesize"
        assert res.data["voice"] == "en-US-GuyNeural"
        assert res.data["bytes"] > 1000
        assert Path(res.data["file"]).exists()
    finally:
        tmp_path.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_speak_tool_empty_text_error():
    """Verify SpeakTool returns clean error on empty text."""
    tool = SpeakTool()
    res = await tool.execute({"text": "   "}, {})
    assert res.success is False
    assert "text parameter is required" in res.error.lower()
