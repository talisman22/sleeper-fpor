from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Any

from sleeper_fpor.config import DRAFT_PICKS
from sleeper_fpor.players import Player, match_adp_player

# Fallback jitter (in picks) for players FFC reports with 0/missing stdev —
# typically late-round players drafted too rarely for FFC to compute a spread.
DEFAULT_STDEV = 1.5


@dataclass(frozen=True)
class DraftedPick:
    season: int
    overall: int
    round_num: int
    slot: int
    adp: float
    ffc_name: str
    position: str
    player_id: str | None


@dataclass(frozen=True)
class MatchedEntry:
    """An FFC ADP row resolved to a Sleeper player, order-independent.

    Matching (name/position/team -> player_id, with de-dup of collisions) only
    needs to happen once per season; draft order can then be resampled many
    times over the same matched entries for Monte Carlo simulation.
    """

    ffc_name: str
    position: str
    adp: float
    stdev: float
    player_id: str | None


def snake_pick(overall: int, teams: int = 16) -> tuple[int, int]:
    round_num = (overall - 1) // teams + 1
    pos_in_round = (overall - 1) % teams
    if round_num % 2 == 1:
        slot = pos_in_round + 1
    else:
        slot = teams - pos_in_round
    return round_num, slot


def picks_for_slot(slot: int, teams: int, rounds: int) -> list[int]:
    picks: list[int] = []
    for round_num in range(1, rounds + 1):
        if round_num % 2 == 1:
            overall = (round_num - 1) * teams + slot
        else:
            overall = round_num * teams - slot + 1
        picks.append(overall)
    return picks


def match_board(
    adp_payload: dict[str, Any],
    lookup: dict[tuple[str, str], str],
    players: dict[str, Player],
) -> list[MatchedEntry]:
    """Resolve FFC ADP rows to Sleeper player IDs, in ADP order (for stable dedup)."""
    rows = sorted(adp_payload.get("players") or [], key=lambda row: row.get("adp", 9999))
    matched: list[MatchedEntry] = []
    used: set[str] = set()
    for row in rows:
        name = row.get("name") or ""
        position = row.get("position") or ""
        team = row.get("team")
        player_id = match_adp_player(name, position, team, lookup, players)
        if player_id and player_id in used:
            player_id = None
        if player_id:
            used.add(player_id)
        matched.append(
            MatchedEntry(
                ffc_name=name,
                position=position,
                adp=float(row.get("adp") or 9999),
                stdev=float(row.get("stdev") or 0.0),
                player_id=player_id,
            )
        )
    return matched


def _assign_from_order(season: int, ordered: list[MatchedEntry]) -> list[DraftedPick]:
    assigned: list[DraftedPick] = []
    for overall, m in enumerate(ordered[:DRAFT_PICKS], start=1):
        round_num, slot = snake_pick(overall)
        assigned.append(
            DraftedPick(
                season=season,
                overall=overall,
                round_num=round_num,
                slot=slot,
                adp=m.adp,
                ffc_name=m.ffc_name,
                position=m.position,
                player_id=m.player_id,
            )
        )
    return assigned


def assign_board(
    season: int,
    adp_payload: dict[str, Any],
    lookup: dict[tuple[str, str], str],
    players: dict[str, Player],
) -> list[DraftedPick]:
    """Deterministic board: straight ADP order, no jitter."""
    matches = match_board(adp_payload, lookup, players)
    return _assign_from_order(season, matches)


def simulate_board(
    season: int,
    matches: list[MatchedEntry],
    rng: random.Random,
) -> list[DraftedPick]:
    """One Monte Carlo draft: jitter each player's ADP by their real FFC stdev,
    then re-sort into a fresh snake order. Real drafters don't follow ADP
    exactly; this samples from the actual observed spread of where a player
    goes instead of pinning every player to their mean pick.
    """
    jittered = [
        (rng.gauss(m.adp, m.stdev if m.stdev > 0 else DEFAULT_STDEV), m) for m in matches
    ]
    jittered.sort(key=lambda pair: pair[0])
    ordered = [m for _, m in jittered]
    return _assign_from_order(season, ordered)
