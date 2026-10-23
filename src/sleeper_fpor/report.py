from __future__ import annotations

import json
import math
from pathlib import Path

from sleeper_fpor.config import DATA_DIR


def write_reports(result: dict) -> tuple[Path, Path]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    json_path = DATA_DIR / "report.json"
    html_path = DATA_DIR / "report.html"
    json_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    html_path.write_text(_html(result), encoding="utf-8")
    return json_path, html_path


def write_mc_report(result: dict) -> tuple[Path, Path]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    json_path = DATA_DIR / "mc_report.json"
    html_path = DATA_DIR / "mc_report.html"
    json_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    html_path.write_text(_mc_html(result), encoding="utf-8")
    return json_path, html_path


# ---------------------------------------------------------------------------
# Shared bar chart (slot value by draft slot) -- inline SVG, no dependencies.
# ---------------------------------------------------------------------------

_CHART_CSS = """
    .viz-root {
      color-scheme: light;
      --chart-surface:  #fcfcfb;
      --text-primary:   #0b0b0b;
      --text-secondary: #52514e;
      --text-muted:     #898781;
      --gridline:       #e1e0d9;
      --axis-line:      #c3c2b7;
      --bar-fill:       #2a78d6;
      --bar-best:       #1c5cab;
      --bar-worst:      #898781;
      --tooltip-bg:     #0b0b0b;
      --tooltip-text:   #fcfcfb;
      --card-border:    rgba(11,11,11,0.10);
    }
    @media (prefers-color-scheme: dark) {
      .viz-root {
        color-scheme: dark;
        --chart-surface:  #1a1a19;
        --text-primary:   #ffffff;
        --text-secondary: #c3c2b7;
        --text-muted:     #898781;
        --gridline:       #2c2c2a;
        --axis-line:      #383835;
        --bar-fill:       #3987e5;
        --bar-best:       #86b6ef;
        --bar-worst:      #6b6a63;
        --tooltip-bg:     #fcfcfb;
        --tooltip-text:   #0b0b0b;
        --card-border:    rgba(255,255,255,0.10);
      }
    }
    .chart-card {
      font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
      background: var(--chart-surface);
      border: 1px solid var(--card-border);
      border-radius: 10px;
      padding: 1rem 1.25rem 0.75rem;
      margin: 1rem 0 2rem;
    }
    .chart-head { margin-bottom: 0.25rem; }
    .chart-title { color: var(--text-primary); font-size: 1rem; font-weight: 600; }
    .chart-subtitle { color: var(--text-secondary); font-size: 0.85rem; margin-top: 0.15rem; }
    .chart-svg { width: 100%; height: auto; display: block; }
    .gridline { stroke: var(--gridline); stroke-width: 1; }
    .axis-line { stroke: var(--axis-line); stroke-width: 1; }
    .whisker { stroke: var(--text-muted); stroke-width: 2; }
    .tick-label { fill: var(--text-muted); font-size: 11px; }
    .bar { fill: var(--bar-fill); }
    .bar-best { fill: var(--bar-best); }
    .bar-worst { fill: var(--bar-worst); }
    .bar-group { cursor: pointer; }
    .bar-group:focus { outline: 2px solid var(--bar-fill); outline-offset: 2px; }
    .direct-label { fill: var(--text-secondary); font-size: 11px; font-weight: 600; }
    .direct-label-best { fill: var(--bar-best); }
    .direct-label-worst { fill: var(--bar-worst); }
    .chart-legend {
      display: flex; gap: 1.25rem; align-items: center; flex-wrap: wrap;
      color: var(--text-secondary); font-size: 0.8rem; padding: 0.5rem 0 0.75rem;
    }
    .legend-swatch {
      display: inline-block; width: 10px; height: 10px; border-radius: 2px;
      background: var(--bar-fill); margin-right: 0.35rem;
    }
    .legend-best, .legend-worst { white-space: nowrap; }
    .legend-best::before, .legend-worst::before {
      content: "\\25CF"; margin-right: 0.3rem;
    }
    .legend-best::before { color: var(--bar-best); }
    .legend-worst::before { color: var(--bar-worst); }
    .chart-tooltip {
      position: fixed; display: none; pointer-events: none; z-index: 10;
      background: var(--tooltip-bg); color: var(--tooltip-text);
      font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
      font-size: 0.78rem; padding: 0.35rem 0.55rem; border-radius: 6px;
      white-space: nowrap;
    }
"""

