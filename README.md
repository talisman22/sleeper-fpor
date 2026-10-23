# 16-team PPR pick value (FPoR)

Weekly **fantasy points over replacement** for players taken at each draft pick, averaged across **2023–2025**.

## League

- 16 teams, snake, full PPR
- Starters: 1 QB, 2 RB, 2 WR, 1 FLEX (RB/WR/TE), 1 DEF, 1 K
- 4 bench, 3 IR (IR is not drafted; board is 12 rounds / 192 picks)

## Data

- **Sleeper** Python HTTP API: weekly regular-season `pts_ppr` (`/stats/nfl/regular/{season}/{week}`) plus the NFL player map
- **Fantasy Football Calculator** PPR ADP for board order. FFC does not publish 16-team ADP, so **12-team PPR ADP rank** is mapped onto overall picks 1–192

Replacement each week is the first player at that position who would **not** start after filling 16 lineups (including the flex). Bye/injury/inactive weeks contribute 0, not a penalty — assumes the manager benches a clear dud for a replacement-level streamer rather than starting a zero.

## Run

```bash
python -m venv .venv
.venv\Scripts\pip install -e .
.venv\Scripts\python -m sleeper_fpor
```

`fetch` only downloads/caches; `analyze` uses the cache; default `run` does both.

Outputs: `data/report.json` and `data/report.html`.

## Trade analyzer (Streamlit)

Interactive trade evaluator for your own Sleeper league, valued in **fantasy points over replacement** with a *dynamic* replacement level:

- **Replacement** at each position = average PPG of the **top N** players in a pool (default 5), where the pool is either
  - **Waiver wire only** — unrostered players (what you could add today), or
  - **Bench + waiver wire** — also every rostered bench player (the cheaply tradeable tier).
  A minimum-games filter keeps one-week waiver flukes from setting the bar.
- Points are computed from each week's Sleeper stats using **your league's `scoring_settings`**.
- Each player gets FPoR/game, FPoR to date, and a naive rest-of-season projection (FPoR/game × weeks remaining). With "floor at replacement" on, sub-replacement players are worth 0 (you'd cut them), so the open roster spot in a 2-for-1 is valued correctly at replacement.
- Search/add/remove players per side with autocomplete and headshot thumbnails.

```bash
.venv\Scripts\pip install -e ".[app]"
set SLEEPER_LEAGUE_ID=<your league id>   # or save it in .sleeper_league_id; can also be entered in the sidebar
.venv\Scripts\sleeper-trade            # or: streamlit run src/sleeper_fpor/app.py
```

The league ID is in the Sleeper URL (`sleeper.com/leagues/<id>/...`), or use the sidebar's username lookup. The page URL keeps `?league=<id>` so it can be bookmarked.

## Draft-zone FPoR web page

How did each pick turn out compared with the players drafted around it? For a player taken at pick *p*, replacement is the average **points per game played** of the nearest N picks (default 6) in the same **position group**:

| Group | Positions | Why |
|---|---|---|
| QB | QB | one QB slot; QBs only compete with QBs |
| Flex | RB, WR, TE | all three can fill the flex spot |
| K / DEF | K, DEF | each compared only with its own position |

- Only games played count, so injuries and byes never count against a player. Players need 3 games (adjustable) before they're judged.
- A player never sets his own bar. Undrafted pickups on current rosters are measured against the last picks of the draft.
- **Recent form:** the same comparison over each player's last N games *played* (missed games are skipped), weighted toward recent games with an adjustable half-life (default: last 4 games, 3-game half-life). The zone uses its neighbors' recent form too, so it stays like-for-like. A second view plots recent against season FPoR to show who's rising or cooling.
- Team views: **draft class value** (everyone a team drafted, wherever they are now) and **current roster value**, split into own picks, players acquired from other teams, and undrafted pickups.

**How it's built.** Python fetches Sleeper data and scores it with the league's settings into one small `data.json`. The page (`src/sleeper_fpor/web/`) does the zone math in the browser (`zone.js`), so the sliders are instant and the site can be hosted as plain files.

```bash
.venv\Scripts\pip install -e ".[web,dev]"
.venv\Scripts\sleeper-draft                     # local, live data: http://127.0.0.1:8000
.venv\Scripts\sleeper-draft-build --out site    # static site in ./site
```

### Deploying to GitHub Pages

`.github/workflows/deploy-draft-site.yml` builds the site and publishes it to GitHub Pages on every push to `main`, every day at 11:00 UTC, and early Tuesday after Monday Night Football. One-time setup:

1. Push this repo to GitHub (public: free Pages needs a public repo).
2. Add your league ID as a repository **secret** named `SLEEPER_LEAGUE_ID` (**Settings → Secrets and variables → Actions → New repository secret**). GitHub keeps secrets encrypted, never displays them, and masks them in workflow logs.
3. In the repo, go to **Settings → Pages → Build and deployment → Source** and choose **GitHub Actions**.

The league ID is not stored in the code. Locally, set `SLEEPER_LEAGUE_ID` or put the ID in a `.sleeper_league_id` file at the repo root, which git ignores. The published `data.json` doesn't include it either.

To refresh right away, open **Actions → Deploy draft-zone FPoR site → Run workflow**.
