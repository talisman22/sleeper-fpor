"use strict";

const POSITIONS = ["QB", "RB", "WR", "TE", "K", "DEF"];
const POS_SYMBOL = { QB: "circle", RB: "square", WR: "diamond", TE: "triangle-up", K: "star", DEF: "hexagon" };
const ORIGINS = ["own_pick", "acquired", "pickup"];
const ORIGIN_VAR = { own_pick: "--origin-own", acquired: "--origin-acquired", pickup: "--origin-pickup" };
const PLOT_CONFIG = { displayModeBar: false, responsive: true };
const LABEL_EACH_END = 32; // name the top/bottom N in the scatter, not every point
const LABEL_PX_EACH = 33; // ...scaled down on narrow screens: one name per end per this many px of plot width

const form = document.getElementById("controls");
const statusEl = document.getElementById("status");
let bundle = null; // raw data.json: picks, teams, weekly points per player
let data = null; // Zone.compute(bundle, controls): what the page renders
let sort = { key: "fpor", dir: -1 };

// ---------------------------------------------------------------- helpers

const css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
const posColor = (pos) => css(`--pos-${pos.toLowerCase()}`) || css("--text-muted");
const fmt = (v, digits = 1) => (v === null || v === undefined ? "—" : v.toFixed(digits));
const signed = (v, digits = 1) => (v === null || v === undefined ? "—" : (v > 0 ? "+" : "") + v.toFixed(digits));
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const clean = (s) => (s || "").trim();
const GROUP_LABEL = { QB: "QB", FLEX: "Flex (RB/WR/TE)", K: "K", DEF: "DEF" };

function baseLayout(extra = {}) {
  const grid = css("--gridline");
  return {
    paper_bgcolor: css("--surface"),
    plot_bgcolor: css("--surface"),
    font: { family: getComputedStyle(document.body).fontFamily, color: css("--text-secondary"), size: 12 },
    margin: { l: 56, r: 16, t: 8, b: 48 },
    hoverlabel: { bgcolor: css("--tooltip-bg"), font: { color: css("--tooltip-text") }, bordercolor: css("--tooltip-bg") },
    xaxis: { gridcolor: grid, zerolinecolor: css("--axis-line"), linecolor: css("--axis-line") },
    yaxis: { gridcolor: grid, zerolinecolor: css("--axis-line"), linecolor: css("--axis-line") },
    legend: { orientation: "h", y: 1.02, yanchor: "bottom", x: 0, font: { color: css("--text-primary") } },
    ...extra,
  };
}

// Stable pseudo-random jitter so undrafted pickups don't stack on one x.
function jitter(id, spread) {
  let h = 0;
  for (const ch of id) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return ((h % 1000) / 1000 - 0.5) * spread;
}

function paddedRange(values, pad = 0.18) {
  const lo = Math.min(0, ...values);
  const hi = Math.max(0, ...values);
  const span = hi - lo || 1;
  return [lo - span * pad, hi + span * pad];
}

function undraftedX() {
  return data.league.last_pick + data.league.teams;
}

function pickTicks() {
  const { teams, rounds } = data.league;
  const vals = [];
  const text = [];
  for (let r = 1; r <= rounds; r++) {
    vals.push((r - 1) * teams + 1);
    text.push(`R${r}`);
  }
  vals.push(undraftedX());
  text.push("Undrafted");
  return { tickvals: vals, ticktext: text };
}

// ---------------------------------------------------------------- data

function controls() {
  const fd = new FormData(form);
  return {
    neighbors: Number(fd.get("neighbors")),
    minGames: Number(fd.get("min_games")),
    through: fd.get("through") ? Number(fd.get("through")) : undefined,
  };
}

