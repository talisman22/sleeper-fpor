"""Build the draft-zone FPoR page as a static site: web assets + one data.json.

The page does all the zone math in the browser (web/zone.js), so the only
server-side work is fetching Sleeper data and scoring it with the league's
settings. The same bundle backs the local Flask server and the GitHub Pages site.

    python -m sleeper_fpor.draft_site --out site
"""

from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sleeper_fpor.client import ApiClient
from sleeper_fpor.config import LEAGUE_ID, SLEEPER_BASE
from sleeper_fpor.league import FREE_AGENT, build_lines, roster_spots, team_names
from sleeper_fpor.players import Player, canonical_position, load_players

WEB_DIR = Path(__file__).with_name("web")
REGULAR_SEASON_WEEKS = 18


def completed_weeks(league: dict[str, Any], state: dict[str, Any]) -> int:
    league_season = int(league["season"])
    if league_season < int(state.get("season") or league_season) or state.get("season_type") == "post":
        return REGULAR_SEASON_WEEKS
    if state.get("season_type") == "pre":
        return 0
    return max(int(state.get("week") or 1) - 1, 0)


def make_bundle(
    *,
    league: dict[str, Any],
    rosters: list[dict[str, Any]],
    users: list[dict[str, Any]],
    picks: list[dict[str, Any]],
    players: dict[str, Player],
    weekly_stats: dict[int, dict[str, Any]],
    weeks: int,
) -> dict[str, Any]:
    """Everything the page needs: picks, teams, and weekly points for each relevant player.

    Relevant = drafted, or on a roster today. ``weekly`` holds league-scored points
    per week (1..weeks), ``null`` for weeks the player did not play.
    """
    spots = roster_spots(rosters)
    lines = build_lines(weekly_stats, players, spots, league.get("scoring_settings") or {})
    names = team_names(users, rosters)
    avatars = {u.get("user_id"): u.get("avatar") for u in users}

    parsed = []
    for rec in picks:
        if not rec.get("player_id"):
            continue
        meta = rec.get("metadata") or {}
        parsed.append(
            {
                "pick_no": int(rec["pick_no"]),
                "round": int(rec.get("round") or 0),
                "player_id": str(rec["player_id"]),
                "roster_id": rec.get("roster_id"),
                "pos": canonical_position(meta.get("position")) or "UNK",
                "name": f"{meta.get('first_name', '')} {meta.get('last_name', '')}".strip(),
            }
        )
    parsed.sort(key=lambda p: p["pick_no"])

    relevant = {p["player_id"] for p in parsed} | {
        pid for pid, spot in spots.items() if spot.status != FREE_AGENT
    }
    bundle_players: dict[str, Any] = {}
    for pid in sorted(relevant):
        line = lines.get(pid)
        spot = spots.get(pid)
        info = players.get(pid)
        if line is None and info is None and pid not in {p["player_id"] for p in parsed}:
            continue
        bundle_players[pid] = {
            "name": line.name if line else (info.name if info else None),
            "pos": line.position if line else (info.position if info else None),
            "nfl": (line.team if line else (info.team if info else None)) or "FA",
            "owner": spot.roster_id if spot and spot.status != FREE_AGENT else None,
            "weekly": [
                round(line.weekly[w], 2) if line and w in line.weekly else None
                for w in range(1, weeks + 1)
            ],
        }

    draft_slot = {p["roster_id"]: ((p["pick_no"] - 1) % len(rosters)) + 1 for p in parsed if p["round"] == 1}
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "league": {
            "name": (league.get("name") or "").strip(),
            "season": int(league["season"]),
            "teams": len(rosters),
            "rounds": max((p["round"] for p in parsed), default=0),
            "last_pick": parsed[-1]["pick_no"] if parsed else 0,
            "completed_weeks": weeks,
        },
        "teams": [
            {
                "roster_id": roster["roster_id"],
                "name": names.get(roster["roster_id"], f"Team {roster['roster_id']}"),
                "avatar": avatars.get(roster.get("owner_id")),
                "draft_slot": draft_slot.get(roster["roster_id"]),
            }
            for roster in rosters
        ],
        "picks": parsed,
        "players": bundle_players,
    }


def build_bundle(league_id: str, client: ApiClient | None = None) -> dict[str, Any]:
    """Fetch everything from Sleeper and assemble the bundle."""
    own = client is None
    client = client or ApiClient(pause_s=0.0)
    try:
        league = client.sleeper_league(league_id)
        if not league:
            raise LookupError(f"League {league_id} not found")
        state = client.sleeper_state()
        weeks = completed_weeks(league, state)
        draft_id = league.get("draft_id")
        picks = client.get_json(f"{SLEEPER_BASE}/draft/{draft_id}/picks") if draft_id else []
        if not picks:
            raise LookupError("This league has no completed draft yet.")
        season = int(league["season"])
        return make_bundle(
            league=league,
            rosters=client.sleeper_rosters(league_id),
            users=client.sleeper_users(league_id),
            picks=picks,
            players=load_players(client.sleeper_players(max_age_s=24 * 3600)),
            weekly_stats={w: client.sleeper_week_stats_live(season, w) or {} for w in range(1, weeks + 1)},
            weeks=weeks,
        )
    finally:
        if own:
            client.close()


def write_site(out_dir: Path, bundle: dict[str, Any]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    for asset in WEB_DIR.iterdir():
        if asset.is_file():
            shutil.copy2(asset, out_dir / asset.name)
    (out_dir / "data.json").write_text(json.dumps(bundle, separators=(",", ":")), encoding="utf-8")
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")  # serve files as-is on GitHub Pages
    return out_dir


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the static draft-zone FPoR site")
    parser.add_argument("--league", default=LEAGUE_ID)
    parser.add_argument("--out", type=Path, default=Path("site"))
    args = parser.parse_args()
    if not args.league:
        parser.error("No league ID: set SLEEPER_LEAGUE_ID, put it in .sleeper_league_id, or pass --league")
    bundle = build_bundle(args.league)
    out = write_site(args.out, bundle)
    size_kb = (out / "data.json").stat().st_size / 1024
    print(
        f"Built {out} for {bundle['league']['name']} -- weeks 1-{bundle['league']['completed_weeks']}, "
        f"{len(bundle['players'])} players, data.json {size_kb:.0f} KB"
    )


if __name__ == "__main__":
    main()