_CHART_SCRIPT = """
    document.querySelectorAll('.chart-svg').forEach(function (svg) {
      var tip = document.getElementById(svg.id + '-tip');
      if (!tip) return;
      svg.querySelectorAll('.bar-group').forEach(function (g) {
        var show = function (e) {
          tip.textContent = g.getAttribute('data-tip');
          tip.style.display = 'block';
          var x = (e && e.clientX) || g.getBoundingClientRect().right;
          var y = (e && e.clientY) || g.getBoundingClientRect().top;
          tip.style.left = (x + 12) + 'px';
          tip.style.top = (y + 12) + 'px';
        };
        g.addEventListener('mouseenter', show);
        g.addEventListener('mousemove', show);
        g.addEventListener('focus', show);
        g.addEventListener('mouseleave', function () { tip.style.display = 'none'; });
        g.addEventListener('blur', function () { tip.style.display = 'none'; });
      });
    });
"""


def _nice_step(max_value: float, target_ticks: int = 4) -> float:
    if max_value <= 0:
        return 1.0
    raw_step = max_value / target_ticks
    magnitude = 10 ** math.floor(math.log10(raw_step))
    for mult in (1, 2, 2.5, 5, 10):
        step = mult * magnitude
        if step >= raw_step:
            return step
    return 10 * magnitude


def _slot_bar_chart(
    rows: list[dict],
    chart_id: str,
    title: str,
    subtitle: str,
    value_key: str,
    unit_label: str,
    low_key: str | None = None,
    high_key: str | None = None,
) -> str:
    rows = sorted(rows, key=lambda r: r["slot"])
    if not rows:
        return ""
    values = [row[value_key] for row in rows]
    max_val = max(values)
    if high_key:
        max_val = max(max_val, max(row[high_key] for row in rows))
    step = _nice_step(max_val)
    tick_count = math.ceil(max_val / step) + 1
    ticks = [round(i * step) for i in range(tick_count)]
    nice_max = ticks[-1] if ticks and ticks[-1] > 0 else 1

    width, height = 720, 340
    margin_top, margin_bottom, margin_left, margin_right = 34, 34, 54, 16
    plot_w = width - margin_left - margin_right
    plot_h = height - margin_top - margin_bottom
    n = len(rows)
    band_w = plot_w / n
    bar_w = min(24.0, band_w - 6)

    def y_of(v: float) -> float:
        return margin_top + plot_h - (v / nice_max) * plot_h

    best_idx = max(range(n), key=lambda i: values[i])
    worst_idx = min(range(n), key=lambda i: values[i])

    parts: list[str] = []
    for t in ticks:
        y = y_of(t)
        parts.append(
            f'<line x1="{margin_left}" y1="{y:.1f}" x2="{width - margin_right}" y2="{y:.1f}" class="gridline" />'
        )
        parts.append(
            f'<text x="{margin_left - 8}" y="{y:.1f}" class="tick-label" '
            f'text-anchor="end" dominant-baseline="middle">{t:,.0f}</text>'
        )

    for i, row in enumerate(rows):
        cx = margin_left + band_w * i + band_w / 2
        x = cx - bar_w / 2
        val = row[value_key]
        y = y_of(val)
        bar_h = margin_top + plot_h - y
        is_best = i == best_idx
        is_worst = i == worst_idx
        cls = "bar bar-best" if is_best else ("bar bar-worst" if is_worst else "bar")

        tip_bits = [f"Slot {row['slot']}", f"{unit_label}: {val:,.1f}"]
        if low_key and high_key:
            tip_bits.append(f"P10-P90: {row[low_key]:,.1f} to {row[high_key]:,.1f}")
        tip = " | ".join(tip_bits)

        if low_key and high_key:
            wy_low = y_of(row[low_key])
            wy_high = y_of(row[high_key])
            parts.append(
                f'<line x1="{cx:.1f}" y1="{wy_low:.1f}" x2="{cx:.1f}" y2="{wy_high:.1f}" class="whisker" />'
            )

        parts.append(
            f'<g class="bar-group" tabindex="0" data-tip="{tip}">'
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_w:.1f}" height="{max(bar_h, 0):.1f}" rx="4" class="{cls}" />'
            f"</g>"
        )
        if is_best or is_worst:
            tag = "best" if is_best else "worst"
            parts.append(
                f'<text x="{cx:.1f}" y="{y - 8:.1f}" text-anchor="middle" '
                f'class="direct-label direct-label-{tag}">{val:,.0f}</text>'
            )
        parts.append(
            f'<text x="{cx:.1f}" y="{height - margin_bottom + 18}" text-anchor="middle" '
            f'class="tick-label">{row["slot"]}</text>'
        )

    parts.append(
        f'<line x1="{margin_left}" y1="{margin_top + plot_h}" x2="{width - margin_right}" '
        f'y2="{margin_top + plot_h}" class="axis-line" />'
    )
    svg_body = "\n    ".join(parts)

    return f"""
  <div class="chart-card viz-root">
    <div class="chart-head">
      <div class="chart-title">{title}</div>
      <div class="chart-subtitle">{subtitle}</div>
    </div>
    <svg viewBox="0 0 {width} {height}" class="chart-svg" id="{chart_id}" role="img" aria-label="{title}">
    {svg_body}
    </svg>
    <div class="chart-legend">
      <span><span class="legend-swatch"></span>{unit_label} by slot</span>
      <span class="legend-best">best: slot {rows[best_idx]['slot']}</span>
      <span class="legend-worst">worst: slot {rows[worst_idx]['slot']}</span>
    </div>
  </div>
  <div class="chart-tooltip" id="{chart_id}-tip"></div>
"""