// Fetch the data once (relative URL: works locally and under a GitHub Pages subpath);
// every control change after that recomputes in the browser.
async function load() {
  statusEl.textContent = "Loading…";
  statusEl.classList.remove("error");
  try {
    const res = await fetch("data.json", { cache: "no-cache" });
    const body = await res.json();
    if (!res.ok || body.error) throw new Error(body.error || res.statusText);
    bundle = body;
    recompute();
    statusEl.textContent = "";
  } catch (err) {
    statusEl.textContent = `Error: ${err.message}`;
    statusEl.classList.add("error");
  }
}

function recompute() {
  data = Zone.compute(bundle, controls());
  syncControls();
  render();
}

let frame = null;
function scheduleRecompute() {
  if (!bundle) return;
  cancelAnimationFrame(frame);
  frame = requestAnimationFrame(recompute);
}

function syncControls() {
  const { league, settings } = data;
  document.getElementById("title").textContent = `${clean(league.name)} — Draft Zone FPoR`;
  document.getElementById("subtitle").textContent =
    `${league.season} · ${league.teams} teams · ${league.rounds} rounds · weeks 1–${league.through}`;
  document.title = `${clean(league.name)} · Draft Zone FPoR`;
  if (bundle.generated_at) {
    const when = new Date(bundle.generated_at).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
    document.getElementById("updated").textContent = `Data updated ${when}.`;
  }

  const through = document.getElementById("through");
  if (through.options.length !== league.completed_weeks) {
    through.innerHTML = "";
    for (let w = 1; w <= Math.max(league.completed_weeks, 1); w++) through.add(new Option(`Week ${w}`, w));
  }
  through.value = String(league.through);

  const minGames = form.elements.min_games;
  minGames.max = String(league.through);
  minGames.value = String(settings.min_games);
  document.getElementById("min-games-out").textContent = settings.min_games;
  form.elements.neighbors.value = String(settings.neighbors);
  document.getElementById("neighbors-out").textContent = settings.neighbors;

  const teamSel = document.getElementById("f-team");
  if (teamSel.options.length === 1) {
    for (const t of [...data.teams].sort((a, b) => clean(a.name).localeCompare(clean(b.name)))) {
      teamSel.add(new Option(clean(t.name), t.name));
    }
    const posSel = document.getElementById("f-pos");
    for (const p of POSITIONS) posSel.add(new Option(p, p));
  }
}

// ---------------------------------------------------------------- render

function render() {
  renderTiles();
  renderScatter();
  renderCurve();
  renderTeams();
  renderTable();
}

function tile(label, value, who, img) {
  const pic = img ? `<img src="${esc(img)}" alt="" loading="lazy" onerror="this.style.visibility='hidden'" />` : "";
  return `<div class="tile">${pic}<div><div class="label">${esc(label)}</div>
    <div class="value">${esc(value)}</div><div class="who">${esc(who)}</div></div></div>`;
}

function renderTiles() {
  const drafted = data.players.filter((p) => p.pick !== null && p.fpor !== null);
  const best = drafted.reduce((a, b) => (b.fpor > a.fpor ? b : a), drafted[0]);
  const worst = drafted.reduce((a, b) => (b.fpor < a.fpor ? b : a), drafted[0]);
  const byClass = [...data.teams].sort((a, b) => b.draft_class - a.draft_class)[0];
  const byRoster = [...data.teams].sort((a, b) => b.roster_total - a.roster_total)[0];
  const avatar = (t) => (t.avatar ? `https://sleepercdn.com/avatars/thumbs/${t.avatar}` : null);
  const u = "/G";
  document.getElementById("tiles").innerHTML = [
    tile("Biggest steal", `${signed(best.fpor)}${u}`, `${best.name} · pick ${best.pick} · ${clean(best.drafted_by)}`, best.img),
    tile("Biggest bust", `${signed(worst.fpor)}${u}`, `${worst.name} · pick ${worst.pick} · ${clean(worst.drafted_by)}`, worst.img),
    tile("Best draft class", `${signed(byClass.draft_class)}${u}`, clean(byClass.name), avatar(byClass)),
    tile("Best current roster", `${signed(byRoster.roster_total)}${u}`, clean(byRoster.name), avatar(byRoster)),
  ].join("");
}

