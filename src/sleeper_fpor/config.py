import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
LOCAL_LEAGUE_FILE = ROOT / ".sleeper_league_id"  # git-ignored; keeps the ID out of the public repo

SEASONS = (2023, 2024, 2025)
WEEKS = range(1, 19)

TEAMS = 16
STARTER_SLOTS = {
    "QB": 1,
    "RB": 2,
    "WR": 2,
    "TE": 0,
    "FLEX": 1,
    "DEF": 1,
    "K": 1,
}
BENCH_SLOTS = 4
IR_SLOTS = 3
DRAFT_ROUNDS = sum(STARTER_SLOTS.values()) + BENCH_SLOTS  # 12; IR is not drafted
DRAFT_PICKS = TEAMS * DRAFT_ROUNDS

SCORING = "ppr"
FLEX_POSITIONS = ("RB", "WR", "TE")

# Monte Carlo draft-order simulation (jitter each player's ADP by FFC's
# observed stdev, redraw the board, repeat) instead of a single fixed ADP order.
MC_ITERATIONS = 500
MC_SEED = 42


def _league_id() -> str:
    """Default league: SLEEPER_LEAGUE_ID env var, else the git-ignored .sleeper_league_id file."""
    if os.environ.get("SLEEPER_LEAGUE_ID"):
        return os.environ["SLEEPER_LEAGUE_ID"].strip()
    if LOCAL_LEAGUE_FILE.exists():
        return LOCAL_LEAGUE_FILE.read_text(encoding="utf-8").strip()
    return ""


LEAGUE_ID = _league_id()

SLEEPER_BASE = "https://api.sleeper.app/v1"
FFC_ADP_URL = "https://fantasyfootballcalculator.com/api/v1/adp/ppr"

USER_AGENT = "sleeper-fpor/0.1 (personal research; +https://github.com)"
