# scripts/ws_smoke_show.py
import asyncio, json, sys, wave, time, argparse, websockets

parser = argparse.ArgumentParser()
parser.add_argument("--url", required=True)
parser.add_argument("--wav", required=True)
parser.add_argument("--timeout", type=int, default=20)
args = parser.parse_args()

async def main():
    start = time.time()
    async with websockets.connect(args.url, ping_interval=10, ping_timeout=10) as ws:
        # 1) Handshake: måste börja med 'ready' (SPEC/PLAYBOOK)
        msg = await ws.recv()
        evt = json.loads(msg)
        assert evt.get("type") == "ready", f"expected 'ready', got: {evt}"
        print("READY ✓", evt.get("audio_in", {}))

        # 2) Läs WAV och skicka som PCM16-chunks (20 ms @ 16 kHz)
        with wave.open(args.wav, "rb") as w:
            assert w.getframerate() == 16000, "must be 16kHz"
            assert w.getnchannels() == 1, "must be mono"
            assert w.getsampwidth() == 2, "must be 16-bit PCM"
            frames = w.readframes(w.getnframes())

        step = 320 * 2  # ~20 ms (320 samples * 2 bytes)
        for off in range(0, len(frames), step):
            await ws.send(frames[off:off+step])
            await asyncio.sleep(0.02)

        # 3) Skriv ut stt.partial och stt.final (mäter total tid)
        last_partial = ""
        partial_printed_len = 0

        async def waiter():
            nonlocal last_partial, partial_printed_len
            while True:
                e = json.loads(await ws.recv())
                if e.get("type") == "stt.partial" and e.get("text"):
                    # skriv bara ny del (enkel throttle/append)
                    txt = e["text"]
                    new = txt[partial_printed_len:]
                    if new:
                        print("PARTIAL:", new)
                        partial_printed_len = len(txt)
                if e.get("type") == "stt.final" and e.get("text"):
                    print("FINAL ✓", e["text"])
                    return True

        await asyncio.wait_for(waiter(), timeout=args.timeout)
        elapsed = time.time() - start
        print(f"TOTAL TIME: {elapsed:.2f}s")

if __name__ == "__main__":
    asyncio.run(main())
