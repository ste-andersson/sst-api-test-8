# SPEC: Live STT via WebSocket (Lovable frontend ↔ FastAPI backend)

**Status:** Normerande (MÅSTE följas)  
**Mål:** Live‑transkribering (svenska) med OpenAI, WebSocket mellan Lovable‑frontend och FastAPI‑backend.  
**Varför:** Stabil, utbytbar och testbar STT som frontenden kan lita på.

---

## 0) Teknik & drift (obligatoriskt)
- Python **3.13**, server: **uvicorn**
- Deploy-miljö: **Render** (lyssna på `0.0.0.0`, port från `APP_PORT`)
- OpenAI Realtime enligt denna SPEC: **modell `whisper-1`**, **`server_vad`**
- CORS: från `ALLOWED_ORIGINS` (default se nedan)

---

## 1) WebSocket-ingång (audio → backend)

- **Path:** `/ws/transcribe`
- **Audio från klient:** binära WS-frames med **PCM16 LE, mono, 16 000 Hz**, 20–40 ms per chunk.
- **Server-handshake på `open`:**  
  Skicka **omedelbart**:
  ```json
  {"type":"ready","audio_in":{"encoding":"pcm16","sample_rate_hz":16000,"channels":1}}
  ```

## 2) STT-motor & Realtime-konfiguration

- **Modell:** `whisper-1`
- **Turn detection:** `server_vad`
  - `silence_duration_ms`: **500–800**
  - `prefix_padding_ms`: **300** (rekommenderat)
- **Lyssna på Realtime-event:**  
  `conversation.item.input_audio_transcription.completed` och **extrahera transkriptet** därifrån.

> OBS: Använd *inte* `response.create` i detta läge. Server-VAD avgör turer.

## 3) Server → klient (transkript)

- Vid pågående tal (icke-final):  
  ```json
  {"type":"stt.partial","text":"..."}
  ```
- När VAD avslutar en tur (final):  
  ```json
  {"type":"stt.final","text":"..."}
  ```
- **Inga andra händelsenamn** för transkript får användas.

## 4) Observability (HTTP)

- `GET /debug/frontend-chunks` → antal & senaste storlekar
- `GET /debug/openai-chunks` → antal & senaste storlekar
- `GET /debug/openai-text` → senaste deltas & finaler
- `GET /debug/frontend-text` → det som faktiskt skickats ut (`stt.partial`/`stt.final`)
- `GET /healthz`
- `POST /debug/reset`

## 5) CORS (obligatoriskt)

Tillåt följande origins (utöka vid behov):
- `https://*.lovable.app`
- `http://localhost:3000`
- `http://127.0.0.1:3000`
- `http://localhost:5173`

## 6) Makefile (minimum)

- `install` – `uv pip install -U pip && uv pip install -r requirements.txt`
- `run` – starta uvicorn (`--host 0.0.0.0 --port ${APP_PORT:-8000}`)
- `clean` – rensa cache/temp
- `ws-smoke` – kör WebSocket-smoketest (se PLAYBOOK.md)

## 7) Acceptanskriterier (måste uppfyllas)

1. Frontend loggar **“Server ready”** vid anslutning.
2. Under tal visas minst en `stt.partial` följt av `stt.final`.
3. `frontend-chunks` & `openai-chunks` tickar upp när du pratar.
4. **WS-smoketest** (16 kHz mono WAV) får **minst en `stt.final` ≤ 10 s**.

## 8) Miljövariabler (exempel)

```
OPENAI_API_KEY=...
APP_HOST=0.0.0.0
APP_PORT=8000
ALLOWED_ORIGINS=https://*.lovable.app,http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173
```

## 9) Leverabler (måste ingå i zip)
- `app/main.py` med WebSocket **/ws/transcribe** som tar **binära PCM16 LE mono 16 kHz (20–40 ms)** och skickar `ready` / `stt.partial` / `stt.final`
- Observability-endpoints enligt SPEC
- `Makefile` med mål: `install`, `run`, `clean`, `ws-smoke`
- `requirements.txt` (rimligt pinnat), `.env.example` (`OPENAI_API_KEY`, `APP_PORT`, `ALLOWED_ORIGINS`)
- `scripts/ws_smoketest.py` (WS-smoketest)
- `lab/input_audio/sv_hej_5s_16k_mono.wav` **eller** instruktion i README att lägga dit filen
- Minimal `README.md` som pekar till SPEC/PLAYBOOK

## 10) Konfiguration (obligatoriskt)
- CORS default: `https://*.lovable.app,http://localhost:3000,http://127.0.0.1:3000,http://localhost:5173`
- **Endast** transkript-eventen `stt.partial` och `stt.final` får användas
- WS-handshake **måste** börja med:
  ```json
  {"type":"ready","audio_in":{"encoding":"pcm16","sample_rate_hz":16000,"channels":1}}
  ```

## 11) Definition of Done (DoD)
- `make ws-smoke` passerar lokalt (minst en `stt.final` ≤ 10 s)
- Frontend loggar **“Server ready”**, därefter `stt.partial` → `stt.final`
- Räknare tickar i `GET /debug/frontend-chunks` och `GET /debug/openai-chunks` under tal
