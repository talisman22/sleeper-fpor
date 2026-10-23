"""Streamlit trade analyzer: fantasy points over a dynamic, league-specific replacement level.

Run with:  streamlit run src/sleeper_fpor/app.py   (or the ``sleeper-trade`` script)
"""

from __future__ import annotations

from typing import Any

import altair as alt
import pandas as pd
import streamlit as st

from sleeper_fpor.client import ApiClient
from sleeper_fpor.config import LEAGUE_ID, SLEEPER_BASE
from sleeper_fpor.league import (
    BENCH,
    DEFAULT_REPLACEMENT_RANKS,
    FANTASY_POSITIONS,
    FREE_AGENT,
    RESERVE,
    STARTER,
    TAXI,
    PlayerLine,
    PlayerValue,
    PoolMode,
    build_lines,
    headshot_url,
    rank_replacement_levels,
    replacement_levels,
    roster_spots,
    team_names,
    value_player,
)
from sleeper_fpor.player_search import player_search
from sleeper_fpor.players import Player, load_players

PLAYERS_MAX_AGE_S = 24 * 3600
LIVE_TTL_S = 15 * 60
REGULAR_SEASON_WEEKS = 18
SIDES = ("A", "B")
# Categorical slots 1-2 of the dataviz reference palette (validated adjacent pair).
SIDE_COLORS = {"A": "#2a78d6", "B": "#eb6834"}
STATUS_LABELS = {STARTER: "Starter", BENCH: "Bench", RESERVE: "IR", TAXI: "Taxi", FREE_AGENT: "Free agent"}
FLEX_SLOTS = {
    "FLEX": ("RB", "WR", "TE"),
    "WRRB_FLEX": ("RB", "WR"),
    "REC_FLEX": ("WR", "TE"),
    "SUPER_FLEX": ("QB", "RB", "WR", "TE"),
}
BASIS = {
    "ros": "Rest of season (projected)",
    "per_game": "Per game",
    "to_date": "Season to date",
}


# ---------------------------------------------------------------------------
# Data loading (cached)
# ---------------------------------------------------------------------------


@st.cache_data(ttl=LIVE_TTL_S, show_spinner=False)
def fetch_league(league_id: str) -> dict[str, Any]:
    with ApiClient(pause_s=0.0) as client:
        return {
            "league": client.sleeper_league(league_id),
            "rosters": client.sleeper_rosters(league_id),
            "users": client.sleeper_users(league_id),
            "state": client.sleeper_state(),
        }


@st.cache_data(ttl=PLAYERS_MAX_AGE_S, show_spinner=False)
def fetch_players() -> dict[str, Player]:
    with ApiClient(pause_s=0.0) as client:
        return load_players(client.sleeper_players(max_age_s=PLAYERS_MAX_AGE_S))


@st.cache_data(ttl=LIVE_TTL_S, show_spinner=False)
def fetch_week(season: int, week: int, live: bool) -> dict[str, Any]:
    with ApiClient(pause_s=0.0) as client:
        if live:
            return client.sleeper_week_stats_live(season, week) or {}
        return client.sleeper_week_stats(season, week) or {}


@st.cache_data(ttl=LIVE_TTL_S, show_spinner=False)
def find_leagues(username: str, season: int) -> list[dict[str, Any]]:
    with ApiClient(pause_s=0.0) as client:
        user = client.get_json(f"{SLEEPER_BASE}/user/{username}")
        if not user:
            return []
        leagues = client.get_json(f"{SLEEPER_BASE}/user/{user['user_id']}/leagues/nfl/{season}")
        return [{"league_id": lg["league_id"], "name": lg["name"]} for lg in leagues or []]


def season_weeks(league: dict[str, Any], state: dict[str, Any]) -> tuple[int, int, bool]:
    """(max selectable week, default window end, season in progress)."""
    league_season = int(league["season"])
    state_season = int(state.get("season") or league_season)
    if league_season < state_season or state.get("season_type") == "post":
        return REGULAR_SEASON_WEEKS, REGULAR_SEASON_WEEKS, False
    if state.get("season_type") == "pre":
        return 1, 1, True
    current = int(state.get("week") or 1)
    return min(current, REGULAR_SEASON_WEEKS), max(current - 1, 1), True


