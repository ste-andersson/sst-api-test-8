# sst-api-test-8 / app/main.py
# FastAPI backend for live STT over WebSocket following SPEC.md.
# Python 3.13 required by SPEC.
import os
from dotenv import load_dotenv
load_dotenv(override=True)
import asyncio
import json
import base64
import time
from typing import List, Dict, Any, Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

# Observability store (in-memory)
class Ring:
    def __init__(self, maxlen: int = 50):
        self.maxlen = maxlen
        self.buf: List[Any] = []

    def push(self, x: Any):
        self.buf.append(x)
        if len(self.buf) > self.maxlen:
            self.buf = self.buf[-self.maxlen:]

    def to_list(self) -> List[Any]:
        return list(self.buf)

class Obs:
    def __init__(self):
        self.frontend_chunk_count = 0
        self.frontend_chunk_sizes = Ring()
        self.openai_chunk_count = 0
        self.openai_chunk_sizes = Ring()
        self.openai_text_deltas = Ring()
        self.openai_text_finals = Ring()
        self.frontend_text_events = Ring()

    def reset(self):
        self.__init__()

obs = Obs()

def _get_allowed_origins():
    env = os.getenv("ALLOWED_ORIGINS", "https://*.lovable.app,http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173")
    parts = [p.strip() for p in env.split(",") if p.strip()]
    # Starlette supports allow_origin_regex for wildcard domain like *.lovable.app
    regex = None
    specific = []
    for p in parts:
        if p.startswith("https://*.") and p.count(".") >= 2:
            # Convert https://*.lovable.app -> ^https://([a-zA-Z0-9-]+\.)*lovable\.app$
            domain = p[len("https://*."):].replace(".", r"\.")
            regex = rf"^https://([a-zA-Z0-9-]+\.)*{domain}$"
        else:
            specific.append(p)
    return specific, regex

app = FastAPI(title="sst-api-test-8")

# CORS per SPEC
_allow, _regex = _get_allowed_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow,
    allow_origin_regex=_regex,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/healthz")
async def healthz():
    return {"status": "ok"}

@app.get("/debug/frontend-chunks")
async def debug_frontend_chunks():
    return {
        "count": obs.frontend_chunk_count,
        "recent_sizes": obs.frontend_chunk_sizes.to_list(),
    }

@app.get("/debug/openai-chunks")
async def debug_openai_chunks():
    return {
        "count": obs.openai_chunk_count,
        "recent_sizes": obs.openai_chunk_sizes.to_list(),
    }

@app.get("/debug/openai-text")
async def debug_openai_text():
    return {
        "deltas": obs.openai_text_deltas.to_list(),
        "finals": obs.openai_text_finals.to_list(),
    }

@app.get("/debug/frontend-text")
async def debug_frontend_text():
    return obs.frontend_text_events.to_list()

@app.post("/debug/reset")
async def debug_reset():
    obs.reset()
    return {"ok": True}

# --- WebSocket <-> OpenAI Realtime bridge ---

OPENAI_REALTIME_URL = os.getenv(
    "OPENAI_REALTIME_URL",
    "wss://api.openai.com/v1/realtime?model=gpt-4o-mini-realtime-preview-2024-12-17"
)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# VAD tuning from SPEC (defaults)
SILENCE_MS = int(os.getenv("SILENCE_MS", "600"))  # 500–800 recommended
PREFIX_PADDING_MS = int(os.getenv("PREFIX_PADDING_MS", "300"))
SAMPLE_RATE = 16000

