import json

from sleeper_fpor.draft_site import completed_weeks, make_bundle, write_site
from sleeper_fpor.players import Player


def test_completed_weeks():
    league = {"season": "2026"}
    assert completed_weeks(league, {"season": "2026", "season_type": "regular", "week": 7}) == 6
    assert completed_weeks(league, {"season": "2026", "season_type": "pre", "week": 0}) == 0
    assert completed_weeks(league, {"season": "2027", "season_type": "regular", "week": 3}) == 18


def make():
    players = {
        "a": Player("a", "Al Pha", "RB", "KC"),
        "b": Player("b", "Bea Ta", "WR", "SF"),
        "w": Player("w", "Wa Ve", "TE", "NE"),
        "x": Player("x", "Ex Tra", "WR", "NE"),  # unrostered, undrafted: not in bundle
    }
    picks = [
        {"pick_no": 2, "round": 1, "player_id": "b", "roster_id": 2, "metadata": {"position": "WR", "first_name": "Bea", "last_name": "Ta"}},
        {"pick_no": 1, "round": 1, "player_id": "a", "roster_id": 1, "metadata": {"position": "RB", "first_name": "Al", "last_name": "Pha"}},
    ]
    rosters = [
        {"roster_id": 1, "owner_id": "u1", "players": ["a", "w"], "starters": ["a"]},
        {"roster_id": 2, "owner_id": "u2", "players": [], "starters": []},
    ]
    users = [{"user_id": "u1", "display_name": "one", "avatar": "av1", "metadata": {"team_name": "Team One"}}]
    weekly = {
        1: {"a": {"gp": 1, "rec": 2}, "w": {"gp": 1, "rec": 5}, "x": {"gp": 1, "rec": 9}},
        2: {"a": {"gp": 1, "rec": 4}, "b": {"gp": 1, "rec": 3}},
    }
    return make_bundle(
        league={"league_id": "L1", "name": " My League ", "season": "2026", "scoring_settings": {"rec": 1.0}},
        rosters=rosters, users=users, picks=picks, players=players, weekly_stats=weekly, weeks=2,
    )


def test_make_bundle_weekly_points_and_membership():
    bundle = make()
    assert bundle["league"] == {
        "name": "My League", "season": 2026, "teams": 2, "rounds": 1, "last_pick": 2, "completed_weeks": 2,
    }
    assert [p["player_id"] for p in bundle["picks"]] == ["a", "b"]
    assert set(bundle["players"]) == {"a", "b", "w"}
    assert bundle["players"]["a"]["weekly"] == [2.0, 4.0]          # scored with league settings
    assert bundle["players"]["b"]["weekly"] == [None, 3.0]         # missed week 1
    assert bundle["players"]["b"]["owner"] is None                 # drafted, since dropped
    assert bundle["players"]["w"]["owner"] == 1                    # undrafted pickup
    teams = {t["roster_id"]: t for t in bundle["teams"]}
    assert teams[1]["name"] == "Team One" and teams[1]["avatar"] == "av1" and teams[1]["draft_slot"] == 1
    assert teams[2]["draft_slot"] == 2


def test_write_site_copies_assets_and_data(tmp_path):
    out = write_site(tmp_path / "site", make())
    for name in ("index.html", "draft.js", "zone.js", "draft.css", "data.json", ".nojekyll"):
        assert (out / name).exists(), name
    published = (out / "data.json").read_text(encoding="utf-8")
    assert json.loads(published)["league"]["name"] == "My League"
    assert "L1" not in published  # the league ID never reaches the public site