def league_positions(roster_positions: list[str]) -> tuple[str, ...]:
    used = set()
    for slot in roster_positions:
        if slot in FANTASY_POSITIONS:
            used.add(slot)
        used.update(FLEX_SLOTS.get(slot, ()))
    return tuple(pos for pos in FANTASY_POSITIONS if pos in used) or FANTASY_POSITIONS


# ---------------------------------------------------------------------------
# UI helpers
# ---------------------------------------------------------------------------


def basis_value(value: PlayerValue, basis: str) -> float:
    return {"ros": value.fpor_ros, "per_game": value.fpor_per_game, "to_date": value.fpor_to_date}[basis]


def search_options(
    lines: list[PlayerLine],
    values: dict[str, PlayerValue],
    names: dict[int, str],
) -> list[dict[str, Any]]:
    ranked = sorted(lines, key=lambda line: (values[line.player_id].fpor_per_game, line.ppg), reverse=True)
    return [
        {
            "id": line.player_id,
            "name": line.name,
            "pos": line.position,
            "team": line.team or "",
            "img": headshot_url(line.player_id, line.position),
            "sub": " · ".join(
                [line.position, line.team or "FA", names.get(line.roster_id, "Free agent")]
            ),
            "meta": f"{line.ppg:.1f} PPG · {values[line.player_id].fpor_per_game:+.1f}",
        }
        for line in ranked
    ]


def remove_player(side: str, player_id: str) -> None:
    st.session_state.trade[side] = [pid for pid in st.session_state.trade[side] if pid != player_id]


def add_player(side: str, picked: str) -> None:
    for other in SIDES:  # a player can only be on one side of a trade
        if other != side and picked in st.session_state.trade[other]:
            remove_player(other, picked)
    if picked not in st.session_state.trade[side]:
        st.session_state.trade[side].append(picked)


def player_card(side: str, value: PlayerValue, basis: str, names: dict[int, str]) -> None:
    line = value.line
    with st.container(border=True):
        img, info, stat, remove = st.columns([1, 5, 2, 1], vertical_alignment="center")
        img.image(headshot_url(line.player_id, line.position), width=52)
        owner = names.get(line.roster_id, "Free agent")
        info.markdown(f"**{line.name}**")
        info.caption(
            f"{line.position} · {line.team or 'FA'} · {owner} · {STATUS_LABELS[line.status]}  \n"
            f"{line.ppg:.1f} PPG over {line.games} G · repl {value.replacement_ppg:.1f}"
        )
        stat.markdown(
            f"**{basis_value(value, basis):+.1f}**",
            help=f"FPoR/G {value.fpor_per_game:+.1f} · to date {value.fpor_to_date:+.1f} · "
            f"ROS {value.fpor_ros:+.1f}",
        )
        stat.caption("FPoR")
        remove.button(
            "",
            icon=":material/close:",
            key=f"rm_{side}_{line.player_id}",
            on_click=remove_player,
            args=(side, line.player_id),
            help="Remove from trade",
        )


def trade_chart(rows: pd.DataFrame, value_col: str, repl_col: str, label: str) -> alt.Chart:
    rows = rows.assign(value=rows[value_col], repl=rows[repl_col])
    domain = list(rows["side_label"].drop_duplicates())
    colors = [SIDE_COLORS[side] for side in rows.drop_duplicates("side_label")["side"]]
    ordered = rows.sort_values("value", ascending=False)
    base = alt.Chart(ordered).encode(
        y=alt.Y(
            "player:N",
            sort=None,  # keep the pre-sorted data order
            title=None,
            scale=alt.Scale(paddingInner=0.35),
            axis=alt.Axis(labelLimit=200),
        ),
        x=alt.X("value:Q", title=label),
    )
    bars = base.mark_bar(cornerRadiusEnd=4).encode(
        color=alt.Color(
            "side_label:N",
            scale=alt.Scale(domain=domain, range=colors),
            legend=alt.Legend(title=None, orient="top", labelLimit=400),
        ),
        tooltip=[
            alt.Tooltip("player:N", title="Player"),
            alt.Tooltip("side_label:N", title="Side"),
            alt.Tooltip("pos:N", title="Pos"),
            alt.Tooltip("ppg:Q", title="PPG", format=".1f"),
            alt.Tooltip("repl:Q", title="Replacement PPG", format=".1f"),
            alt.Tooltip("value:Q", title=label, format="+.1f"),
        ],
    )
    text = base.mark_text(align="left", dx=4).encode(text=alt.Text("value:Q", format="+.1f"))
    return (bars + text).properties(height=alt.Step(40))


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------


