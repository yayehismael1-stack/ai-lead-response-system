"""
ElevenLabs speech in and out.

The API key lives here and only here. The browser posts text to /api/speak and
audio to /api/listen; it never sees a key.
"""
import json
import os
import urllib.error
import urllib.request
import uuid

TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"
DEFAULT_VOICE = "21m00Tcm4TlvDq8ikWAM"
MODEL_TTS = "eleven_turbo_v2_5"
MODEL_STT = "scribe_v1"
TIMEOUT = 45


def _key():
    return (os.environ.get("ELEVENLABS_API_KEY") or "").strip()


def status():
    if not _key():
        return {"available": False, "reason": "ELEVENLABS_API_KEY not set in .env"}
    return {"available": True, "reason": "", "voice_id": os.environ.get("ELEVENLABS_VOICE_ID") or DEFAULT_VOICE}


def speak(text):
    """text -> (mp3 bytes, error). Never raises."""
    text = (text or "").strip()
    if not text:
        return b"", "nothing to say"
    key = _key()
    if not key:
        return b"", "ELEVENLABS_API_KEY not set — speech output is off"

    voice_id = os.environ.get("ELEVENLABS_VOICE_ID") or DEFAULT_VOICE
    payload = json.dumps({
        "text": text[:2500],
        "model_id": MODEL_TTS,
        "voice_settings": {"stability": 0.45, "similarity_boost": 0.75},
    }).encode()
    req = urllib.request.Request(
        TTS_URL.format(voice_id=voice_id),
        data=payload,
        headers={
            "xi-api-key": key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return resp.read(), None
    except urllib.error.HTTPError as e:
        return b"", f"ElevenLabs TTS {e.code}: {e.read()[:200].decode(errors='replace')}"
    except Exception as e:
        return b"", f"ElevenLabs TTS unreachable: {e}"


def _multipart(fields, file_field, filename, file_bytes, file_ctype):
    boundary = uuid.uuid4().hex
    out = []
    for k, v in fields.items():
        out.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
    out.append(
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"{file_field}\"; "
        f"filename=\"{filename}\"\r\nContent-Type: {file_ctype}\r\n\r\n".encode()
    )
    out.append(file_bytes)
    out.append(f"\r\n--{boundary}--\r\n".encode())
    return b"".join(out), f"multipart/form-data; boundary={boundary}"


def listen(audio_bytes, content_type="audio/webm"):
    """audio bytes -> (transcript, error). Never raises."""
    if not audio_bytes:
        return "", "no audio received"
    key = _key()
    if not key:
        return "", "ELEVENLABS_API_KEY not set — transcription is off"

    ext = "webm"
    if "ogg" in content_type:
        ext = "ogg"
    elif "mp4" in content_type or "m4a" in content_type:
        ext = "mp4"
    elif "wav" in content_type:
        ext = "wav"

    body, ctype = _multipart(
        {"model_id": MODEL_STT},
        "file",
        f"turn.{ext}",
        audio_bytes,
        content_type.split(";")[0],
    )
    req = urllib.request.Request(
        STT_URL, data=body, headers={"xi-api-key": key, "Content-Type": ctype}
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            parsed = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return "", f"ElevenLabs Scribe {e.code}: {e.read()[:200].decode(errors='replace')}"
    except Exception as e:
        return "", f"ElevenLabs Scribe unreachable: {e}"
    return (parsed.get("text") or "").strip(), None
