from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx

from sleeper_fpor.config import DATA_DIR, FFC_ADP_URL, SLEEPER_BASE, USER_AGENT


class ApiClient:
    def __init__(self, timeout: float = 60.0, pause_s: float = 0.15) -> None:
        self._pause_s = pause_s
        self._http = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> ApiClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        time.sleep(self._pause_s)
        response = self._http.get(url, params=params)
        response.raise_for_status()
        return response.json()

    def cache_json(
        self,
        path: Path,
        url: str,
        params: dict[str, Any] | None = None,
        max_age_s: float | None = None,
    ) -> Any:
        if path.exists() and (max_age_s is None or time.time() - path.stat().st_mtime < max_age_s):
            return json.loads(path.read_text(encoding="utf-8"))
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = self.get_json(url, params=params)
        path.write_text(json.dumps(payload), encoding="utf-8")
        return payload

    def sleeper_state(self) -> dict[str, Any]:
        return self.get_json(f"{SLEEPER_BASE}/state/nfl")

    def sleeper_players(self, max_age_s: float | None = None) -> dict[str, Any]:
        return self.cache_json(
            DATA_DIR / "sleeper_players.json", f"{SLEEPER_BASE}/players/nfl", max_age_s=max_age_s
        )

    def sleeper_league(self, league_id: str) -> dict[str, Any]:
        return self.get_json(f"{SLEEPER_BASE}/league/{league_id}")

    def sleeper_rosters(self, league_id: str) -> list[dict[str, Any]]:
        return self.get_json(f"{SLEEPER_BASE}/league/{league_id}/rosters")

    def sleeper_users(self, league_id: str) -> list[dict[str, Any]]:
        return self.get_json(f"{SLEEPER_BASE}/league/{league_id}/users")

    def sleeper_week_stats_live(self, season: int, week: int) -> dict[str, Any]:
        """Uncached weekly stats -- for the in-progress season, where stat corrections land."""
        return self.get_json(f"{SLEEPER_BASE}/stats/nfl/regular/{season}/{week}")

    def sleeper_week_stats(self, season: int, week: int) -> dict[str, Any]:
        path = DATA_DIR / "stats" / str(season) / f"week_{week:02d}.json"
        url = f"{SLEEPER_BASE}/stats/nfl/regular/{season}/{week}"
        return self.cache_json(path, url)

    def ffc_adp(self, season: int) -> dict[str, Any]:
        path = DATA_DIR / "adp" / f"ffc_ppr_{season}.json"
        # FFC does not publish a 16-team feed; 12-team PPR rank is used as board order.
        return self.cache_json(path, FFC_ADP_URL, params={"teams": 12, "year": season})