def _mc_html(result: dict) -> str:
    best_pick = result.get("best_overall_pick") or {}
    best_slot = result.get("best_snake_slot") or {}
    slot_rows = "\n".join(
        f"<tr><td>{row['slot']}</td><td>{row['mean']}</td><td>{row['std']}</td>"
        f"<td>{row['p10']}</td><td>{row['p50']}</td><td>{row['p90']}</td></tr>"
        for row in sorted(result.get("slots", []), key=lambda item: item["mean"], reverse=True)
    )
    pick_rows = "\n".join(
        f"<tr><td>{row['label']}</td><td>{row['overall']}</td><td>{row['mean']}</td>"
        f"<td>{row['std']}</td><td>{row['p10']}</td><td>{row['p50']}</td><td>{row['p90']}</td></tr>"
        for row in sorted(result.get("picks", []), key=lambda item: item["mean"], reverse=True)[:25]
    )
    notes = "".join(f"<li>{note}</li>" for note in result.get("notes", []))
    chart = _slot_bar_chart(
        result.get("slots", []),
        chart_id="mc-slot-chart",
        title="Average season value by draft slot (Monte Carlo)",
        subtitle=(
            f"Mean total FPoR across {result.get('total_draws_per_pick')} simulated drafts per slot "
            f"({result.get('iterations_per_season')} drafts/season x {len(result.get('seasons', []))} seasons). "
            "Whiskers span P10-P90."
        ),
        value_key="mean",
        unit_label="Mean total FPoR",
        low_key="p10",
        high_key="p90",
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>16-team PPR draft value -- Monte Carlo</title>
  <style>
    body {{ font-family: Georgia, serif; margin: 2rem; max-width: 900px; color: #1a1a1a; }}
    table {{ border-collapse: collapse; width: 100%; margin: 1rem 0 2rem; }}
    th, td {{ border-bottom: 1px solid #ddd; padding: 0.4rem 0.5rem; text-align: left; }}
    .hero {{ background: #f4f1ea; padding: 1rem 1.25rem; border-radius: 8px; }}
{_CHART_CSS}
  </style>
</head>
<body>
  <h1>16-team PPR draft value -- Monte Carlo simulation</h1>
  <p>{result.get('total_draws_per_pick')} simulated draws per pick/slot
  ({result.get('iterations_per_season')} drafts/season x {len(result.get('seasons', []))} seasons), seed {result.get('seed')}.</p>
  <div class="hero">
    <p><strong>Best snake slot:</strong> {best_slot.get('slot')} (mean {best_slot.get('mean')} total FPoR/season, std {best_slot.get('std')})</p>
    <p><strong>Best overall pick:</strong> {best_pick.get('label')} (mean {best_pick.get('mean')} FPoR, std {best_pick.get('std')})</p>
    <p><strong>Slot edge vs median:</strong> {result.get('slot_edge_over_median')}</p>
  </div>
  <ul>{notes}</ul>
  {chart}
  <h2>Snake slots (distribution of that seat's 12-pick season total)</h2>
  <table>
    <thead><tr><th>Slot</th><th>Mean</th><th>Std</th><th>P10</th><th>P50</th><th>P90</th></tr></thead>
    <tbody>{slot_rows}</tbody>
  </table>
  <h2>Top 25 overall picks (distribution)</h2>
  <table>
    <thead><tr><th>Pick</th><th>Overall</th><th>Mean</th><th>Std</th><th>P10</th><th>P50</th><th>P90</th></tr></thead>
    <tbody>{pick_rows}</tbody>
  </table>
  <script>
{_CHART_SCRIPT}
  </script>
</body>
</html>
"""


def _html(result: dict) -> str:
    league = result["league"]
    best_pick = result.get("best_overall_pick") or {}
    best_slot = result.get("best_snake_slot") or {}
    rows = "\n".join(
        f"<tr><td>{row['slot']}</td><td>{row['avg_total_fpor']}</td><td>{row['avg_per_pick']}</td></tr>"
        for row in result.get("slots", [])
    )
    pick_rows = "\n".join(
        f"<tr><td>{row['label']}</td><td>{row['overall']}</td><td>{row['avg_fpor']}</td></tr>"
        for row in sorted(result.get("picks", []), key=lambda item: item["avg_fpor"], reverse=True)[:25]
    )
    chart = _slot_bar_chart(
        result.get("slots", []),
        chart_id="slot-chart",
        title="Average season value by draft slot",
        subtitle=f"Avg total FPoR per slot across seasons {', '.join(str(s) for s in league['seasons'])} (sum of that seat's 12 picks).",
        value_key="avg_total_fpor",
        unit_label="Avg total FPoR",
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>16-team PPR pick value (FPoR)</title>
  <style>
    body {{ font-family: Georgia, serif; margin: 2rem; max-width: 900px; color: #1a1a1a; }}
    table {{ border-collapse: collapse; width: 100%; margin: 1rem 0 2rem; }}
    th, td {{ border-bottom: 1px solid #ddd; padding: 0.4rem 0.5rem; text-align: left; }}
    .hero {{ background: #f4f1ea; padding: 1rem 1.25rem; border-radius: 8px; }}
{_CHART_CSS}
  </style>
</head>
<body>
  <h1>16-team PPR draft value</h1>
  <p>{league['teams']} teams · {league['scoring']} · {league['starters']} · {league['bench']} bench · seasons {', '.join(str(s) for s in league['seasons'])}</p>
  <div class="hero">
    <p><strong>Best snake slot:</strong> {best_slot.get('slot')} ({best_slot.get('avg_total_fpor')} total FPoR / season)</p>
    <p><strong>Best overall pick:</strong> {best_pick.get('label')} ({best_pick.get('avg_fpor')} avg FPoR)</p>
    <p><strong>Slot edge vs median:</strong> {result.get('slot_edge_over_median')}</p>
  </div>
  {chart}
  <h2>Snake slots (sum of that seat's 12 picks)</h2>
  <table>
    <thead><tr><th>Slot</th><th>Avg total FPoR</th><th>Per pick</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  <h2>Top 25 overall picks</h2>
  <table>
    <thead><tr><th>Pick</th><th>Overall</th><th>Avg FPoR</th></tr></thead>
    <tbody>{pick_rows}</tbody>
  </table>
  <script>
{_CHART_SCRIPT}
  </script>
</body>
</html>
"""
