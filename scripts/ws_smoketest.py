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