function hoverData(p) {
  return [
    p.name,
    `${p.pos} · ${p.nfl} · zone: ${GROUP_LABEL[data.groups[p.pos]] || p.pos}`,
    p.pick ? `Pick ${p.pick} (${p.round}.${String(p.pick_in_round).padStart(2, "0")})` : "Undrafted",
    clean(p.drafted_by) || "—",
    clean(p.owner) || "Not rostered",
    fmt(p.value),
    fmt(p.baseline),
    p.zone_size,
    signed(p.fpor),
    p.games,
  ];
}

const HOVER =
  "<b>%{customdata[0]}</b>  %{customdata[1]}<br>%{customdata[2]}<br>" +
  "Drafted by: %{customdata[3]}<br>Rostered by: %{customdata[4]}<br>" +
  "PPG: %{customdata[5]} over %{customdata[9]} G · zone avg %{customdata[6]} (n=%{customdata[7]})<br>" +
  "<b>FPoR/G: %{customdata[8]}</b><extra></extra>";

function renderScatter() {
  const pts = data.players.filter((p) => p.fpor !== null);
  const ux = undraftedX();
  const xOf = (p) => (p.pick ?? ux + jitter(p.id, data.league.teams * 0.8));
  const traces = POSITIONS.map((pos) => {
    const group = pts.filter((p) => p.pos === pos);
    return {
      type: "scatter",
      mode: "markers",
      name: pos,
      x: group.map(xOf),
      y: group.map((p) => p.fpor),
      customdata: group.map(hoverData),
      hovertemplate: HOVER,
      marker: {
        color: posColor(pos),
        symbol: POS_SYMBOL[pos],
        size: 9,
        line: { width: 1.5, color: css("--surface") },
      },
    };
  });

  const xRange = [-2, ux + data.league.teams];
  const ys = pts.map((p) => p.fpor);
  const ySpan = Math.max(...ys) - Math.min(...ys) || 1;
  const yRange = [Math.min(...ys) - ySpan * 0.08, Math.max(...ys) + ySpan * 0.08];
  const margin = { l: 56, r: 16, t: 40, b: 48 };

  const el = document.getElementById("scatter");
  const ranked = [...pts].sort((a, b) => b.fpor - a.fpor);
  const fit = Math.floor((el.clientWidth - margin.l - margin.r) / LABEL_PX_EACH);
  const n = Math.max(0, Math.min(LABEL_EACH_END, fit, Math.floor(ranked.length / 2)));
  const labeled = [...ranked.slice(0, n), ...ranked.slice(-n)];
  const annotations = placeLabels(labeled, pts, xOf, {
    xRange, yRange, margin, width: el.clientWidth, height: el.clientHeight,
  });

  document.getElementById("scatter-note").textContent =
    `Points per game played over the average of the nearest ${data.settings.neighbors} picks in the same ` +
    `position group. Names: top and bottom ${n}. Hover any point for its zone; shapes mark position.`;

  Plotly.react("scatter", traces, baseLayout({
    margin,
    xaxis: { ...baseLayout().xaxis, title: { text: "Draft pick" }, ...pickTicks(), range: xRange },
    yaxis: { ...baseLayout().yaxis, title: { text: "FPoR per game" }, zeroline: true, zerolinewidth: 2, range: yRange },
    annotations,
    hovermode: "closest",
  }), PLOT_CONFIG);
}

