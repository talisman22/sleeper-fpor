from sleeper_fpor.draft import picks_for_slot, snake_pick
from sleeper_fpor.fpor import WeekScore, replacement_levels
from sleeper_fpor.players import normalize_name


def test_snake_slot_16():
    assert snake_pick(1) == (1, 1)
    assert snake_pick(16) == (1, 16)
    assert snake_pick(17) == (2, 16)
    assert snake_pick(32) == (2, 1)


def test_slot_one_picks():
    assert picks_for_slot(1, 16, 4) == [1, 32, 33, 64]


def test_normalize_name():
    assert normalize_name("Ja'Marr Chase") == "jamarr chase"
    assert normalize_name("Amon-Ra St. Brown Jr.") == "amon ra st brown"


def test_replacement_includes_flex():
    scores = []
    for i in range(40):
        scores.append(WeekScore(f"rb{i}", "RB", 20 - i * 0.1))
    for i in range(40):
        scores.append(WeekScore(f"wr{i}", "WR", 19 - i * 0.1))
    for i in range(20):
        scores.append(WeekScore(f"te{i}", "TE", 12 - i * 0.2))
    for i in range(20):
        scores.append(WeekScore(f"qb{i}", "QB", 25 - i))
    levels = replacement_levels(scores)
    assert "QB" in levels
    assert levels["QB"] == 9  # 17th QB after 16 starters
    # 32 RB + 32 WR locked; 16 flex from remaining RB/WR/TE
    assert levels["TE"] > 0
