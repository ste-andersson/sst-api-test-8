install:
	uv pip install --upgrade pip
	uv pip install -r requirements.txt

run:
	set -a; [ -f .env ] && . ./.env; set +a; \
	uvicorn app.main:app --host $${APP_HOST:-0.0.0.0} --port $${APP_PORT:-8000}

clean:
	rm -rf .pytest_cache .ruff_cache __pycache__ .mypy_cache .venv dist build

ws-smoke:
	python scripts/ws_smoketest.py --url ws://localhost:$${APP_PORT:-8000}/ws/transcribe --wav lab/input_audio/sv_hej_5s_16k_mono.wav --timeout 10

SHELL := /bin/bash

# Tyst, steg-för-steg diagnose (ingen 'konstig' eko-text i början)
ws-diagnose:
	@( set -euo pipefail; \
	  PORT="$${APP_PORT:-8000}"; WAV="lab/input_audio/sv_hej_5s_16k_mono.wav"; \
	  echo "=== ws-diagnose ==="; \
	  echo "0) Effektiv port: $$PORT"; \
	  echo "1) Healthz"; \
	  if curl -fsS "http://localhost:$$PORT/healthz" >/dev/null; then echo "   OK"; else echo "   FAIL"; fi; \
	  echo "2) WAV-format"; \
	  if [[ -f "$$WAV" ]]; then echo "   OK: $$WAV"; else echo "   FAIL: saknas"; fi; \
	  python -c "import wave; p='lab/input_audio/sv_hej_5s_16k_mono.wav'; \
	try: \
		with wave.open(p,'rb') as w: \
			rate=w.getframerate(); ch=w.getnchannels(); sw=w.getsampwidth(); \
			ok=(rate==16000 and ch==1 and sw==2); \
			print(f'   format: {rate} Hz, ch={ch}, width={sw} -> {\"OK\" if ok else \"FAIL\"}'); \
	except FileNotFoundError: \
		print('   format: (ingen fil)')" 2>/dev/null || true; \
	  echo "3) OPENAI_API_KEY"; \
	  if [[ -n "$${OPENAI_API_KEY:-}" ]]; then echo "   OK: i miljön"; \
	  elif [[ -f ".env" ]] && grep -E '^[[:space:]]*OPENAI_API_KEY[[:space:]]*=[[:space:]]*\S' .env >/dev/null; then echo "   OK: i .env"; \
	  else echo "   WARN: saknas"; fi; \
	  echo "4) WS-handshake"; \
	  python scripts/ws_handshake_check.py --port "$${PORT:-8000}" || true; \
	  echo "5) ws-smoke (tyst)"; \
	  if python scripts/ws_smoketest.py --url "ws://localhost:$${PORT:-8000}/ws/transcribe" --wav "$$WAV" --timeout 10 >/dev/null 2>&1; then \
	    echo "   OK: stt.final mottagen ≤ 10 s"; \
	  else echo "   FAIL: ingen final"; fi; \
	)

# Snapshot av observability (SPEC §4)
debug-snapshot:
	@PORT="$${APP_PORT:-8000}"; \
	echo "=== debug-snapshot (port $$PORT) ==="; \
	echo "# /debug/frontend-chunks"; curl -fsS "http://localhost:$$PORT/debug/frontend-chunks" || true; echo; \
	echo "# /debug/openai-chunks"; curl -fsS "http://localhost:$$PORT/debug/openai-chunks" || true; echo; \
	echo "# /debug/openai-text";   curl -fsS "http://localhost:$$PORT/debug/openai-text"   || true; echo; \
	echo "# /debug/frontend-text"; curl -fsS "http://localhost:$$PORT/debug/frontend-text" || true; echo; \
	echo "# /healthz";             curl -fsS "http://localhost:$$PORT/healthz"             || true; echo




# Visa "live" transkription (partials + final)
ws-smoke-show:
	@PORT="$${APP_PORT:-8000}"; WAV="lab/input_audio/sv_hej_5s_16k_mono.wav"; \
	echo "=== ws-smoke-show (port $$PORT) ==="; \
	python scripts/ws_smoke_show.py --url "ws://localhost:$$PORT/ws/transcribe" --wav "$$WAV" --timeout 20


	
# Kontrollera miljövariabler
env-check:
	@python -c "from dotenv import load_dotenv; load_dotenv(override=True); \
import os; \
k=os.getenv('OPENAI_API_KEY'); \
mask=(k[:7]+'…'+k[-4:]) if k else '(saknas)'; \
print('OPENAI_API_KEY:', 'SET' if k else 'MISSING', mask)"

.PHONY: ws-smoke-show ws-diagnose debug-snapshot env-check