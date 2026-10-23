import pytest

from sleeper_fpor.league import (
    BENCH,
    FREE_AGENT,
    RESERVE,
    STARTER,
    PlayerLine,
    PoolMode,
    build_lines,
    rank_replacement_levels,
    replacement_levels,
    roster_spots,
    score_stats,
    value_player,
)
from sleeper_fpor.players import Player


def line(pid, pos, status, ppg, games=4):
    return PlayerLine(pid, pid, pos, "KC", None if status == FREE_AGENT else 1, status, games, ppg * games)


def test_score_stats_uses_league_settings():
    stats = {"rec": 5, "rec_yd": 60, "rec_td": 1, "pts_ppr": 17.0, "gp": 1}
    assert score_stats(stats, {"rec": 0.5, "rec_yd": 0.1, "rec_td": 6}) == pytest.approx(14.5)
    assert score_stats(stats, None) == 17.0


def test_roster_spots_statuses():
    spots = roster_spots(
        [{"roster_id": 3, "players": ["a", "b", "c"], "starters": ["a"], "reserve": ["c"], "taxi": None}]
    )
    assert spots["a"].status == STARTER
    assert spots["b"].status == BENCH
    assert spots["c"].status == RESERVE
    assert spots["a"].roster_id == 3


def test_build_lines_counts_only_games_played():
    players = {"p1": Player("p1", "Joe", "WR", "KC"), "p2": Player("p2", "Moe", "WR", "KC")}
    spots = roster_spots([{"roster_id": 1, "players": ["p1"], "starters": ["p1"]}])
    weekly = {
        1: {"p1": {"gp": 1, "pts_ppr": 10.0}, "p2": {"gp": 1, "pts_ppr": 4.0}},
        2: {"p1": {"gms_active": 1, "pts_ppr": 0.0}},  # active, didn't play: not a game
    }
    lines = build_lines(weekly, players, spots, None)
    assert lines["p1"].games == 1 and lines["p1"].ppg == 10.0
    assert lines["p2"].status == FREE_AGENT


def test_replacement_pool_modes():
    lines = [
        line("fa1", "RB", FREE_AGENT, 10),
        line("fa2", "RB", FREE_AGENT, 6),
        line("fa3", "RB", FREE_AGENT, 20, games=1),  # fluke, filtered by min_games
        line("bn1", "RB", BENCH, 14),
        line("st1", "RB", STARTER, 25),
    ]
    waiver = replacement_levels(lines, PoolMode.WAIVER, top_n=2, min_games=2, positions=["RB"])
    assert waiver["RB"].ppg == pytest.approx(8.0)
    both = replacement_levels(lines, PoolMode.BENCH_AND_WAIVER, top_n=2, min_games=2, positions=["RB"])
    assert both["RB"].ppg == pytest.approx(12.0)
    assert [p.player_id for p in both["RB"].pool] == ["bn1", "fa1"]


def test_empty_pool_is_zero():
    levels = replacement_levels([], PoolMode.WAIVER, top_n=5, min_games=1, positions=["K"])
    assert levels["K"].ppg == 0.0


def test_value_player_floor_and_projection():
    lines = [line("fa1", "WR", FREE_AGENT, 10), line("star", "WR", STARTER, 18), line("dud", "WR", BENCH, 7)]
    levels = replacement_levels(lines, PoolMode.WAIVER, top_n=1, min_games=1, positions=["WR"])
    star = value_player(lines[1], levels, remaining_weeks=10)
    assert star.fpor_per_game == pytest.approx(8.0)
    assert star.fpor_to_date == pytest.approx(32.0)
    assert star.fpor_ros == pytest.approx(80.0)
    assert value_player(lines[2], levels, 10).fpor_per_game == 0.0
    assert value_player(lines[2], levels, 10, floor_at_replacement=False).fpor_per_game == pytest.approx(-3.0)


def test_rank_replacement_uses_nth_best_league_wide():
    lines = [line(f"rb{i}", "RB", STARTER if i < 3 else FREE_AGENT, 20 - i) for i in range(5)]
    lines.append(line("fluke", "RB", FREE_AGENT, 30, games=1))
    levels = rank_replacement_levels(lines, {"RB": 3, "QB": 16}, min_games=2)
    assert levels["RB"].ppg == pytest.approx(18.0)  # rb0=20, rb1=19, rb2=18; fluke filtered
    assert levels["RB"].pool[0].player_id == "rb2"
    assert levels["QB"].ppg == 0.0
    short = rank_replacement_levels(lines, {"RB": 25}, min_games=2)
    assert short["RB"].ppg == pytest.approx(16.0)  # fewer than 25: last qualifier
