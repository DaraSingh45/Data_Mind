"""Start Data Mind:  python run.py   (then open http://localhost:8000)"""
import argparse
import os
import sys
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import uvicorn  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Data Mind server")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    ap.add_argument("--reload", action="store_true", help="auto-reload on code changes (development)")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
    url = f"http://localhost:{args.port}"

    def open_when_ready() -> None:
        """Wait for the server to answer before opening the browser (first start can take a while)."""
        import time
        import urllib.request

        for _ in range(240):
            try:
                urllib.request.urlopen(url + "/api/health", timeout=1)
                print(f"\n  Data Mind is ready → {url}\n", flush=True)
                if not args.no_browser and dist.exists():
                    webbrowser.open(url)
                return
            except Exception:
                time.sleep(0.5)

    import threading

    print("\n  Starting Data Mind… (the first start can take up to a minute)", flush=True)
    threading.Thread(target=open_when_ready, daemon=True).start()
    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload, log_level="warning")
