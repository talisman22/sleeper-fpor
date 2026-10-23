from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b\.?", re.I)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")

POS_MAP = {
    "QB": "QB",
    "RB": "RB",
    "FB": "RB",
    "WR": "WR",
    "TE": "TE",
    "K": "K",
    "PK": "K",
    "DEF": "DEF",
    "DST": "DEF",
}

NAME_ALIASES = {
    "hollywood brown": "marquise brown",
}


def normalize_name(name: str) -> str:
    text = name.lower().replace("'", "").replace(".", " ")
    text = _SUFFIX.sub("", text)
    text = _NON_ALNUM.sub(" ", text)
    return " ".join(text.split())


@dataclass(frozen=True)
class Player:
    player_id: str
    name: str
    position: str
    team: str | None


def canonical_position(raw: str | None) -> str | None:
    if not raw:
        return None
    return POS_MAP.get(raw.upper())


def load_players(raw: dict[str, Any]) -> dict[str, Player]:
    players: dict[str, Player] = {}
    for player_id, rec in raw.items():
        if not isinstance(rec, dict):
            continue
        pos = canonical_position(rec.get("position"))
        if pos is None:
            fantasy = rec.get("fantasy_positions") or []
            for item in fantasy:
                pos = canonical_position(item)
                if pos:
                    break
        if pos is None:
            continue
        first = rec.get("first_name") or ""
        last = rec.get("last_name") or ""
        full = rec.get("full_name") or f"{first} {last}".strip()
        if not full:
            continue
        team = rec.get("team") or rec.get("team_abbr")
        players[str(player_id)] = Player(
            player_id=str(player_id),
            name=full,
            position=pos,
            team=team,
        )
    return players


def build_lookup(players: dict[str, Player]) -> dict[tuple[str, str], str]:
    lookup: dict[tuple[str, str], str] = {}
    for player in players.values():
        key = (normalize_name(player.name), player.position)
        lookup.setdefault(key, player.player_id)
        if player.position == "DEF" and player.team:
            lookup.setdefault((normalize_name(player.team), "DEF"), player.player_id)
            lookup.setdefault((normalize_name(f"{player.team} defense"), "DEF"), player.player_id)
    return lookup


def match_adp_player(
    name: str,
    position: str,
    team: str | None,
    lookup: dict[tuple[str, str], str],
    players: dict[str, Player],
) -> str | None:
    pos = canonical_position(position)
    if not pos:
        return None
    name = NAME_ALIASES.get(normalize_name(name), name)
    if pos == "DEF":
        if team:
            team_id = f"TEAM_{team.upper()}"
            if team_id in players:
                return team_id
            hit = lookup.get((normalize_name(team), "DEF"))
            if hit:
                return hit
        for suffix in (" defense", " dst", " d st"):
            cleaned = name.lower().removesuffix(suffix)
            hit = lookup.get((normalize_name(cleaned), "DEF"))
            if hit:
                return hit
    hit = lookup.get((normalize_name(name), pos))
    if hit:
        return hit
    # Last-name + team fallback for common collisions.
    last = normalize_name(name).split()[-1] if name else ""
    if last and team:
        for player in players.values():
            if player.position != pos:
                continue
            if player.team != team:
                continue
            if normalize_name(player.name).endswith(last):
                return player.player_id
    return None
