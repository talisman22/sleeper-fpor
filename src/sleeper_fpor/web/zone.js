/*
 * Draft-zone FPoR: value each player against the players drafted around him.
 *
 * A player taken at pick p is measured against the average points per game of the
 * nearest picks in his position group -- what that draft slot typically bought this
 * season. Groups follow lineup eligibility: QBs only face QBs, while RB/WR/TE share
 * the flex group. Only games played count, so missed weeks (injury, bye) never drag
 * a player down. Undrafted players on a roster today are measured against the end of
 * the draft: a pickup costs about what a final-round pick does.
 *
 * Pure functions over the data.json bundle -- no DOM -- so the page and the tests
 * (tests/test_zone_js.py) run the same code.
 */
(function (root) {
  "use strict";

  const POSITION_GROUPS = { QB: "QB", RB: "FLEX", WR: "FLEX", TE: "FLEX", K: "K", DEF: "DEF" };
  const OWN_PICK = "own_pick";
  const ACQUIRED = "acquired"; // drafted by another team, now here (trade or waivers)
  const PICKUP = "pickup"; // never drafted
  const ORIGINS = { own_pick: "Own picks", acquired: "Acquired (trade/waivers)", pickup: "Undrafted pickups" };

  const groupOf = (pos) => POSITION_GROUPS[pos] || pos;

  /** Games played and points over weeks 1..through (null = did not play). */
  function seasonLine(player, through) {
    let games = 0;
    let points = 0;
    const weekly = (player && player.weekly) || [];
    for (let w = 0; w < Math.min(through, weekly.length); w++) {
      const pts = weekly[w];
      if (pts !== null && pts !== undefined) {
        games += 1;
        points += pts;
      }
    }
    return { games, points };
  }

  /** Points per game *played*; null until a player has minGames games. */
  function gamesPpg(line, minGames) {
    if (!line || line.games < Math.max(minGames, 1)) return null;
    return line.points / line.games;
  }

  /**
   * Average PPG of the `neighbors` picks nearest pickNo in the same position group.
   * candidates: [{pick, value}]. Picks without a PPG yet are skipped, and the player
   * being valued (exclude) never sets his own bar. Ties go to the earlier pick.
   */
  function zoneBaseline(pickNo, position, candidates, neighbors, exclude) {
    const group = groupOf(position);
    const pool = candidates.filter(
      (c) => c.value !== null && c.pick.player_id !== exclude && groupOf(c.pick.pos) === group
    );
    pool.sort(
      (a, b) => Math.abs(a.pick.pick_no - pickNo) - Math.abs(b.pick.pick_no - pickNo) || a.pick.pick_no - b.pick.pick_no
    );
    const chosen = pool.slice(0, neighbors);
    if (!chosen.length) return { value: null, neighbors: [] };
    const mean = chosen.reduce((sum, c) => sum + c.value, 0) / chosen.length;
    return { value: mean, neighbors: chosen.map((c) => c.pick.player_id) };
  }

  function headshot(id, pos) {
    return pos === "DEF"
      ? `https://sleepercdn.com/images/team_logos/nfl/${String(id).toLowerCase()}.png`
      : `https://sleepercdn.com/content/nfl/players/thumb/${id}.jpg`;
  }

  /**
   * Recent form: weighted PPG over the player's last `lastN` games *played* through week
   * `through`. Missed weeks are skipped, so the window reaches back past an injury instead
   * of counting it as zero. With a half-life H, a game's weight halves every H games back
   * (most recent = 1); halfLife 0 or null weights the window equally. Null until the player
   * has `minGames` games played in total.
   */
  function formPpg(player, { through, lastN, halfLife, minGames }) {
    const played = [];
    const weekly = (player && player.weekly) || [];
    for (let w = 0; w < Math.min(through, weekly.length); w++) {
      if (weekly[w] !== null && weekly[w] !== undefined) played.push(weekly[w]);
    }
    if (played.length < Math.max(minGames, 1)) return null;
    const window = played.slice(-Math.max(lastN, 1)).reverse(); // most recent first
    let num = 0;
    let den = 0;
    window.forEach((pts, age) => {
      const weight = halfLife > 0 ? Math.pow(0.5, age / halfLife) : 1;
      num += weight * pts;
      den += weight;
    });
    return num / den;
  }

  /**
   * Every drafted player, plus every undrafted player rostered today, valued with
   * `ppgOf(id)` -- season PPG by default, or any other per-player PPG (e.g. recent form).
   * The same function values the zone neighbors, so comparisons stay like-for-like.
   */
  function draftValues(bundle, { neighbors, minGames, through, ppgOf }) {
    const picks = [...bundle.picks].sort((a, b) => a.pick_no - b.pick_no);
    const players = bundle.players;
    const teams = bundle.league.teams;
    const lastPick = picks.length ? picks[picks.length - 1].pick_no : 0;
    const lines = {};
    for (const id of Object.keys(players)) lines[id] = seasonLine(players[id], through);
    const ppg = ppgOf || ((id) => gamesPpg(lines[id], minGames));
    const candidates = picks.map((pick) => ({ pick, value: ppg(pick.player_id) }));

    function build(id, pick) {
      const player = players[id] || {};
      const line = lines[id] || { games: 0, points: 0 };
      const owner = player.owner ?? null;
      const draftedBy = pick ? pick.roster_id : null;
      let origin = null;
      if (owner !== null) origin = !pick ? PICKUP : draftedBy === owner ? OWN_PICK : ACQUIRED;
      const pos = player.pos || (pick && pick.pos) || "UNK";
      const anchor = pick ? pick.pick_no : lastPick + 1;
      const base = zoneBaseline(anchor, pos, candidates, neighbors, id);
      const value = ppg(id);
      return {
        id,
        name: player.name || (pick && pick.name) || id,
        pos,
        nfl: player.nfl || "FA",
        img: headshot(id, pos),
        pick: pick ? pick.pick_no : null,
        round: pick ? pick.round : null,
        pick_in_round: pick ? ((pick.pick_no - 1) % teams) + 1 : null,
        drafted_by_id: draftedBy,
        owner_id: owner,
        origin,
        games: line.games,
        points: line.points,
        value,
        baseline: base.value,
        zone_size: base.neighbors.length,
        fpor: value === null || base.value === null ? null : value - base.value,
      };
    }

    const drafted = new Set(picks.map((p) => p.player_id));
    const results = picks.map((pick) => build(pick.player_id, pick));
    for (const id of Object.keys(players)) {
      if (!drafted.has(id) && players[id].owner !== null && players[id].owner !== undefined) {
        results.push(build(id, null));
      }
    }
    return results;
  }

  /** Sum of FPoR/G per team: everyone it drafted, and today's roster split by origin. */
  function teamSummaries(values, rosterIds) {
    const out = new Map(
      rosterIds.map((rid) => [rid, { draft_class: 0, roster: { own_pick: 0, acquired: 0, pickup: 0 } }])
    );
    for (const v of values) {
      if (v.fpor === null) continue;
      if (out.has(v.drafted_by_id)) out.get(v.drafted_by_id).draft_class += v.fpor;
      if (out.has(v.owner_id) && v.origin) out.get(v.owner_id).roster[v.origin] += v.fpor;
    }
    return out;
  }

  /** Expectation curve per position group: the zone average at each of its picks. */
  function curves(bundle, values, neighbors) {
    const valueById = new Map(values.map((v) => [v.id, v.value]));
    const candidates = bundle.picks.map((pick) => ({ pick, value: valueById.get(pick.player_id) ?? null }));
    const result = {};
    for (const group of new Set(Object.values(POSITION_GROUPS))) result[group] = [];
    for (const pick of [...bundle.picks].sort((a, b) => a.pick_no - b.pick_no)) {
      const group = groupOf(pick.pos);
      if (!result[group]) continue;
      const base = zoneBaseline(pick.pick_no, pick.pos, candidates, neighbors, null);
      if (base.value !== null) result[group].push([pick.pick_no, base.value]);
    }
    return result;
  }

  /** Everything the page renders, for one setting of the controls. */
  function compute(bundle, { neighbors = 6, minGames = 3, through, recentGames = 4, halfLife = 3 } = {}) {
    const completed = bundle.league.completed_weeks;
    const thru = Math.max(1, Math.min(through || completed, Math.max(completed, 1)));
    const mg = Math.max(1, Math.min(minGames, thru));
    const lastN = Math.max(1, Math.min(recentGames, thru));
    const values = draftValues(bundle, { neighbors, minGames: mg, through: thru });
    const recentOf = (id) =>
      formPpg(bundle.players[id], { through: thru, lastN, halfLife, minGames: mg });
    const recent = new Map(
      draftValues(bundle, { neighbors, minGames: mg, through: thru, ppgOf: recentOf }).map((v) => [v.id, v])
    );
    const names = new Map(bundle.teams.map((t) => [t.roster_id, t.name]));
    const summaries = teamSummaries(values, bundle.teams.map((t) => t.roster_id));
    return {
      league: { ...bundle.league, through: thru },
      settings: { neighbors, min_games: mg, recent_games: lastN, half_life: halfLife },
      groups: POSITION_GROUPS,
      origins: ORIGINS,
      teams: bundle.teams.map((t) => {
        const s = summaries.get(t.roster_id);
        const total = s.roster.own_pick + s.roster.acquired + s.roster.pickup;
        return { ...t, draft_class: s.draft_class, roster: s.roster, roster_total: total };
      }),
      players: values.map((v) => {
        const r = recent.get(v.id);
        return {
          ...v,
          drafted_by: v.drafted_by_id === null ? null : names.get(v.drafted_by_id) ?? null,
          owner: v.owner_id === null ? null : names.get(v.owner_id) ?? null,
          recent_value: r.value,
          recent_baseline: r.baseline,
          recent_fpor: r.fpor,
          recent_window: Math.min(v.games, lastN), // games actually in the recent window
        };
      }),
      curves: curves(bundle, values, neighbors),
    };
  }

  root.Zone = {
    POSITION_GROUPS, groupOf, seasonLine, gamesPpg, formPpg, zoneBaseline, draftValues, teamSummaries, curves, compute,
  };
})(typeof globalThis !== "undefined" ? globalThis : this);