def main() -> None:
    st.set_page_config(page_title="Sleeper Trade FPoR", page_icon="🏈", layout="wide")
    st.session_state.setdefault("trade", {side: [] for side in SIDES})

    with st.sidebar:
        st.header("League")
        default_league = st.query_params.get("league") or LEAGUE_ID
        league_id = st.text_input("Sleeper league ID", value=default_league).strip()
        with st.expander("Find my league by username"):
            username = st.text_input("Sleeper username")
            season_guess = st.number_input("Season", value=2026, step=1)
            if username:
                try:
                    found = find_leagues(username.strip(), int(season_guess))
                except Exception as exc:  # noqa: BLE001 -- surface API errors in the UI
                    st.error(f"Lookup failed: {exc}")
                    found = []
                for lg in found:
                    st.code(lg["league_id"], language=None)
                    st.caption(lg["name"])
                if not found:
                    st.caption("No leagues found.")

    st.title("Trade analyzer — fantasy points over replacement")
    if not league_id:
        st.info("Enter your Sleeper league ID in the sidebar (or set `SLEEPER_LEAGUE_ID`).")
        return
    st.query_params["league"] = league_id

    try:
        with st.spinner("Loading league..."):
            bundle = fetch_league(league_id)
            players = fetch_players()
    except Exception as exc:  # noqa: BLE001
        st.error(f"Could not load league `{league_id}`: {exc}")
        return
    league, rosters, users, state = bundle["league"], bundle["rosters"], bundle["users"], bundle["state"]
    if not league:
        st.error(f"League `{league_id}` not found.")
        return

    season = int(league["season"])
    max_week, default_end, in_progress = season_weeks(league, state)
    positions = league_positions(league.get("roster_positions") or [])
    scoring = league.get("scoring_settings") or {}
    names = team_names(users, rosters)

    with st.sidebar:
        st.header("Replacement level")
        pool_labels = {PoolMode.WAIVER.value: "Waiver wire only", PoolMode.BENCH_AND_WAIVER.value: "Bench + waiver wire"}
        pool_mode = PoolMode(
            st.radio(
                "Replacement pool",
                options=list(pool_labels),
                format_func=pool_labels.get,
                help="Waiver only: what you could pick up today. Bench + waiver: also every rostered "
                "bench player — the cheaply tradeable tier.",
            )
        )
        top_n = st.slider("Average the top N pool players", 1, 15, 5)
        if max_week > 1:
            weeks = st.slider("Weeks to evaluate", 1, max_week, (1, default_end))
        else:
            weeks = (1, 1)
        span = weeks[1] - weeks[0] + 1
        min_games = st.slider(
            "Min games for pool players", 1, span, min(2, span),
            help="Keeps a one-week waiver fluke from setting the bar.",
        )

        st.header("Rank-based replacement")
        st.caption("Per-game chart: replacement = the Nth-best player league-wide at each position.")
        rank_cols = st.columns(3)
        ranks = {
            pos: int(
                rank_cols[i % 3].number_input(
                    f"{pos} rank", min_value=1, max_value=120,
                    value=DEFAULT_REPLACEMENT_RANKS.get(pos, len(rosters)), key=f"rank_{pos}",
                )
            )
            for i, pos in enumerate(positions)
        }

        st.header("Valuation")
        basis = st.radio("Compare trade by", list(BASIS), format_func=BASIS.get)
        through = st.number_input(
            "Value through week", min_value=weeks[1], max_value=REGULAR_SEASON_WEEKS,
            value=max(weeks[1], 17 if in_progress else weeks[1]),
            help="Rest-of-season value = FPoR/game × weeks after the evaluation window.",
        )
        remaining = int(through) - weeks[1]
        floor = st.checkbox(
            "Floor at replacement (no negative values)", value=True,
            help="A below-replacement player is worth 0 — you'd drop him for a waiver pickup. "
            "This also values the open roster spot in a 2-for-1 at replacement.",
        )

    with st.spinner(f"Loading {season} weeks {weeks[0]}–{weeks[1]} stats..."):
        weekly = {
            week: fetch_week(season, week, live=in_progress) for week in range(weeks[0], weeks[1] + 1)
        }
    spots = roster_spots(rosters)
    lines = build_lines(weekly, players, spots, scoring)
    levels = replacement_levels(lines.values(), pool_mode, top_n, min_games, positions)
    values = {
        pid: value_player(line, levels, remaining, floor)
        for pid, line in lines.items()
        if line.position in positions
    }
    rank_levels = rank_replacement_levels(lines.values(), ranks, min_games)
    rank_values = {pid: value_player(values[pid].line, rank_levels, remaining, floor) for pid in values}

    st.caption(
        f"**{league.get('name', league_id)}** · {season} · weeks {weeks[0]}–{weeks[1]} · "
        f"{len(rosters)} teams · scored with league settings · "
        f"replacement = top {top_n} "
        f"{'waiver' if pool_mode is PoolMode.WAIVER else 'bench + waiver'} players by PPG"
    )

    # --- Replacement levels strip ---
    level_cols = st.columns(len(positions))
    for col, pos in zip(level_cols, positions):
        col.metric(f"{pos} replacement", f"{levels[pos].ppg:.1f} PPG", help=f"{len(levels[pos].pool)} pool players")

    # --- Trade builder ---
    team_options = [None, *sorted(names, key=lambda rid: names[rid].lower())]
    trade = st.session_state.trade
    for side in SIDES:
        trade[side] = [pid for pid in trade[side] if pid in values]

    side_cols = st.columns(2, gap="large")
    for idx, (side, col) in enumerate(zip(SIDES, side_cols)):
        with col:
            team = st.selectbox(
                f"Side {side} sends",
                team_options,
                index=min(idx + 1, len(team_options) - 1),
                format_func=lambda rid: "Any team / free agents" if rid is None else names[rid],
                key=f"team_{side}",
            )
            pool = [
                line for pid, line in lines.items()
                if pid in values and (line.roster_id == team if team is not None else True)
                and (team is not None or line.roster_id is not None or line.games)
            ]
            picked = player_search(
                search_options(pool, values, names),
                key=f"search_{side}",
                exclude=trade["A"] + trade["B"],
                placeholder="Search by name, team or position…",
            )
            if picked and picked in values:
                add_player(side, picked)
                st.rerun()  # redraw both sides (and refresh search exclusions)
            for pid in trade[side]:
                player_card(side, values[pid], basis, names)
            if not trade[side]:
                st.caption("No players added yet.")

    side_label = {
        side: names.get(st.session_state.get(f"team_{side}"), f"Side {side}") for side in SIDES
    }
    if not (trade["A"] or trade["B"]):
        st.divider()
        st.caption("Add players to both sides to compare the trade.")
        render_replacement_details(levels, positions, names)
        return

    # --- Summary ---
    st.divider()
    totals = {side: sum(basis_value(values[pid], basis) for pid in trade[side]) for side in SIDES}
    unit = BASIS[basis].lower()
    summary_cols = st.columns(2)
    for side, col in zip(SIDES, summary_cols):
        other = "B" if side == "A" else "A"
        net = totals[other] - totals[side]
        col.metric(
            f"{side_label[side]} net FPoR ({unit})",
            f"{net:+.1f}",
            delta=f"gets {totals[other]:.1f} · gives {totals[side]:.1f}",
            delta_color="off",
            delta_arrow="off",
        )
    if basis == "ros" and remaining == 0:
        st.warning("No weeks remain after the evaluation window — pick another basis or raise 'Value through week'.")

    rows = pd.DataFrame(
        [
            {
                "side": side,
                "side_label": f"{side_label[side]} sends",
                "player": values[pid].line.name,
                "pos": values[pid].line.position,
                "img": headshot_url(pid, values[pid].line.position),
                "team": values[pid].line.team or "FA",
                "games": values[pid].line.games,
                "ppg": values[pid].line.ppg,
                "repl": values[pid].replacement_ppg,
                "fpor_pg": values[pid].fpor_per_game,
                "fpor_to_date": values[pid].fpor_to_date,
                "fpor_ros": values[pid].fpor_ros,
                "value": basis_value(values[pid], basis),
                "rank_repl": rank_values[pid].replacement_ppg,
                "rank_fpor_pg": rank_values[pid].fpor_per_game,
            }
            for side in SIDES
            for pid in trade[side]
        ]
    )
    st.subheader("Pool-based replacement")
    st.altair_chart(trade_chart(rows, "value", "repl", f"FPoR — {unit}"), width="stretch")
    st.dataframe(
        rows[[
            "img", "player", "side_label", "pos", "games", "ppg", "repl", "fpor_pg", "fpor_to_date", "fpor_ros",
            "rank_repl", "rank_fpor_pg",
        ]],
        hide_index=True,
        width="stretch",
        column_config={
            "img": st.column_config.ImageColumn("", width="small"),
            "player": "Player",
            "side_label": "Side",
            "pos": "Pos",
            "games": st.column_config.NumberColumn("G"),
            "ppg": st.column_config.NumberColumn("PPG", format="%.1f"),
            "repl": st.column_config.NumberColumn("Repl PPG", format="%.1f"),
            "fpor_pg": st.column_config.NumberColumn("FPoR/G", format="%+.1f"),
            "fpor_to_date": st.column_config.NumberColumn("FPoR to date", format="%+.1f"),
            "fpor_ros": st.column_config.NumberColumn(f"FPoR ROS ({remaining} wk)", format="%+.1f"),
            "rank_repl": st.column_config.NumberColumn("Rank repl PPG", format="%.1f"),
            "rank_fpor_pg": st.column_config.NumberColumn("FPoR/G (rank)", format="%+.1f"),
        },
    )

    render_rank_section(rows, rank_levels, positions, ranks, side_label)
    render_weekly(trade, values, levels, weeks)
    render_replacement_details(levels, positions, names)