async def _openai_ws_connect():
    """
    Connects to OpenAI Realtime WS with proper headers.
    Returns the connected websocket object from the 'websockets' library.
    """
    import websockets
    # Azure vs OpenAI headers
    if ".openai.azure.com" in OPENAI_REALTIME_URL:
        headers = [("api-key", OPENAI_API_KEY)]
    else:
        headers = [("Authorization", f"Bearer {OPENAI_API_KEY}")]
        headers.append(("OpenAI-Beta", "realtime=v1"))
    ws = await websockets.connect(
        OPENAI_REALTIME_URL,
        extra_headers=headers,
        max_size=32 * 1024 * 1024,
        ping_interval=10,
        ping_timeout=10,
    )
    # Configure session for server_vad + pcm16 16k mono
    session_update = {
        "type": "session.update",
        "session": {
            "turn_detection": {
                "type": "server_vad",
                "silence_duration_ms": SILENCE_MS,
                "prefix_padding_ms": PREFIX_PADDING_MS,
                "threshold": 0.5,
                "create_response": True,
                "interrupt_response": True,
            },
            "input_audio_format": "pcm16",
            "input_audio_transcription": {
                "model": os.getenv("REALTIME_TRANSCRIBE_MODEL", "whisper-1"),
                "language": os.getenv("INPUT_LANGUAGE", "sv"),
            },
            # Ensure transcription-only behavior
            "modalities": ["text"],
        },
    }
    await ws.send(json.dumps(session_update))
    # Kick off a text-only response stream so transcripts are emitted
    try:
        await ws.send(json.dumps({
            "type": "response.create",
            "response": {
                "conversation": "none",
                "modalities": ["text"],
                "instructions": "Transcribe the user's speech to text only. Do not speak back."
            }
        }))
    except Exception:
        pass

    return ws

def _extract_text_from_event(evt: Dict[str, Any]) -> Optional[str]:
    """
    Try to robustly pull text out of a variety of event payloads the
    Realtime API may emit. The SPEC pinpoints
    'conversation.item.input_audio_transcription.completed' for finals.
    """
    # Potential locations
    for key in ["text", "transcript", "transcription", "output_text"]:
        if isinstance(evt.get(key), str) and evt[key].strip():
            return evt[key].strip()
        if isinstance(evt.get("item", {}), dict):
            v = evt["item"].get(key)
            if isinstance(v, str) and v.strip():
                return v.strip()
            if isinstance(evt["item"].get("content"), list):
                # Sometimes content is a list of blocks
                for block in evt["item"]["content"]:
                    if isinstance(block, dict):
                        t = block.get("text") or block.get("transcript") or block.get("delta")
                        if isinstance(t, str) and t.strip():
                            return t.strip()
    # Some delta events: evt.get("delta")
    if isinstance(evt.get("delta"), str) and evt["delta"].strip():
        return evt["delta"].strip()
    # Nested in "transcription": {"text": ...}
    if isinstance(evt.get("transcription"), dict):
        t = evt["transcription"].get("text")
        if isinstance(t, str) and t.strip():
            return t.strip()
    return None

async def _pump_client_to_openai(client_ws: WebSocket, openai_ws):
    """
    Forward PCM16 frames from client to OpenAI using input_audio_buffer.append messages.
    """
    COMMIT_INTERVAL_MS = int(os.getenv("COMMIT_INTERVAL_MS", "500"))
    last_commit = 0.0
    
    try:
        while True:
            data = await client_ws.receive_bytes()
            size = len(data)
            obs.frontend_chunk_count += 1
            obs.frontend_chunk_sizes.push(size)

            # forward as base64 in JSON per Realtime protocol
            b64 = base64.b64encode(data).decode("ascii")
            msg = {
                "type": "input_audio_buffer.append",
                "audio": b64,
            }
            await openai_ws.send(json.dumps(msg))
            obs.openai_chunk_count += 1
            obs.openai_chunk_sizes.push(size)

            # Periodisk commit för att få deltas och finaler
            now = time.time()
            if (now - last_commit) * 1000 >= COMMIT_INTERVAL_MS:
                try:
                    await openai_ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
                except Exception as e:
                    # ignorera "buffer too small"/tom buffer
                    s = str(e)
                    if "buffer too small" not in s and "input_audio_buffer_commit_empty" not in s:
                        raise
                last_commit = now
    except (WebSocketDisconnect, asyncio.CancelledError):
        # Client or task cancelled/disconnected
        pass
    except Exception:
        # Stop on any error; OpenAI side might continue until closed.
        pass
    finally:
        # Commit the current buffer so VAD can finalize any trailing speech
        try:
            await openai_ws.send(json.dumps({"type": "input_audio_buffer.commit"}))
        except Exception:
            pass