// Greedy label placement: each name tries a ring of offsets around its point (outward side
// first) and takes the first spot that overlaps no earlier label, any marker, or the plot edge.
// Extremes are placed first so the most notable names get the closest spots.
function placeLabels(players, allPoints, xOf, { xRange, yRange, margin, width, height }) {
  const plotW = width - margin.l - margin.r;
  const plotH = height - margin.t - margin.b;
  const px = (x) => ((x - xRange[0]) / (xRange[1] - xRange[0])) * plotW;
  const py = (y) => ((yRange[1] - y) / (yRange[1] - yRange[0])) * plotH;
  const CHAR_W = 5.6; // ~10.5px font
  const LINE_H = 13;
  const PAD = 2;

  const boxes = allPoints.map((p) => ({ x: px(xOf(p)) - 5, y: py(p.fpor) - 5, w: 10, h: 10 })); // every marker
  const overlaps = (a) => boxes.some((b) =>
    a.x < b.x + b.w + PAD && b.x < a.x + a.w + PAD && a.y < b.y + b.h + PAD && b.y < a.y + a.h + PAD);
  const inside = (a) => a.x >= 0 && a.y >= 0 && a.x + a.w <= plotW && a.y + a.h <= plotH;

  const order = [...players].sort((a, b) => Math.abs(b.fpor) - Math.abs(a.fpor));
  const ink = css("--text-primary");
  const leader = css("--text-muted");
  return order.map((p) => {
    const cx = px(xOf(p));
    const cy = py(p.fpor);
    const w = p.name.length * CHAR_W + 4;
    const out = p.fpor >= 0 ? -1 : 1; // pixel y grows downward: positives label upward
    const candidates = [];
    for (let ring = 1; ring <= 7; ring++) {
      for (const side of [out, -out]) {
        for (const dx of [0, -(w / 2 + 8), w / 2 + 8, -(w + 12), w + 12]) {
          candidates.push({ dx, dy: side * ring * LINE_H, ring });
        }
      }
    }
    let pick = candidates[0];
    for (const c of candidates) {
      const box = { x: cx + c.dx - w / 2, y: cy + c.dy - LINE_H / 2, w, h: LINE_H };
      if (inside(box) && !overlaps(box)) {
        pick = c;
        break;
      }
    }
    boxes.push({ x: cx + pick.dx - w / 2, y: cy + pick.dy - LINE_H / 2, w, h: LINE_H });
    const near = pick.ring === 1 && pick.dx === 0;
    return {
      x: xOf(p),
      y: p.fpor,
      text: p.name,
      showarrow: true,
      ax: pick.dx,
      ay: pick.dy,
      arrowhead: 0,
      arrowwidth: 1,
      arrowcolor: near ? "rgba(0,0,0,0)" : leader,
      standoff: 5,
      font: { size: 10.5, color: ink },
    };
  });
}

function renderCurve() {
  const drafted = data.players.filter((p) => p.pick !== null && p.value !== null);
  const traces = POSITIONS.map((pos) => {
    const group = drafted.filter((p) => p.pos === pos);
    return {
      type: "scatter",
      mode: "markers",
      name: pos,
      legendgroup: pos,
      x: group.map((p) => p.pick),
      y: group.map((p) => p.value),
      customdata: group.map(hoverData),
      hovertemplate: HOVER,
      marker: { color: posColor(pos), symbol: POS_SYMBOL[pos], size: 7, opacity: 0.55 },
    };
  });
  for (const [group, points] of Object.entries(data.curves)) {
    if (!points.length) continue;
    const flex = group === "FLEX";
    const label = GROUP_LABEL[group] || group;
    traces.push({
      type: "scatter",
      mode: "lines",
      name: `${label} zone avg`,
      x: points.map((pt) => pt[0]),
      y: points.map((pt) => pt[1]),
      // Flex spans three positions, so its line wears neutral ink; QB/K/DEF wear their position color.
      line: { color: flex ? css("--text-primary") : posColor(group), width: 2, shape: "spline", smoothing: 0.6,
              dash: flex ? "solid" : "dot" },
      hovertemplate: `Pick %{x}: ${label} zone avg %{y:.1f}<extra></extra>`,
    });
  }
  const ticks = pickTicks();
  Plotly.react("curve", traces, baseLayout({
    xaxis: { ...baseLayout().xaxis, title: { text: "Draft pick" },
      tickvals: ticks.tickvals.slice(0, -1), ticktext: ticks.ticktext.slice(0, -1) },
    yaxis: { ...baseLayout().yaxis, title: { text: "Points per game played" } },
    hovermode: "closest",
  }), PLOT_CONFIG);
}

