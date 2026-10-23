"""Tests for web/zone.js -- the draft-zone math the page runs -- executed in embedded V8."""

import json
from pathlib import Path

import pytest

mini_racer = pytest.importorskip("py_mini_racer")

ZONE_JS = Path(__file__).resolve().parents[1] / "src" / "sleeper_fpor" / "web" / "zone.js"


@pytest.fixture(scope="module")
def zone():
    ctx = mini_racer.MiniRacer()
    ctx.eval(ZONE_JS.read_text(encoding="utf-8"))

    def call(fn, *args):
        payload = json.dumps(list(args))
        return json.loads(ctx.eval(f"JSON.stringify(Zone.{fn}(...{payload}))"))

    yield call
    ctx.close()


def pick(n, pos="RB", roster_id=1, pid=None, round_=1):
    return {"pick_no": n, "round": round_, "player_id": pid or f"p{n}", "roster_id": roster_id, "pos": pos, "name": f"P{n}"}


def player(pos, weekly, owner=None):
    return {"name": "x", "pos": pos, "nfl": "KC", "owner": owner, "weekly": weekly}


def bundle(picks, players, teams=2, weeks=4):
    return {
        "league": {"teams": teams, "completed_weeks": weeks},
        "teams": [{"roster_id": r, "name": f"Team {r}"} for r in range(1, teams + 1)],
        "picks": picks,
        "players": players,
    }


def test_zone_excludes_self_and_players_without_games(zone):
    cands = [{"pick": pick(1), "value": 20}, {"pick": pick(2), "value": 10},
             {"pick": pick(3), "value": None}, {"pick": pick(4), "value": 6}, {"pick": pick(10), "value": 99}]
    base = zone("zoneBaseline", 2, "RB", cands, 2, "p2")
    assert base["value"] == pytest.approx(13.0)  # nearest two with games: picks 1 and 4
    assert set(base["neighbors"]) == {"p1", "p4"}


def test_flex_group_mixes_rb_wr_te_but_not_qb(zone):
    cands = [{"pick": pick(1, "QB"), "value": 30}, {"pick": pick(2, "WR"), "value": 14},
             {"pick": pick(3, "TE"), "value": 10}, {"pick": pick(4, "RB"), "value": 12},
             {"pick": pick(5, "QB"), "value": 25}, {"pick": pick(9, "QB"), "value": 15}]
    assert zone("zoneBaseline", 1, "WR", cands, 3, None)["value"] == pytest.approx(12.0)
    qb = zone("zoneBaseline", 4, "QB", cands, 2, "p5")
    assert set(qb["neighbors"]) == {"p1", "p9"}  # only QBs, however far away


def test_missed_games_do_not_count_against_a_player(zone):
    line = zone("seasonLine", player("RB", [16, None, None, 16]), 4)
    assert line == {"games": 2, "points": 32}
    assert zone("gamesPpg", line, 1) == pytest.approx(16.0)
    assert zone("gamesPpg", line, 3) is None  # held back until 3 games played
    assert zone("seasonLine", player("RB", [16, None, None, 16]), 1) == {"games": 1, "points": 16}  # through week 1


def test_compute_origins_fpor_and_team_totals(zone):
    picks = [pick(1, "RB", 1, "a"), pick(2, "WR", 2, "b"), pick(3, "TE", 1, "c")]
    players = {
        "a": player("RB", [20, 20], owner=1),   # own pick
        "b": player("WR", [10, 10], owner=1),   # drafted by 2, now on 1
        "c": player("TE", [6, 6]),              # dropped
        "w": player("RB", [12, 12], owner=2),   # undrafted pickup
    }
    out = zone("compute", bundle(picks, players, weeks=2), {"neighbors": 1, "minGames": 1})
    by_id = {p["id"]: p for p in out["players"]}
    assert by_id["a"]["origin"] == "own_pick" and by_id["b"]["origin"] == "acquired"
    assert by_id["w"]["origin"] == "pickup" and by_id["c"]["origin"] is None
    assert by_id["a"]["fpor"] == pytest.approx(10)   # nearest flex pick: 2 (10 PPG)
    assert by_id["b"]["fpor"] == pytest.approx(-10)  # tie at distance 1 -> earlier pick (20)
    assert by_id["w"]["fpor"] == pytest.approx(6)    # end of draft: pick 3 (6 PPG)
    assert by_id["b"]["drafted_by"] == "Team 2" and by_id["b"]["owner"] == "Team 1"

    teams = {t["roster_id"]: t for t in out["teams"]}
    assert teams[1]["draft_class"] == pytest.approx(10 + (6 - 10))  # a and c
    assert teams[1]["roster"]["acquired"] == pytest.approx(-10)
    assert teams[2]["roster_total"] == pytest.approx(6)


def test_compute_pick_in_round_uses_league_size(zone):
    picks = [pick(n, "RB", 1, round_=(n - 1) // 16 + 1) for n in (1, 16, 17, 18, 33)]
    players = {p["player_id"]: player("RB", [10]) for p in picks}
    out = zone("compute", bundle(picks, players, teams=16, weeks=1), {"neighbors": 2, "minGames": 1})
    labels = {p["pick"]: (p["round"], p["pick_in_round"]) for p in out["players"]}
    assert labels == {1: (1, 1), 16: (1, 16), 17: (2, 1), 18: (2, 2), 33: (3, 1)}


def test_compute_clamps_controls_to_completed_weeks(zone):
    picks = [pick(1, pid="a")]
    out = zone("compute", bundle(picks, {"a": player("RB", [10, 12])}, weeks=2),
               {"neighbors": 6, "minGames": 5, "through": 9})
    assert out["league"]["through"] == 2 and out["settings"]["min_games"] == 2