async def _pump_openai_to_client(openai_ws, client_ws: WebSocket):
    """
    Listen for transcription events and forward partials/finals.
    """
    # Throttle partials to avoid spamming
    last_partial_sent_at = 0.0
    partial_accum = ""

    try:
        while True:
            msg = await openai_ws.recv()
            if isinstance(msg, (bytes, bytearray)):
                # Binary messages are not expected for transcript text here
                continue
            evt = json.loads(msg)

            etype = evt.get("type", "")
            # debug: record event types occasionally
            try:
                obs.frontend_text_events.push({"etype": etype})
            except Exception:
                pass
            text = None
            is_final = False
            is_partial = False

            # Heuristics for partial text delta events
            if etype in (
                "response.output_text.delta",          # common in Realtime
                "response.audio_transcript.delta",
                "transcription.delta",
                "conversation.item.delta",
            ):
                text = _extract_text_from_event(evt)
                is_partial = True

            # Finals per SPEC event, plus a few common alternates
            if etype in (
                "conversation.item.input_audio_transcription.completed",
                "transcription.completed",
                "response.output_text.done",
                "response.audio_transcript.completed",
            ):
                text = _extract_text_from_event(evt)
                is_final = True

            if is_partial and text:
                partial_accum += text
                now = time.time()
                if now - last_partial_sent_at > 0.15:  # ~6/s
                    payload = {"type": "stt.partial", "text": partial_accum}
                    await client_ws.send_text(json.dumps(payload, ensure_ascii=False))
                    obs.frontend_text_events.push(payload)
                    obs.openai_text_deltas.push(text)
                    last_partial_sent_at = now

            if is_final and text:
                payload = {"type": "stt.final", "text": text}
                await client_ws.send_text(json.dumps(payload, ensure_ascii=False))
                obs.frontend_text_events.push(payload)
                obs.openai_text_finals.push(text)
                # Reset accumulators after a turn completes
                partial_accum = ""
                last_partial_sent_at = 0.0
    except (Exception, asyncio.CancelledError):
        # Exit on any error/closure (graceful under 3.11+/3.13 where CancelledError is BaseException)
        pass

@app.websocket("/ws/transcribe")
async def ws_transcribe(ws: WebSocket):
    await ws.accept()
    # Handshake: must immediately send 'ready' per SPEC
    ready = {
        "type": "ready",
        "audio_in": {"encoding": "pcm16", "sample_rate_hz": 16000, "channels": 1},
    }
    await ws.send_text(json.dumps(ready))

    if not OPENAI_API_KEY:
        # Fail fast but keep the socket alive long enough for frontends to see 'ready'
        # and possibly some helpful message.
        await asyncio.sleep(0.1)
        await ws.send_text(json.dumps({"type": "stt.final", "text": "OPENAI_API_KEY not configured"}))
        return

    # Connect to OpenAI Realtime
    try:
        openai_ws = await _openai_ws_connect()
    except Exception as e:
        await ws.send_text(json.dumps({"type": "stt.final", "text": f"OpenAI Realtime connect failed: {e}"}))
        return

    # Run pumps concurrently
    pump_up = asyncio.create_task(_pump_client_to_openai(ws, openai_ws))
    pump_down = asyncio.create_task(_pump_openai_to_client(openai_ws, ws))

    # Keep session until client disconnects
    try:
        done, pending = await asyncio.wait([pump_up, pump_down], return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in done:
            try:
                await task
            except asyncio.CancelledError:
                pass
    finally:
        # Close OpenAI ws
        try:
            await openai_ws.close()
        except Exception:
            pass
        # Cancel the other task
        for t in (pump_up, pump_down):
            if not t.done():
                t.cancel()
                try:
                    await t
                except Exception:
                    pass
