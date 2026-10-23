"""Autocomplete player search with headshot thumbnails (Streamlit v2 component).

Filtering happens client-side on every keystroke; Python only hears about it
when a player is picked, via the ``selected`` trigger.
"""

from __future__ import annotations

from typing import Any, Callable

import streamlit as st

_HTML = """
<div class="ps">
  <input class="ps-input" type="text" autocomplete="off" spellcheck="false" />
  <ul class="ps-list" role="listbox" hidden></ul>
</div>
"""

_CSS = """
.ps { font-family: var(--st-font, "Source Sans Pro", sans-serif); color: var(--st-text-color, inherit); }
.ps-input {
  width: 100%; box-sizing: border-box; padding: 0.55rem 0.75rem; font: inherit; font-size: 0.95rem;
  color: inherit; background: var(--st-secondary-background-color, #f0f2f6);
  border: 1px solid transparent; border-radius: var(--st-base-radius, 0.5rem); outline: none;
}
.ps-input:focus { border-color: var(--st-primary-color, #ff4b4b); }
.ps-list {
  list-style: none; margin: 0.25rem 0 0; padding: 0.25rem; max-height: 22rem; overflow-y: auto;
  border: 1px solid var(--st-border-color, rgba(49, 51, 63, 0.2));
  border-radius: var(--st-base-radius, 0.5rem); background: var(--st-background-color, #fff);
}
.ps-item {
  display: flex; align-items: center; gap: 0.65rem; padding: 0.35rem 0.5rem;
  border-radius: calc(var(--st-base-radius, 0.5rem) - 2px); cursor: pointer;
}
.ps-item.active { background: var(--st-secondary-background-color, #f0f2f6); }
.ps-img {
  width: 40px; height: 40px; flex: none; border-radius: 50%; object-fit: cover;
  background: var(--st-secondary-background-color, #f0f2f6);
}
.ps-initials {
  display: flex; align-items: center; justify-content: center; font-size: 0.8rem; font-weight: 600;
  opacity: 0.7;
}
.ps-main { flex: 1; min-width: 0; }
.ps-name { font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ps-name mark { background: none; color: var(--st-primary-color, #ff4b4b); }
.ps-sub, .ps-meta { font-size: 0.8rem; opacity: 0.7; white-space: nowrap; }
.ps-meta { text-align: right; font-variant-numeric: tabular-nums; }
.ps-empty { padding: 0.5rem; font-size: 0.85rem; opacity: 0.7; }
"""

