"""League-specific FPoR for trade evaluation.

Replacement level here is *dynamic*: for each position it is the average
points-per-game of the top N players in a replacement pool -- either free
agents only (what you could pick up today) or free agents plus every rostered
bench player (what you could pick up or trade for cheaply). A player's value is
how far his PPG sits above that bar.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable

from sleeper_fpor.fpor import ppr_points
from sleeper_fpor.players import Player

FANTASY_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")


class PoolMode(str, Enum):
    WAIVER = "waiver"
    BENCH_AND_WAIVER = "bench_and_waiver"


# Roster status for every player the league knows about.
STARTER = "starter"
BENCH = "bench"
RESERVE = "ir"
TAXI = "taxi"
FREE_AGENT = "fa"


@dataclass(frozen=True)
class RosterSpot:
    roster_id: int | None
    status: str


@dataclass
class PlayerLine:
    player_id: str
    name: str
    position: str
    team: str | None
    roster_id: int | None
    status: str
    games: int = 0
    points: float = 0.0
    weekly: dict[int, float] = field(default_factory=dict)

    @property
    def ppg(self) -> float:
        return self.points / self.games if self.games else 0.0


@dataclass(frozen=True)
class Replacement:
    position: str
    ppg: float
    pool: tuple[PlayerLine, ...]


@dataclass(frozen=True)
class PlayerValue:
    line: PlayerLine
    replacement_ppg: float
    fpor_per_game: float
    fpor_to_date: float
    fpor_ros: float


def score_stats(stats: dict[str, Any], scoring: dict[str, float] | None) -> float:
    """Fantasy points for one stat line under the league's scoring settings.

    Sleeper stat keys (``rec``, ``pass_yd``, ``pts_allow_7_13`` ...) share names
    with ``scoring_settings`` keys, so scoring is a dot product. Falls back to
    Sleeper's precomputed full-PPR total when no settings are given.
    """
    if not scoring:
        return ppr_points(stats)
    total = 0.0
    for key, value in stats.items():
        weight = scoring.get(key)
        if weight and isinstance(value, (int, float)):
            total += weight * value
    return round(total, 2)


def played(stats: dict[str, Any]) -> bool:
    # gp, not gms_active: an active-but-unused backup shouldn't drag PPG down.
    return bool(stats.get("gp"))


def roster_spots(rosters: Iterable[dict[str, Any]]) -> dict[str, RosterSpot]:
    spots: dict[str, RosterSpot] = {}
    for roster in rosters:
        roster_id = roster.get("roster_id")
        starters = set(roster.get("starters") or [])
        reserve = set(roster.get("reserve") or [])
        taxi = set(roster.get("taxi") or [])
        for player_id in roster.get("players") or []:
            if player_id in starters:
                status = STARTER
            elif player_id in reserve:
                status = RESERVE
            elif player_id in taxi:
                status = TAXI
            else:
                status = BENCH
            spots[str(player_id)] = RosterSpot(roster_id=roster_id, status=status)
    return spots


def build_lines(
    weekly_stats: dict[int, dict[str, Any]],
    players: dict[str, Player],
    spots: dict[str, RosterSpot],
    scoring: dict[str, float] | None,
) -> dict[str, PlayerLine]:
    """One line per fantasy-relevant player: every rostered player plus anyone who played."""
    lines: dict[str, PlayerLine] = {}

    def line_for(player_id: str) -> PlayerLine | None:
        if player_id in lines:
            return lines[player_id]
        player = players.get(player_id)
        if player is None or player.position not in FANTASY_POSITIONS:
            return None
        spot = spots.get(player_id, RosterSpot(None, FREE_AGENT))
        lines[player_id] = PlayerLine(
            player_id=player_id,
            name=player.name,
            position=player.position,
            team=player.team,
            roster_id=spot.roster_id,
            status=spot.status,
        )
        return lines[player_id]

    for player_id in spots:
        line_for(player_id)

    for week, stats_by_player in sorted(weekly_stats.items()):
        for player_id, stats in stats_by_player.items():
            if not isinstance(stats, dict) or not played(stats):
                continue
            line = line_for(str(player_id))
            if line is None:
                continue
            pts = score_stats(stats, scoring)
            line.games += 1
            line.points += pts
            line.weekly[week] = pts
    return lines


def pool_statuses(mode: PoolMode) -> set[str]:
    if mode is PoolMode.WAIVER:
        return {FREE_AGENT}
    return {FREE_AGENT, BENCH}


def replacement_levels(
    lines: Iterable[PlayerLine],
    mode: PoolMode,
    top_n: int,
    min_games: int,
    positions: Iterable[str] = FANTASY_POSITIONS,
) -> dict[str, Replacement]:
    """Average PPG of the top ``top_n`` pool players at each position.

    ``min_games`` keeps one-week flukes from setting the bar.
    """
    statuses = pool_statuses(mode)
    by_pos: dict[str, list[PlayerLine]] = {pos: [] for pos in positions}
    for line in lines:
        if line.position in by_pos and line.status in statuses and line.games >= min_games:
            by_pos[line.position].append(line)

    levels: dict[str, Replacement] = {}
    for pos, pool in by_pos.items():
        top = sorted(pool, key=lambda item: item.ppg, reverse=True)[:top_n]
        ppg = sum(item.ppg for item in top) / len(top) if top else 0.0
        levels[pos] = Replacement(position=pos, ppg=ppg, pool=tuple(top))
    return levels


# Positional-rank replacement defaults (16 teams): most teams start one QB/TE/K/DEF,
# while RB and WR are started (and rostered) deeper.
DEFAULT_REPLACEMENT_RANKS = {"QB": 16, "RB": 25, "WR": 30, "TE": 16, "K": 16, "DEF": 16}


def rank_replacement_levels(
    lines: Iterable[PlayerLine],
    ranks: dict[str, int],
    min_games: int,
) -> dict[str, Replacement]:
    """PPG of the Nth-best player league-wide at each position (e.g. RB25), rostered or not.

    If fewer than N players qualify, the last qualifier sets the level.
    """
    by_pos: dict[str, list[PlayerLine]] = {pos: [] for pos in ranks}
    for line in lines:
        if line.position in by_pos and line.games >= min_games:
            by_pos[line.position].append(line)

    levels: dict[str, Replacement] = {}
    for pos, rank in ranks.items():
        ranked = sorted(by_pos[pos], key=lambda item: item.ppg, reverse=True)
        if not ranked:
            levels[pos] = Replacement(position=pos, ppg=0.0, pool=())
            continue
        player = ranked[min(rank, len(ranked)) - 1]
        levels[pos] = Replacement(position=pos, ppg=player.ppg, pool=(player,))
    return levels


def value_player(
    line: PlayerLine,
    levels: dict[str, Replacement],
    remaining_weeks: int,
    floor_at_replacement: bool = True,
) -> PlayerValue:
    """FPoR per game, to date, and naively projected over the remaining weeks.

    With ``floor_at_replacement`` a below-replacement player is worth 0, not
    negative: you would cut him for a waiver pickup. This also makes roster-spot
    math fall out naturally -- the open spot in a 2-for-1 is worth replacement (0).
    """
    replacement_ppg = levels[line.position].ppg if line.position in levels else 0.0
    per_game = line.ppg - replacement_ppg if line.games else 0.0
    if floor_at_replacement:
        per_game = max(per_game, 0.0)
    return PlayerValue(
        line=line,
        replacement_ppg=replacement_ppg,
        fpor_per_game=per_game,
        fpor_to_date=per_game * line.games,
        fpor_ros=per_game * remaining_weeks,
    )


def headshot_url(player_id: str, position: str) -> str:
    if position == "DEF":
        return f"https://sleepercdn.com/images/team_logos/nfl/{player_id.lower()}.png"
    return f"https://sleepercdn.com/content/nfl/players/thumb/{player_id}.jpg"


def team_names(users: Iterable[dict[str, Any]], rosters: Iterable[dict[str, Any]]) -> dict[int, str]:
    by_user = {}
    for user in users:
        meta = user.get("metadata") or {}
        by_user[user.get("user_id")] = meta.get("team_name") or user.get("display_name") or "Unknown"
    names: dict[int, str] = {}
    for roster in rosters:
        roster_id = roster.get("roster_id")
        names[roster_id] = by_user.get(roster.get("owner_id"), f"Team {roster_id}")
    return names
