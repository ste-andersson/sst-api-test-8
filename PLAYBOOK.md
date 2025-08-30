# PLAYBOOK: Bygga & testa Live STT (FastAPI ↔ OpenAI Realtime)

**Roll:** Praktisk guide för dev/test. **Får aldrig** överstyra `SPEC.md`.  
**Källhierarki:** 1) SPEC.md (normer) → 2) PLAYBOOK.md (metod) → 3) README/övrigt.

---

## Repo-struktur (minst)
```
app/
  main.py
lab/
  input_audio/
    sv_hej_5s_16k_mono.wav   # eller lägg till själv
scripts/
  ws_smoketest.py
Makefile
requirements.txt
.env.example
README.md
SPEC.md
PLAYBOOK.md
```

## Snabbstart
1. Kopiera `.env.example` → `.env` och fyll **OPENAI_API_KEY**.
2. `make install`
3. `make run`
4. Kör smoketest: `make ws-smoke`  (ska ge minst en `stt.final` inom 10 s)

## WebSocket-kontrakt (TL;DR)
- **Klient → server:** binära WS-frames med **PCM16 LE, mono, 16 kHz**, 20–40 ms/chunk.
- **Server → klient (open):**
  ```json
  {"type":"ready","audio_in":{"encoding":"pcm16","sample_rate_hz":16000,"channels":1}}
  ```
- **Transkript (server → klient):**
  - `{"type":"stt.partial","text":"..."}`
  - `{"type":"stt.final","text":"..."}`
- **Realtime:** `whisper-1` + `server_vad` → lyssna på `conversation.item.input_audio_transcription.completed`.

## Make-kommandon (rekommenderat minimum)
```make
install:
	uv pip install --upgrade pip
	uv pip install -r requirements.txt

run:
	uvicorn app.main:app --host $${APP_HOST:-0.0.0.0} --port $${APP_PORT:-8000}

clean:
	rm -rf .pytest_cache .ruff_cache __pycache__

ws-smoke:
	python scripts/ws_smoketest.py --url ws://localhost:$${APP_PORT:-8000}/ws/transcribe --wav lab/input_audio/sv_hej_5s_16k_mono.wav --timeout 10
```

## WS-smoketest (scripts/ws_smoketest.py)
```python
import asyncio, json, sys, wave, websockets

async def run(url: str, wav_path: str, timeout: int = 10):
    async with websockets.connect(url, ping_interval=10, ping_timeout=10) as ws:
        # 1) Handshake: måste börja med 'ready'
        msg = await ws.recv()
        evt = json.loads(msg)
        assert evt.get("type") == "ready", f"expected 'ready', got: {evt}"

        # 2) Läs WAV och skicka som PCM16-chunks (20–40 ms ≈ 320–640 sampel @ 16kHz)
        with wave.open(wav_path, "rb") as w:
            assert w.getframerate() == 16000, "must be 16kHz"
            assert w.getnchannels() == 1, "must be mono"
            assert w.getsampwidth() == 2, "must be 16-bit PCM"
            frames = w.readframes(w.getnframes())

        step = 320 * 2  # 320 sampel * 2 bytes = ~20 ms
        for off in range(0, len(frames), step):
            await ws.send(frames[off:off+step])
            await asyncio.sleep(0.02)

        # 3) Vänta på stt.final
        async def waiter():
            while True:
                m = await ws.recv()
                e = json.loads(m)
                if e.get("type") == "stt.final" and e.get("text"):
                    return True

        await asyncio.wait_for(waiter(), timeout=timeout)

if __name__ == "__main__":
    url = sys.argv[sys.argv.index("--url")+1]
    wav = sys.argv[sys.argv.index("--wav")+1]
    timeout = int(sys.argv[sys.argv.index("--timeout")+1]) if "--timeout" in sys.argv else 10
    asyncio.run(run(url, wav, timeout))
```

## Observability
- `GET /debug/frontend-chunks` – verifiera inkommande ljud
- `GET /debug/openai-chunks` – verifiera skickade chunks
- `GET /debug/openai-text` – senaste transkript från OpenAI
- `GET /debug/frontend-text` – text skickad till frontend
- `GET /healthz` – hälsa
- `POST /debug/reset` – nollställ buffertar

## Miljöexempel (.env.example)
```
# OpenAI
OPENAI_API_KEY=
# Server
APP_HOST=0.0.0.0
APP_PORT=8000
# CORS
ALLOWED_ORIGINS=https://*.lovable.app,http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173
```

## Definition of Done
- [ ] `make ws-smoke` passerar lokalt
- [ ] Frontend loggar “Server ready”, `stt.partial` → `stt.final`
- [ ] Debug-räknare tickar vid tal
- [ ] SPEC.md uppfylld