_JS = """
const MAX_RESULTS = 8;

function norm(text) {
  return (text || "").toLowerCase().normalize("NFD").replace(/[\\u0300-\\u036f]/g, "")
    .replace(/[.'`]/g, "").replace(/[^a-z0-9]+/g, " ").trim();
}

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (c) => (
    {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
}

// Every query token must prefix a word of the name, or equal the position/team.
// Lower score = better: full-name prefix, then first-name prefix, then input order (PPG rank).
function rank(option, tokens, query) {
  const words = option._words;
  let score = 0;
  for (const token of tokens) {
    if (token === option._pos || token === option._team) continue;
    const idx = words.findIndex((w) => w.startsWith(token));
    if (idx < 0) return null;
    score += idx;
  }
  if (option._name.startsWith(query)) score -= 10;
  return score;
}

function highlight(name, tokens) {
  const parts = name.split(/(\\s+|-)/);
  return parts.map((part) => {
    const n = norm(part);
    const hit = tokens.find((t) => t && n.startsWith(t));
    if (!hit) return escapeHtml(part);
    // Highlight the matched prefix, approximating over punctuation-stripped text.
    const cut = Math.min(part.length, hit.length + (part.length - n.length));
    return "<mark>" + escapeHtml(part.slice(0, cut)) + "</mark>" + escapeHtml(part.slice(cut));
  }).join("");
}

function initials(name) {
  return name.split(/\\s+/).filter(Boolean).slice(0, 2).map((w) => w[0]).join("").toUpperCase();
}

export default function (component) {
  const { data, parentElement, setTriggerValue } = component;
  const input = parentElement.querySelector(".ps-input");
  const list = parentElement.querySelector(".ps-list");
  const exclude = new Set(data.exclude || []);

  const options = (data.options || []).filter((o) => !exclude.has(o.id)).map((o) => ({
    ...o,
    _name: norm(o.name),
    _words: norm(o.name).split(" "),
    _pos: norm(o.pos),
    _team: norm(o.team),
  }));
  input.placeholder = data.placeholder || "Search players";

  let results = [];
  let active = 0;

  function close() {
    list.hidden = true;
    list.innerHTML = "";
    results = [];
  }

  function pick(option) {
    if (!option) return;
    input.value = "";
    close();
    setTriggerValue("selected", option.id);
  }

  function render() {
    const query = norm(input.value);
    if (!query) return close();
    const tokens = query.split(" ");
    results = options
      .map((o, i) => ({ o, s: rank(o, tokens, query), i }))
      .filter((r) => r.s !== null)
      .sort((a, b) => a.s - b.s || a.i - b.i)
      .slice(0, MAX_RESULTS)
      .map((r) => r.o);
    active = Math.min(active, Math.max(results.length - 1, 0));
    list.hidden = false;
    if (!results.length) {
      list.innerHTML = '<li class="ps-empty">No matching players</li>';
      return;
    }
    list.innerHTML = results.map((o, i) => `
      <li class="ps-item${i === active ? " active" : ""}" role="option" data-i="${i}">
        <img class="ps-img" src="${escapeHtml(o.img)}" alt="" loading="lazy" data-initials="${escapeHtml(initials(o.name))}" />
        <div class="ps-main">
          <div class="ps-name">${highlight(o.name, tokens)}</div>
          <div class="ps-sub">${escapeHtml(o.sub || "")}</div>
        </div>
        <div class="ps-meta">${escapeHtml(o.meta || "")}</div>
      </li>`).join("");
    list.querySelectorAll("img.ps-img").forEach((img) => {
      img.onerror = () => {
        const div = document.createElement("div");
        div.className = "ps-img ps-initials";
        div.textContent = img.dataset.initials;
        img.replaceWith(div);
      };
    });
  }

  function setActive(i) {
    active = i;
    list.querySelectorAll(".ps-item").forEach((el, j) => {
      el.classList.toggle("active", j === active);
      if (j === active) el.scrollIntoView({ block: "nearest" });
    });
  }

  input.oninput = () => { active = 0; render(); };
  input.onfocus = () => render();
  input.onkeydown = (e) => {
    if (e.key === "ArrowDown" && results.length) {
      e.preventDefault(); setActive((active + 1) % results.length);
    } else if (e.key === "ArrowUp" && results.length) {
      e.preventDefault(); setActive((active - 1 + results.length) % results.length);
    } else if (e.key === "Enter") {
      e.preventDefault(); pick(results[active]);
    } else if (e.key === "Escape") {
      input.value = ""; close();
    }
  };
  // mousedown (not click) fires before the input's blur closes the list.
  list.onmousedown = (e) => {
    const item = e.target.closest(".ps-item");
    if (!item) return;
    e.preventDefault();
    pick(results[Number(item.dataset.i)]);
  };
  input.onblur = () => setTimeout(close, 100);

  // Re-render with fresh data (e.g. an exclusion changed) if the user is mid-search.
  if (document.activeElement === input || parentElement.activeElement === input) render();
}
"""

_component = st.components.v2.component("player_search", html=_HTML, css=_CSS, js=_JS)


def player_search(
    options: list[dict[str, Any]],
    *,
    key: str,
    exclude: list[str] | None = None,
    placeholder: str = "Search players",
    on_select: Callable[[], None] | None = None,
) -> str | None:
    """Render the search box; returns the picked player_id on the run it was picked.

    ``options`` items: ``{id, name, pos, team, img, sub, meta}``. Order is the
    tie-break for equally good matches, so pass them best-first.
    """
    result = _component(
        key=key,
        data={"options": options, "exclude": exclude or [], "placeholder": placeholder},
        on_selected_change=on_select or (lambda: None),
    )
    return result.selected
