"""Local Flask server for the draft-zone FPoR page.

Serves the same page as the static site (sleeper_fpor/web) plus a live
``data.json`` rebuilt from Sleeper at most every 15 minutes.

Run with:  sleeper-draft [--league ID] [--host 0.0.0.0] [--port 8000]
"""

from __future__ import annotations

import argparse
import threading
import time
from typing import Any

from flask import Flask, jsonify, send_from_directory

from sleeper_fpor.config import LEAGUE_ID
from sleeper_fpor.draft_site import WEB_DIR, build_bundle

LIVE_TTL_S = 15 * 60


def create_app(league_id: str) -> Flask:
    app = Flask(__name__, static_folder=str(WEB_DIR), static_url_path="")
    lock = threading.Lock()
    cached: dict[str, Any] = {}

    @app.get("/")
    def index():
        return send_from_directory(WEB_DIR, "index.html")

    @app.get("/data.json")
    def data():
        with lock:  # one rebuild at a time; others wait for it rather than duplicating it
            if not cached or time.time() - cached["at"] > LIVE_TTL_S:
                try:
                    cached.update(at=time.time(), bundle=build_bundle(league_id))
                except Exception as exc:  # noqa: BLE001 -- surface upstream failures to the page
                    return jsonify({"error": f"Could not load league {league_id}: {exc}"}), 502
            return jsonify(cached["bundle"])

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Draft-zone FPoR web server for a Sleeper league")
    parser.add_argument("--league", default=LEAGUE_ID)
    parser.add_argument("--host", default="127.0.0.1", help="0.0.0.0 to share on your network")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    if not args.league:
        parser.error("No league ID: set SLEEPER_LEAGUE_ID, put it in .sleeper_league_id, or pass --league")
    create_app(args.league).run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
