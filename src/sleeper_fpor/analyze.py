from __future__ import annotations

import random
from collections import defaultdict
from dataclasses import dataclass

from sleeper_fpor.config import DRAFT_PICKS, DRAFT_ROUNDS, MC_ITERATIONS, MC_SEED, SEASONS, TEAMS, WEEKS
from sleeper_fpor.client import ApiClient
from sleeper_fpor.draft import assign_board, match_board, picks_for_slot, simulate_board, snake_pick
from sleeper_fpor.fpor import replacement_levels, week_scores, weekly_fpor
from sleeper_fpor.players import Player, build_lookup, load_players


@dataclass
class PickSeasonValue:
    season: int
    overall: int
    fpor: float
    player_id: str | None
    player_name: str
    position: str
    matched: bool


def fetch_all(client: ApiClient) -> None:
    client.sleeper_players()
    for season in SEASONS:
        client.ffc_adp(season)
        for week in WEEKS:
            client.sleeper_week_stats(season, week)


def _season_player_fpor(
    client: ApiClient,
    season: int,
    players: dict[str, Player],
    player_ids: set[str],
) -> dict[str, float]:
    """Season-total FPoR per player, independent of draft order/position on the board.

    A week a player has no recorded stats (bye, injury, inactive, not yet worth a
    roster spot) contributes 0, not a negative replacement penalty -- this assumes
    a manager benches a clear dud for a replacement-level streamer rather than
    eating a zero every week that player doesn't suit up.
    """
    season_fpor: dict[str, float] = {player_id: 0.0 for player_id in player_ids}
    for week in WEEKS:
        scores = week_scores(client.sleeper_week_stats(season, week), players)
        replacement = replacement_levels(scores)
        week_vals = weekly_fpor(scores, replacement)
        for player_id in player_ids:
            if player_id in week_vals:
                season_fpor[player_id] += week_vals[player_id]
            # else: no stats this week -> assume a replacement-level streamer, contributes 0
    return season_fpor


def _summarize(vals: list[float]) -> dict:
    vals_sorted = sorted(vals)
    n = len(vals_sorted)
    mean = sum(vals_sorted) / n
    variance = sum((v - mean) ** 2 for v in vals_sorted) / n

    def pct(p: float) -> float:
        idx = min(n - 1, max(0, round(p * (n - 1))))
        return vals_sorted[idx]

    return {
        "mean": round(mean, 2),
        "std": round(variance**0.5, 2),
        "p10": round(pct(0.10), 2),
        "p50": round(pct(0.50), 2),
        "p90": round(pct(0.90), 2),
        "n": n,
    }