def render_rank_section(
    rows: pd.DataFrame,
    rank_levels: dict[str, Any],
    positions: tuple[str, ...],
    ranks: dict[str, int],
    side_label: dict[str, str],
) -> None:
    st.subheader("Per game vs. positional-rank replacement")
    st.caption(
        " · ".join(
            f"{pos}{ranks[pos]} = {rank_levels[pos].ppg:.1f}"
            + (f" ({rank_levels[pos].pool[0].name})" if rank_levels[pos].pool else "")
            for pos in positions
        )
    )
    totals = rows.groupby("side")["rank_fpor_pg"].sum()
    cols = st.columns(2)
    for side, col in zip(SIDES, cols):
        other = "B" if side == "A" else "A"
        gets, gives = totals.get(other, 0.0), totals.get(side, 0.0)
        col.metric(
            f"{side_label[side]} net FPoR per game",
            f"{gets - gives:+.1f}",
            delta=f"gets {gets:.1f} · gives {gives:.1f}",
            delta_color="off",
            delta_arrow="off",
        )
    st.altair_chart(
        trade_chart(rows, "rank_fpor_pg", "rank_repl", "FPoR per game (vs. positional rank)"),
        width="stretch",
    )


def render_weekly(
    trade: dict[str, list[str]],
    values: dict[str, PlayerValue],
    levels: dict[str, Any],
    weeks: tuple[int, int],
) -> None:
    with st.expander("Weekly points vs replacement"):
        records = []
        for side in SIDES:
            for pid in trade[side]:
                line = values[pid].line
                repl = levels[line.position].ppg
                row = {"Player": line.name, "Pos": line.position, "Repl": round(repl, 1)}
                for week in range(weeks[0], weeks[1] + 1):
                    pts = line.weekly.get(week)
                    row[f"W{week}"] = None if pts is None else round(pts - repl, 1)
                records.append(row)
        st.caption("Each cell is that week's points minus the position's replacement PPG. Blank = did not play.")
        st.dataframe(pd.DataFrame(records), hide_index=True, width="stretch")


def render_replacement_details(
    levels: dict[str, Any],
    positions: tuple[str, ...],
    names: dict[int, str],
) -> None:
    with st.expander("Who sets the replacement level?"):
        tabs = st.tabs(list(positions))
        for tab, pos in zip(tabs, positions):
            with tab:
                pool = levels[pos].pool
                if not pool:
                    st.caption("No eligible pool players — replacement is 0.")
                    continue
                st.dataframe(
                    pd.DataFrame(
                        [
                            {
                                "img": headshot_url(line.player_id, line.position),
                                "Player": line.name,
                                "NFL": line.team or "FA",
                                "Status": STATUS_LABELS[line.status],
                                "Rostered by": names.get(line.roster_id, "—"),
                                "G": line.games,
                                "PPG": round(line.ppg, 1),
                            }
                            for line in pool
                        ]
                    ),
                    hide_index=True,
                    width="stretch",
                    column_config={"img": st.column_config.ImageColumn("", width="small")},
                )
                st.caption(f"Average: **{levels[pos].ppg:.1f} PPG**")


main()
