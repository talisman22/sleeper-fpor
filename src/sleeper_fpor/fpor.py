from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Iterable

from sleeper_fpor.config import FLEX_POSITIONS, STARTER_SLOTS, TEAMS
from sleeper_fpor.players import Player, canonical_position


@dataclass(frozen=True)
class WeekScore:
    player_id: str
    position: str
    pts: float


def ppr_points(stats: dict[str, Any]) -> float:
    if stats.get("pts_ppr") is not None:
        return float(stats["pts_ppr"])
    return 0.0


def week_scores(
    stats_by_player: dict[str, Any],
    players: dict[str, Player],
) -> list[WeekScore]:
    scores: list[WeekScore] = []
    for player_id, rec in stats_by_player.items():
        if not isinstance(rec, dict):
            continue
        player = players.get(str(player_id))
        if player is None:
            pos = canonical_position(rec.get("pos") or rec.get("position"))
            if pos is None:
                continue
        else:
            pos = player.position
        pts = ppr_points(rec)
        if pts == 0.0 and not rec.get("gp"):
            continue
        scores.append(WeekScore(player_id=str(player_id), position=pos, pts=pts))
    return scores


def replacement_levels(scores: Iterable[WeekScore]) -> dict[str, float]:
    """First non-starter at each position, after filling 16-team starting lineups.

    Lineup: 1 QB, 2 RB, 2 WR, 0 TE, 1 FLEX (RB/WR/TE), 1 DEF, 1 K.
    """
    by_pos: dict[str, list[WeekScore]] = defaultdict(list)
    for score in scores:
        by_pos[score.position].append(score)
    for pos in by_pos:
        by_pos[pos].sort(key=lambda item: item.pts, reverse=True)

    started: set[str] = set()

    def take(pos: str, count: int) -> None:
        for item in by_pos.get(pos, [])[:count]:
            started.add(item.player_id)

    take("QB", TEAMS * STARTER_SLOTS["QB"])
    take("RB", TEAMS * STARTER_SLOTS["RB"])
    take("WR", TEAMS * STARTER_SLOTS["WR"])
    take("TE", TEAMS * STARTER_SLOTS["TE"])
    take("DEF", TEAMS * STARTER_SLOTS["DEF"])
    take("K", TEAMS * STARTER_SLOTS["K"])

    leftover = [
        item
        for pos in FLEX_POSITIONS
        for item in by_pos.get(pos, [])
        if item.player_id not in started
    ]
    leftover.sort(key=lambda item: item.pts, reverse=True)
    for item in leftover[: TEAMS * STARTER_SLOTS["FLEX"]]:
        started.add(item.player_id)

    replacement: dict[str, float] = {}
    for pos, ranked in by_pos.items():
        first_bench = next((item.pts for item in ranked if item.player_id not in started), None)
        if first_bench is not None:
            replacement[pos] = first_bench
        elif ranked:
            replacement[pos] = ranked[-1].pts
        else:
            replacement[pos] = 0.0
    return replacement


def weekly_fpor(scores: list[WeekScore], replacement: dict[str, float]) -> dict[str, float]:
    pts_by_id = {item.player_id: item.pts for item in scores}
    pos_by_id = {item.player_id: item.position for item in scores}
    values: dict[str, float] = {}
    for player_id, pts in pts_by_id.items():
        pos = pos_by_id[player_id]
        values[player_id] = pts - replacement.get(pos, 0.0)
    return values
