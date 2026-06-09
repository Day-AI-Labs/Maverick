"""Voice tools — speech-to-text (Whisper) and text-to-speech.

Both are optional extras; they require API keys.

Speech-to-text backends (tried in order):
  1. OpenAI Whisper API (OPENAI_API_KEY)
  2. Groq Whisper API (GROQ_API_KEY, faster + cheap)
  3. local faster-whisper if installed

Text-to-speech backends:
  1. OpenAI TTS API (OPENAI_API_KEY)
  2. ElevenLabs (ELEVENLABS_API_KEY)
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from . import Tool

log = logging.getLogger(__name__)


_TRANSCRIBE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "source": {
            "type": "string",
            "description": "Audio file path (mp3, wav, m4a, flac, ogg).",
        },
        "language": {
            "type": "string",
            "description": "ISO 639-1 code (e.g. 'en'). Auto-detect if omitted.",
        },
        "backend": {
            "type": "string",
            "enum": ["openai", "groq", "local", "auto"],
            "description": "Force a specific backend (default 'auto').",
        },
    },
    "required": ["source"],
}


_TTS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "text": {"type": "string", "description": "Text to synthesize."},
        "voice": {
            "type": "string",
            "description": "Voice id. Backend-specific: 'alloy'/'echo'/... for OpenAI.",
        },
        "backend": {
            "type": "string",
            "enum": ["openai", "elevenlabs", "auto"],
            "description": "Backend (default 'auto').",
        },
        "output": {
            "type": "string",
            "description": "Output file path. Default: ./speech-<n>.mp3.",
        },
    },
    "required": ["text"],
}


# ---------- STT ----------

def _whisper_openai(audio_path: Path, language: str | None) -> str | None:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        return None
    try:
        from openai import OpenAI
    except ImportError:
        return None
    try:
        client = OpenAI(api_key=key)
        with open(audio_path, "rb") as f:
            kwargs: dict[str, Any] = {"model": "whisper-1", "file": f}
            if language:
                kwargs["language"] = language
            resp = client.audio.transcriptions.create(**kwargs)
        return getattr(resp, "text", None) or str(resp)
    except Exception as e:
        log.warning("whisper (openai): %s", e)
        return None


def _whisper_groq(audio_path: Path, language: str | None) -> str | None:
    key = os.environ.get("GROQ_API_KEY")
    if not key:
        return None
    try:
        from openai import OpenAI
    except ImportError:
        return None
    try:
        client = OpenAI(api_key=key, base_url="https://api.groq.com/openai/v1")
        with open(audio_path, "rb") as f:
            kwargs: dict[str, Any] = {
                "model": "whisper-large-v3-turbo", "file": f,
            }
            if language:
                kwargs["language"] = language
            resp = client.audio.transcriptions.create(**kwargs)
        return getattr(resp, "text", None) or str(resp)
    except Exception as e:
        log.warning("whisper (groq): %s", e)
        return None


def _whisper_local(audio_path: Path, language: str | None) -> str | None:
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError:
        return None
    try:
        model_size = os.environ.get("MAVERICK_WHISPER_MODEL", "small")
        model = WhisperModel(model_size, device="cpu", compute_type="int8")
        segments, _ = model.transcribe(str(audio_path), language=language)
        return " ".join(s.text for s in segments).strip()
    except Exception as e:
        log.warning("whisper (local): %s", e)
        return None


def _run_transcribe(args: dict[str, Any], sandbox: Any = None) -> str:
    src = (args.get("source") or "").strip()
    if not src:
        return "ERROR: source is required"
    # Confine the model-supplied path to the workspace: transcription reads the
    # file and ships its bytes to a Whisper backend, so an unconfined source is
    # arbitrary host-file read + exfiltration (~/.ssh/id_rsa, .env). sandbox=None
    # -- the trusted internal view_video caller's temp path -- passes through.
    from .ffmpeg_tool import _safe_path
    try:
        path = Path(_safe_path(sandbox, src))
    except ValueError as e:
        return f"ERROR: {e}"
    if not path.exists() or not path.is_file():
        return f"ERROR: audio file not found: {src!r}"
    language = args.get("language")
    backend = (args.get("backend") or "auto").lower()

    if backend in ("openai", "auto"):
        out = _whisper_openai(path, language)
        if out is not None:
            return out
        if backend == "openai":
            return "ERROR: OpenAI Whisper failed (check OPENAI_API_KEY)"
    if backend in ("groq", "auto"):
        out = _whisper_groq(path, language)
        if out is not None:
            return out
        if backend == "groq":
            return "ERROR: Groq Whisper failed (check GROQ_API_KEY)"
    if backend in ("local", "auto"):
        out = _whisper_local(path, language)
        if out is not None:
            return out
        if backend == "local":
            return (
                "ERROR: local Whisper not installed. "
                "Run: pip install 'maverick-agent[voice]'"
            )
    return (
        "ERROR: no voice backend available. Set OPENAI_API_KEY / GROQ_API_KEY "
        "or install faster-whisper for local transcription."
    )


# ---------- TTS ----------

def _tts_openai(text: str, voice: str | None, output: Path) -> bool:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        return False
    try:
        from openai import OpenAI
    except ImportError:
        return False
    try:
        client = OpenAI(api_key=key)
        resp = client.audio.speech.create(
            model="tts-1",
            voice=voice or "alloy",
            input=text,
        )
        # Stream to file (SDK exposes a stream_to_file helper).
        try:
            resp.stream_to_file(str(output))
        except AttributeError:
            # Older SDK: write resp.content.
            output.write_bytes(getattr(resp, "content", b""))
        return output.exists() and output.stat().st_size > 0
    except Exception as e:
        log.warning("tts (openai): %s", e)
        return False


def _tts_elevenlabs(text: str, voice: str | None, output: Path) -> bool:
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        return False
    try:
        import httpx
    except ImportError:
        return False
    voice_id = voice or os.environ.get("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
    try:
        resp = httpx.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            headers={
                "xi-api-key": key,
                "Content-Type": "application/json",
                "Accept": "audio/mpeg",
            },
            json={"text": text, "model_id": "eleven_turbo_v2_5"},
            timeout=60.0,
        )
        resp.raise_for_status()
        output.write_bytes(resp.content)
        return True
    except Exception as e:
        log.warning("tts (elevenlabs): %s", e)
        return False


def _next_output_path(sandbox: Any = None) -> Path:
    base = Path(sandbox.workdir) if sandbox is not None else Path.cwd()
    i = 1
    while True:
        cand = base / f"speech-{i}.mp3"
        if not cand.exists():
            return cand
        i += 1


def _run_speak(args: dict[str, Any], sandbox: Any = None) -> str:
    text = (args.get("text") or "").strip()
    if not text:
        return "ERROR: text is required"
    if len(text) > 4096:
        return f"ERROR: text too long ({len(text)} > 4096 chars)"
    # Confine the output path to the workspace (unconfined => arbitrary write:
    # ~/.ssh/authorized_keys, ~/.maverick/config.toml). The default also lands
    # in the workspace.
    output = args.get("output")
    if output:
        from .ffmpeg_tool import _safe_path
        try:
            output_path = Path(_safe_path(sandbox, output))
        except ValueError as e:
            return f"ERROR: {e}"
    else:
        output_path = _next_output_path(sandbox)
    voice = args.get("voice")
    backend = (args.get("backend") or "auto").lower()

    if backend in ("openai", "auto"):
        if _tts_openai(text, voice, output_path):
            return f"wrote {output_path} ({output_path.stat().st_size} bytes)"
        if backend == "openai":
            return "ERROR: OpenAI TTS failed (check OPENAI_API_KEY)"
    if backend in ("elevenlabs", "auto"):
        if _tts_elevenlabs(text, voice, output_path):
            return f"wrote {output_path} ({output_path.stat().st_size} bytes)"
        if backend == "elevenlabs":
            return "ERROR: ElevenLabs TTS failed (check ELEVENLABS_API_KEY)"
    return (
        "ERROR: no TTS backend available. Set OPENAI_API_KEY or "
        "ELEVENLABS_API_KEY."
    )


def transcribe_audio(sandbox: Any = None) -> Tool:
    return Tool(
        name="transcribe_audio",
        description=(
            "Transcribe an audio file via Whisper. Backends tried in order: "
            "OpenAI (OPENAI_API_KEY), Groq (GROQ_API_KEY, fast+cheap), local "
            "faster-whisper if installed. Accepts mp3/wav/m4a/flac/ogg. "
            "Set `language='en'` to skip auto-detect."
        ),
        input_schema=_TRANSCRIBE_SCHEMA,
        fn=lambda args: _run_transcribe(args, sandbox),
    )


def speak(sandbox: Any = None) -> Tool:
    return Tool(
        name="speak",
        description=(
            "Synthesize speech from text to an mp3 file. Backends: OpenAI "
            "TTS (OPENAI_API_KEY) or ElevenLabs (ELEVENLABS_API_KEY). "
            "Set `voice` for backend-specific id; default OpenAI voice is "
            "'alloy'. Output path defaults to ./speech-N.mp3."
        ),
        input_schema=_TTS_SCHEMA,
        fn=lambda args: _run_speak(args, sandbox),
    )