function renderTeams() {
  const u = "/G";
  const byClass = [...data.teams].sort((a, b) => a.draft_class - b.draft_class);
  const label = (t) => `${clean(t.name)}${t.draft_slot ? ` (#${t.draft_slot})` : ""}`;
  Plotly.react("draft-class", [{
    type: "bar",
    orientation: "h",
    y: byClass.map(label),
    x: byClass.map((t) => t.draft_class),
    customdata: byClass.map((t) => t.name),
    marker: { color: css("--bar"), cornerradius: 4 },
    text: byClass.map((t) => signed(t.draft_class)),
    textposition: "outside",
    cliponaxis: false,
    textfont: { color: css("--text-primary") },
    hovertemplate: `%{y}<br>Draft class FPoR: %{x:+.1f}${u}<extra></extra>`,
  }], baseLayout({
    margin: { l: 200, r: 48, t: 8, b: 40 },
    bargap: 0.35,
    xaxis: { ...baseLayout().xaxis, title: { text: "FPoR per game (sum over players)" }, zeroline: true, zerolinewidth: 2,
      range: paddedRange(byClass.map((t) => t.draft_class)) },
    yaxis: { ...baseLayout().yaxis, automargin: true, gridcolor: "rgba(0,0,0,0)" },
    showlegend: false,
  }), PLOT_CONFIG);

  const byRoster = [...data.teams].sort((a, b) => a.roster_total - b.roster_total);
  const traces = ORIGINS.map((origin) => ({
    type: "bar",
    orientation: "h",
    name: data.origins[origin],
    y: byRoster.map((t) => clean(t.name)),
    x: byRoster.map((t) => t.roster[origin]),
    customdata: byRoster.map((t) => t.name),
    marker: { color: css(ORIGIN_VAR[origin]), line: { width: 2, color: css("--surface") } },
    hovertemplate: `%{y}<br>${data.origins[origin]}: %{x:+.1f}${u}<extra></extra>`,
  }));
  const stackEnd = (t) => ORIGINS.reduce((sum, o) => sum + Math.max(t.roster[o], 0), 0);
  traces.push({
    type: "scatter",
    mode: "markers",
    name: "Total",
    y: byRoster.map((t) => clean(t.name)),
    x: byRoster.map((t) => t.roster_total),
    customdata: byRoster.map((t) => t.name),
    marker: { symbol: "line-ns-open", size: 18, color: css("--text-primary"), line: { width: 3, color: css("--text-primary") } },
    hovertemplate: `%{y}<br>Roster total: %{x:+.1f}${u}<extra></extra>`,
  });
  traces.push({
    type: "scatter",
    mode: "text",
    showlegend: false,
    hoverinfo: "skip",
    y: byRoster.map((t) => clean(t.name)),
    x: byRoster.map((t) => Math.max(stackEnd(t), t.roster_total)),
    text: byRoster.map((t) => signed(t.roster_total)),
    textposition: "middle right",
    textfont: { color: css("--text-primary") },
    cliponaxis: false,
  });
  Plotly.react("roster", traces, baseLayout({
    barmode: "relative",
    bargap: 0.35,
    margin: { l: 200, r: 48, t: 8, b: 40 },
    xaxis: { ...baseLayout().xaxis, title: { text: "FPoR per game (sum over players)" }, zeroline: true, zerolinewidth: 2,
      range: paddedRange(byRoster.flatMap((t) => [
        stackEnd(t),
        ORIGINS.reduce((sum, o) => sum + Math.min(t.roster[o], 0), 0),
      ])) },
    yaxis: { ...baseLayout().yaxis, automargin: true, gridcolor: "rgba(0,0,0,0)" },
  }), PLOT_CONFIG);
}

// ---------------------------------------------------------------- table

function filteredPlayers() {
  const q = document.getElementById("f-search").value.trim().toLowerCase();
  const team = document.getElementById("f-team").value;
  const mode = document.getElementById("f-team-mode").value;
  const pos = document.getElementById("f-pos").value;
  const origin = document.getElementById("f-origin").value;
  return data.players.filter((p) =>
    (!q || p.name.toLowerCase().includes(q)) &&
    (!team || p[mode] === team) &&
    (!pos || p.pos === pos) &&
    (!origin || (origin === "none" ? p.origin === null : p.origin === origin)));
}

function compare(a, b) {
  const va = a[sort.key];
  const vb = b[sort.key];
  if (va === vb) return 0;
  if (va === null || va === undefined) return 1; // blanks last, either direction
  if (vb === null || vb === undefined) return -1;
  return (typeof va === "string" ? va.localeCompare(vb) : va - vb) * sort.dir;
}

function renderTable() {
  const rows = filteredPlayers().sort(compare);
  const tbody = document.querySelector("#players tbody");
  tbody.innerHTML = rows.map((p) => `
    <tr>
      <td class="num">${p.pick ? `${p.pick} <span class="muted">R${p.round}</span>` : '<span class="muted">—</span>'}</td>
      <td class="player"><img src="${esc(p.img)}" alt="" loading="lazy" onerror="this.style.visibility='hidden'" />${esc(p.name)}</td>
      <td><span class="pos-chip"><i style="background:${posColor(p.pos)}"></i>${esc(p.pos)} · ${esc(p.nfl)}</span></td>
      <td>${esc(clean(p.drafted_by)) || '<span class="muted">Undrafted</span>'}</td>
      <td>${esc(clean(p.owner)) || '<span class="muted">Not rostered</span>'}</td>
      <td class="num">${p.games}</td>
      <td class="num">${fmt(p.value)}</td>
      <td class="num">${fmt(p.baseline)}</td>
      <td class="num ${p.fpor > 0 ? "pos-val" : "neg-val"}">${signed(p.fpor)}</td>
    </tr>`).join("");
  document.querySelectorAll("#players th").forEach((th) => {
    th.setAttribute("aria-sort", th.dataset.key === sort.key ? (sort.dir > 0 ? "ascending" : "descending") : "none");
  });
  document.getElementById("table-count").textContent = `${rows.length} of ${data.players.length} players`;
}

// ---------------------------------------------------------------- events

form.addEventListener("input", (e) => {
  const out = { neighbors: "neighbors-out", min_games: "min-games-out" }[e.target.name];
  if (out) document.getElementById(out).textContent = e.target.value;
  scheduleRecompute();
});

for (const id of ["f-search", "f-team", "f-team-mode", "f-pos", "f-origin"]) {
  document.getElementById(id).addEventListener("input", () => data && renderTable());
}

document.querySelectorAll("#players th").forEach((th) => {
  th.addEventListener("click", () => {
    const key = th.dataset.key;
    sort = { key, dir: sort.key === key ? -sort.dir : (["name", "pos", "drafted_by", "owner"].includes(key) ? 1 : -1) };
    renderTable();
  });
});

function focusTeam(name, mode) {
  document.getElementById("f-team").value = name;
  document.getElementById("f-team-mode").value = mode;
  document.getElementById("f-origin").value = "";
  renderTable();
  document.getElementById("table-card").scrollIntoView({ behavior: "smooth", block: "start" });
}

function bindTeamClicks() {
  document.getElementById("draft-class").on("plotly_click", (ev) => focusTeam(ev.points[0].customdata, "drafted_by"));
  document.getElementById("roster").on("plotly_click", (ev) => focusTeam(ev.points[0].customdata, "owner"));
}

window.matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => data && render());

// Label placement depends on the chart's pixel size, so redo it when the window resizes.
let resizeTimer = null;
window.addEventListener("resize", () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => data && renderScatter(), 200);
});

load().then(() => {
  if (data) bindTeamClicks();
});
