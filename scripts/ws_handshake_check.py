# scripts/ws_handshake_check.py
import asyncio, json, argparse, websockets

parser = argparse.ArgumentParser()
parser.add_argument("--port", default="8000")
args = parser.parse_args()
URL = f"ws://localhost:{args.port}/ws/transcribe"

async def main():
    try:
        async with websockets.connect(URL, ping_interval=10, ping_timeout=10) as ws:
            msg = await asyncio.wait_for(ws.recv(), timeout=3)
            evt = json.loads(msg)
            if evt.get("type") == "ready":
                print("   OK: mottog 'ready' från servern")
            else:
                print(f"   FAIL: första meddelandet var inte 'ready': {evt}")
    except Exception as e:
        print(f"   FAIL: kunde inte genomföra WS-handshake: {e}")

if __name__ == "__main__":
    asyncio.run(main())
