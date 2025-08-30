# sst-api-test-8

FastAPI-backend för live STT (svenska) via OpenAI Realtime. Frontend ↔ backend via **WebSocket**.  
Byggt enligt **SPEC.md** (norm) och **PLAYBOOK.md** (guide).

## Snabbstart
1. Kopiera `.env.example` → `.env` och fyll **OPENAI_API_KEY**.
2. `make install`
3. `make run`
4. Lägg en 16 kHz, mono, PCM16 WAV i `lab/input_audio/` och döp den till `sv_hej_5s_16k_mono.wav` (t.ex. säg “hej” i ca 3–5 s).
5. `make ws-smoke` → ska ge minst en `stt.final` inom 10 s.

## API-kontrakt (WS)
Servern skickar **omedelbart** vid anslutning:
```json
{"type":"ready","audio_in":{"encoding":"pcm16","sample_rate_hz":16000,"channels":1}}
```
Klienten skickar binära **PCM16 LE mono 16 kHz**-frames om 20–40 ms.
Servern svarar med löpande:
- `{"type":"stt.partial","text":"..."}`
- `{"type":"stt.final","text":"..."}`

## Observability (HTTP)
- `GET /debug/frontend-chunks` – antal & senaste storlekar av inkommande frames
- `GET /debug/openai-chunks` – antal & senaste storlekar som skickats till OpenAI
- `GET /debug/openai-text` – senaste deltas (partials) & finaler
- `GET /debug/frontend-text` – event (`stt.partial`/`stt.final`) som faktiskt skickats till klient
- `GET /healthz`
- `POST /debug/reset` – nollställ intern state

## Deploy
- Kör på `0.0.0.0`, port från `APP_PORT`. (Render-kompatibelt.)

## Källor
Se **[SPEC.md](SPEC.md)** och **[PLAYBOOK.md](PLAYBOOK.md)** för normer och arbetsgång.