def analyze(client: ApiClient) -> dict:
    players = load_players(client.sleeper_players())
    lookup = build_lookup(players)

    season_pick_values: list[PickSeasonValue] = []
    unmatched: list[dict] = []

    for season in SEASONS:
        board = assign_board(season, client.ffc_adp(season), lookup, players)
        for pick in board:
            if pick.player_id is None:
                unmatched.append(
                    {"season": season, "overall": pick.overall, "name": pick.ffc_name, "pos": pick.position}
                )

        board_player_ids = {pick.player_id for pick in board if pick.player_id}
        season_fpor = _season_player_fpor(client, season, players, board_player_ids)

        for pick in board:
            name = pick.ffc_name
            pos = pick.position
            if pick.player_id and pick.player_id in players:
                name = players[pick.player_id].name
                pos = players[pick.player_id].position
            season_pick_values.append(
                PickSeasonValue(
                    season=season,
                    overall=pick.overall,
                    fpor=season_fpor.get(pick.player_id or "", 0.0),
                    player_id=pick.player_id,
                    player_name=name,
                    position=pos,
                    matched=pick.player_id is not None,
                )
            )

    by_pick: dict[int, list[PickSeasonValue]] = defaultdict(list)
    for row in season_pick_values:
        by_pick[row.overall].append(row)

    pick_rows = []
    for overall in range(1, DRAFT_PICKS + 1):
        years = by_pick.get(overall, [])
        if not years:
            continue
        round_num, slot = snake_pick(overall)
        avg = sum(item.fpor for item in years) / len(years)
        pick_rows.append(
            {
                "overall": overall,
                "round": round_num,
                "slot": slot,
                "label": f"{round_num}.{slot:02d}",
                "avg_fpor": round(avg, 2),
                "by_season": {item.season: round(item.fpor, 2) for item in years},
                "players": [
                    {
                        "season": item.season,
                        "name": item.player_name,
                        "position": item.position,
                        "fpor": round(item.fpor, 2),
                        "matched": item.matched,
                    }
                    for item in years
                ],
            }
        )

    slot_rows = []
    for slot in range(1, TEAMS + 1):
        picks = picks_for_slot(slot, TEAMS, DRAFT_ROUNDS)
        pick_avgs = []
        for overall in picks:
            years = by_pick.get(overall, [])
            if years:
                pick_avgs.append(sum(item.fpor for item in years) / len(years))
        total = sum(pick_avgs)
        slot_rows.append(
            {
                "slot": slot,
                "picks": picks,
                "avg_total_fpor": round(total, 2),
                "avg_per_pick": round(total / len(pick_avgs), 2) if pick_avgs else 0.0,
            }
        )

    best_pick = max(pick_rows, key=lambda row: row["avg_fpor"]) if pick_rows else None
    worst_pick = min(pick_rows, key=lambda row: row["avg_fpor"]) if pick_rows else None
    best_slot = max(slot_rows, key=lambda row: row["avg_total_fpor"]) if slot_rows else None
    median_slot = sorted(slot_rows, key=lambda row: row["avg_total_fpor"])[len(slot_rows) // 2] if slot_rows else None

    return {
        "league": {
            "teams": TEAMS,
            "scoring": "full PPR",
            "starters": "QB, 2RB, 2WR, FLEX, DEF, K",
            "bench": 4,
            "ir": 3,
            "rounds": DRAFT_ROUNDS,
            "seasons": list(SEASONS),
        },
        "notes": [
            "Weekly PPR stats come from Sleeper.",
            "Draft boards use Fantasy Football Calculator 12-team PPR ADP rank as overall pick order (FFC has no 16-team ADP).",
            "Replacement is the first non-starter each week after filling 16 lineups (including FLEX).",
            "Bye/injury/inactive weeks contribute 0, not a penalty -- assumes the manager benches "
            "a clear dud for a replacement-level streamer rather than starting a zero.",
        ],
        "best_overall_pick": best_pick,
        "worst_overall_pick": worst_pick,
        "best_snake_slot": best_slot,
        "median_snake_slot": median_slot,
        "slot_edge_over_median": (
            round(best_slot["avg_total_fpor"] - median_slot["avg_total_fpor"], 2)
            if best_slot and median_slot
            else None
        ),
        "picks": pick_rows,
        "slots": slot_rows,
        "unmatched_adp": unmatched,
        "unmatched_count": len(unmatched),
    }


def simulate_monte_carlo(
    client: ApiClient, iterations: int = MC_ITERATIONS, seed: int = MC_SEED
) -> dict:
    """Resample draft order (jittered by FFC's real per-player ADP stdev) many times
    per season, and aggregate the resulting FPoR distribution per pick and per slot.

    Per-player weekly FPoR doesn't depend on draft order, so it's computed once per
    season and reused across every simulated draw -- only the pick/slot each player
    lands on changes between iterations.
    """
    players = load_players(client.sleeper_players())
    lookup = build_lookup(players)
    rng = random.Random(seed)

    pick_samples: dict[int, list[float]] = defaultdict(list)
    slot_samples: dict[int, list[float]] = defaultdict(list)

    for season in SEASONS:
        matches = match_board(client.ffc_adp(season), lookup, players)
        matched_ids = {m.player_id for m in matches if m.player_id}
        season_fpor = _season_player_fpor(client, season, players, matched_ids)

        for _ in range(iterations):
            board = simulate_board(season, matches, rng)
            slot_totals: dict[int, float] = defaultdict(float)
            for pick in board:
                val = season_fpor.get(pick.player_id, 0.0) if pick.player_id else 0.0
                pick_samples[pick.overall].append(val)
                slot_totals[pick.slot] += val
            for slot, total in slot_totals.items():
                slot_samples[slot].append(total)

    pick_rows = []
    for overall in range(1, DRAFT_PICKS + 1):
        vals = pick_samples.get(overall)
        if not vals:
            continue
        round_num, slot = snake_pick(overall)
        pick_rows.append(
            {
                "overall": overall,
                "round": round_num,
                "slot": slot,
                "label": f"{round_num}.{slot:02d}",
                **_summarize(vals),
            }
        )

    slot_rows = []
    for slot in range(1, TEAMS + 1):
        vals = slot_samples.get(slot)
        if not vals:
            continue
        slot_rows.append({"slot": slot, **_summarize(vals)})

    best_pick = max(pick_rows, key=lambda row: row["mean"]) if pick_rows else None
    worst_pick = min(pick_rows, key=lambda row: row["mean"]) if pick_rows else None
    best_slot = max(slot_rows, key=lambda row: row["mean"]) if slot_rows else None
    median_slot = (
        sorted(slot_rows, key=lambda row: row["mean"])[len(slot_rows) // 2] if slot_rows else None
    )

    total_draws = iterations * len(SEASONS)
    return {
        "seasons": list(SEASONS),
        "iterations_per_season": iterations,
        "total_draws_per_pick": total_draws,
        "seed": seed,
        "notes": [
            "Each simulated draft jitters every player's ADP by FFC's observed stdev "
            "(the real spread of where that player actually got drafted), then re-sorts into a fresh snake order.",
            f"{iterations} simulated drafts/season x {len(SEASONS)} seasons = {total_draws} draws per pick/slot.",
            "Per-player weekly FPoR doesn't depend on draft order, so it's computed once per "
            "season and reused across every simulated draw -- only who lands on each pick changes.",
            "Bye/injury/inactive weeks contribute 0, not a penalty -- assumes the manager benches "
            "a clear dud for a replacement-level streamer rather than starting a zero.",
        ],
        "best_overall_pick": best_pick,
        "worst_overall_pick": worst_pick,
        "best_snake_slot": best_slot,
        "median_snake_slot": median_slot,
        "slot_edge_over_median": (
            round(best_slot["mean"] - median_slot["mean"], 2) if best_slot and median_slot else None
        ),
        "picks": pick_rows,
        "slots": slot_rows,
    }
