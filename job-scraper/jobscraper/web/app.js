"use strict";

const SOURCE_NAMES = {
  remoteok: "RemoteOK", remotive: "Remotive", arbeitnow: "Arbeitnow", hackernews: "Hacker News",
  greenhouse: "Greenhouse", lever: "Lever", ashby: "Ashby", demo: "Demo",
};
const BOARDS = {
  remoteok: "Remote jobs, mostly tech",
  remotive: "Remote jobs in all fields",
  arbeitnow: "Jobs in Europe, mostly Germany",
  hackernews: "Monthly “Who is hiring?” thread",
};
const ATS_NAMES = { greenhouse: "Greenhouse", lever: "Lever", ashby: "Ashby" };
const TABS = [
  ["all", "All"], ["new", "New"], ["saved", "Saved"], ["applied", "Applied"], ["hidden", "Hidden"],
];
const PAGE = 100;
const ICONS = {
  star: '<svg viewBox="0 0 24 24"><path d="M12 3l2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.3 6.5 20.2l1-6.2L3 9.6l6.2-.9z"/></svg>',
  check: '<svg viewBox="0 0 24 24"><path d="M20 6L9 17l-5-5"/></svg>',
  hide: '<svg viewBox="0 0 24 24"><path d="M3 3l18 18M10.6 10.6a2 2 0 0 0 2.8 2.8M9.9 5.1A10 10 0 0 1 12 5c6 0 9.5 7 9.5 7a17 17 0 0 1-3.2 4M6.1 6.1A17 17 0 0 0 2.5 12S6 19 12 19a9.6 9.6 0 0 0 4-.9"/></svg>',
  ext: '<svg viewBox="0 0 24 24"><path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/></svg>',
  back: '<svg viewBox="0 0 24 24"><path d="M15 18l-6-6 6-6"/></svg>',
};

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const safeUrl = (u) => (/^https?:\/\//i.test(u || "") ? u : "#");

const store = {
  get(k, d) { try { const v = localStorage.getItem("jobradar:" + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("jobradar:" + k, JSON.stringify(v)); } catch { /* private mode */ } },
};

const DEFAULT_FILTERS = { q: "", loc: "", exclude: "", remote: false, days: "", hiddenSources: [], tab: "all", sort: "newest" };
const state = {
  data: null,
  filters: { ...DEFAULT_FILTERS, ...store.get("filters", {}) },
  selected: null,
  shown: PAGE,
  draftConfig: null,
};

// ---------------------------------------------------------------- API

async function api(path, body, method = "POST") {
  const opts = body === undefined ? {} : { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

async function load() {
  state.data = await api("/api/state");
  render();
  if (!state.data.fetched_at) refresh();
}

async function refresh() {
  const btn = $("refreshBtn");
  if (btn.disabled) return;
  btn.disabled = true;
  btn.classList.add("spinning");
  btn.querySelector("span").textContent = "Refreshing…";
  $("status").textContent = "Checking all sites for new jobs. This can take up to a minute…";
  if (!state.data?.jobs?.length) showEmpty("Looking for jobs…", "Checking every site you follow. This can take up to a minute.");
  try {
    state.data = await api("/api/refresh", {});
  } catch (e) {
    showBanner(`<b>Refresh failed:</b> ${esc(e.message)}`, true);
  } finally {
    btn.disabled = false;
    btn.classList.remove("spinning");
    btn.querySelector("span").textContent = "Refresh";
    render();
  }
}

async function setStatus(job, status) {
  const next = job.status === status ? null : status;
  job.status = next;
  render();
  try {
    await api("/api/status", { key: job.key, status: next });
  } catch (e) {
    showBanner(`Couldn't save that change: ${esc(e.message)}`, true);
  }
}

// ---------------------------------------------------------------- filtering

function ageDays(job) {
  return job.posted_at ? (Date.now() - Date.parse(job.posted_at)) / 864e5 : null;
}

function matches(job, f, { ignoreSource = false } = {}) {
  if (!ignoreSource && f.hiddenSources.includes(job.source)) return false;
  if (f.remote && !job.remote) return false;
  if (f.days) {
    const age = ageDays(job);
    if (age != null && age > Number(f.days)) return false;
  }
  if (f.loc.trim()) {
    const locs = f.loc.toLowerCase().split(",").map((s) => s.trim()).filter(Boolean);
    const where = (job.location || "").toLowerCase();
    if (!locs.some((l) => where.includes(l) || (l === "remote" && job.remote))) return false;
  }
  if (f.exclude.trim()) {
    const words = f.exclude.split(",").map((s) => s.trim()).filter(Boolean);
    if (words.some((w) => new RegExp(`\\b${w.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`, "i").test(job.title))) return false;
  }
  if (f.q.trim()) {
    const hay = job._hay || (job._hay = [job.title, job.company, job.location, (job.tags || []).join(" "), job.description].join(" ").toLowerCase());
    if (!f.q.toLowerCase().split(/\s+/).filter(Boolean).every((w) => hay.includes(w))) return false;
  }
  return true;
}

function inTab(job, tab) {
  if (tab === "hidden") return job.status === "hidden";
  if (job.status === "hidden") return false;
  if (tab === "new") return job.is_new;
  if (tab === "saved") return job.status === "saved";
  if (tab === "applied") return job.status === "applied";
  return true;
}

function sortJobs(list, how) {
  const by = {
    newest: (a, b) => (Date.parse(b.posted_at) || 0) - (Date.parse(a.posted_at) || 0),
    company: (a, b) => a.company.localeCompare(b.company) || a.title.localeCompare(b.title),
    title: (a, b) => a.title.localeCompare(b.title),
  }[how];
  return list.sort(by);
}

// ---------------------------------------------------------------- rendering

function relTime(iso) {
  if (!iso) return "date unknown";
  const mins = (Date.now() - Date.parse(iso)) / 6e4;
  if (mins < 60) return "just now";
  if (mins < 60 * 24) return `${Math.floor(mins / 60)}h ago`;
  const d = Math.floor(mins / 1440);
  if (d < 30) return `${d}d ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function renderStatus() {
  const d = state.data;
  if (!d || $("refreshBtn").disabled) return;
  const n = d.sources.length;
  $("status").textContent = d.fetched_at
    ? `Updated ${relTime(d.fetched_at)} · ${d.jobs.length.toLocaleString()} jobs from ${n} ${n === 1 ? "source" : "sources"}`
    : "Not refreshed yet";
}

function render() {
  const d = state.data;
  if (!d) return;
  const f = state.filters;
  store.set("filters", f);

  renderStatus();
  const nSites = d.sources.length;
  const errs = Object.entries(d.errors || {});
  if (d.demo) {
    showBanner("<b>Demo mode.</b> These are made-up sample jobs. Start the app without <code>--demo</code> to see real ones.");
  } else if (errs.length) {
    const summary = errs.length === nSites
      ? "None of the sites could be reached."
      : `${errs.length} of ${nSites} sources couldn't be loaded. The other results are still shown.`;
    showBanner(
      `<details><summary><b>${summary}</b> Details</summary><ul>` +
      errs.map(([k, v]) => `<li><b>${esc(sourceLabel(k))}</b>: ${esc(friendlyError(v))}</li>`).join("") + "</ul></details>",
      true,
    );
  } else {
    $("banner").hidden = true;
  }

  // everything matching the sidebar filters, before the tab is applied
  const base = d.jobs.filter((j) => matches(j, f));

  $("tabs").innerHTML = TABS.map(([id, label]) => {
    const n = base.filter((j) => inTab(j, id)).length;
    return `<button class="tab" role="tab" data-tab="${id}" aria-selected="${f.tab === id}">${label}<span class="n">${n.toLocaleString()}</span></button>`;
  }).join("");

  // source checkboxes with counts (counted with every other filter applied)
  const counts = {};
  for (const j of d.jobs) if (inTab(j, "all") && matches(j, f, { ignoreSource: true })) counts[j.source] = (counts[j.source] || 0) + 1;
  const allSources = [...new Set(d.jobs.map((j) => j.source))].sort();
  $("sourceList").innerHTML = allSources.length
    ? allSources.map((s) => `<label><input type="checkbox" data-source="${esc(s)}" ${f.hiddenSources.includes(s) ? "" : "checked"}>${esc(SOURCE_NAMES[s] || s)}<span class="n">${(counts[s] || 0).toLocaleString()}</span></label>`).join("")
    : `<small style="color:var(--muted)">Appear after the first refresh.</small>`;

  const list = sortJobs(base.filter((j) => inTab(j, f.tab)), f.sort);
  $("count").textContent = `${list.length.toLocaleString()} ${list.length === 1 ? "job" : "jobs"}`;
  $("list").innerHTML = list.slice(0, state.shown).map(jobCard).join("");
  $("moreBtn").hidden = list.length <= state.shown;
  $("moreBtn").textContent = `Show more (${(list.length - state.shown).toLocaleString()} left)`;

  if (!list.length) {
    if (!d.fetched_at) showEmpty("No jobs yet", "Press Refresh to look for jobs.", true);
    else if (!d.jobs.length && errs.length) showEmpty("Couldn't load any jobs", "Check your internet connection, then press Refresh.", true);
    else if (!d.jobs.length) showEmpty("No jobs found", "Add more job sites or companies in Settings, then refresh.");
    else if (f.tab !== "all" && !base.some((j) => inTab(j, f.tab))) showEmpty(...TAB_EMPTY[f.tab]);
    else showEmpty("No jobs match your filters", "Try fewer search words or a wider date range.", false, true);
  } else {
    $("empty").hidden = true;
  }

  renderDetail();
}

const TAB_EMPTY = {
  new: ["Nothing new since the last refresh", "Jobs that show up in a later refresh will be listed here."],
  saved: ["No saved jobs", "Press the star on a job to keep it here."],
  applied: ["Nothing marked as applied", "Press the check mark on a job once you've applied."],
  hidden: ["No hidden jobs", "Jobs you hide are moved here, out of the way."],
};

// "greenhouse:stripe" -> "Stripe (Greenhouse)", "remoteok" -> "RemoteOK"
function sourceLabel(label) {
  const [src, slug] = label.split(":");
  const name = SOURCE_NAMES[src] || src;
  return slug ? `${slug.replace(/[-_]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())} (${name})` : name;
}

function friendlyError(msg) {
  if (/404/.test(msg)) return "not found. Check the company name in Settings.";
  if (/403|Tunnel|Proxy/i.test(msg)) return "the site refused the connection (network blocked?)";
  if (/429/.test(msg)) return "too many requests. Try again later.";
  if (/timed? ?out/i.test(msg)) return "the site took too long to answer";
  if (/NameResolution|getaddrinfo|Max retries/i.test(msg)) return "couldn't connect (are you offline?)";
  return msg;
}

function showEmpty(title, text, withRefresh = false, withReset = false) {
  $("empty").hidden = false;
  $("empty").innerHTML = `<h3>${esc(title)}</h3><div>${esc(text)}</div>` +
    (withRefresh ? `<button class="btn primary" data-action="refresh">Refresh now</button>` : "") +
    (withReset ? `<button class="btn" data-action="reset">Clear filters</button>` : "");
}

function showBanner(html, warn = false) {
  const b = $("banner");
  b.innerHTML = html;
  b.classList.toggle("warn", warn);
  b.hidden = false;
}

function actionButtons(job, cls = "act", labels = false) {
  const btn = (status, icon, label) => {
    const on = job.status === status;
    const title = on ? { saved: "Unsave", applied: "Unmark applied", hidden: "Unhide" }[status] : label;
    return `<button class="${cls} ${status} ${on ? "on" : ""}" data-status="${status}" title="${title}" aria-label="${title}" aria-pressed="${on}">${icon}${labels ? `<span>${on ? title : label}</span>` : ""}</button>`;
  };
  return btn("saved", ICONS.star, "Save") + btn("applied", ICONS.check, "Mark applied") + btn("hidden", ICONS.hide, "Hide");
}

function jobCard(j) {
  const selected = state.selected === j.key;
  const loc = j.location || (j.remote ? "Remote" : "");
  const meta = [
    j.is_new ? `<span class="chip new">New</span>` : "",
    j.status === "applied" ? `<span class="chip status-applied">Applied</span>` : "",
    j.remote ? `<span class="chip remote">Remote</span>` : "",
    j.salary ? `<span class="chip">${esc(j.salary)}</span>` : "",
    `<span>${relTime(j.posted_at)}</span>`,
    `<span class="sep"></span><span>${esc(SOURCE_NAMES[j.source] || j.source)}</span>`,
  ].join("");
  return `<li class="job ${selected ? "selected" : ""} ${j.status === "applied" ? "dim" : ""}" data-key="${esc(j.key)}" tabindex="0">
    <div class="job-title">${esc(j.title)}</div>
    <div class="job-actions">${actionButtons(j)}</div>
    <div class="job-sub">${esc(j.company)}${loc ? ` · ${esc(loc)}` : ""}</div>
    <div class="job-meta">${meta}</div>
  </li>`;
}

function renderDetail() {
  const el = $("detail");
  const j = state.data.jobs.find((x) => x.key === state.selected);
  el.classList.toggle("open", !!j);
  if (!j) {
    el.innerHTML = `<div class="detail-placeholder">Select a job to see the details.</div>`;
    return;
  }
  const facts = [
    ["Location", j.location || (j.remote ? "Remote" : "Not listed")],
    ["Remote", j.remote ? "Yes" : "No / not stated"],
    ["Salary", j.salary || "Not listed"],
    ["Posted", j.posted_at ? `${new Date(j.posted_at).toLocaleDateString(undefined, { dateStyle: "medium" })} (${relTime(j.posted_at)})` : "Unknown"],
    ["Found on", SOURCE_NAMES[j.source] || j.source],
  ];
  el.innerHTML = `<div class="detail-inner">
    <button class="btn ghost small back" data-action="close">${ICONS.back}Back to list</button>
    <div>
      <h2>${esc(j.title)}</h2>
      <div class="company">${esc(j.company)}</div>
    </div>
    <div class="detail-actions">
      <a class="btn primary" href="${esc(safeUrl(j.url))}" target="_blank" rel="noopener noreferrer">${ICONS.ext}Open job posting</a>
      ${actionButtons(j, "btn", true)}
    </div>
    <dl class="facts">${facts.map(([k, v]) => `<dt>${k}</dt><dd>${esc(v)}</dd>`).join("")}</dl>
    ${j.tags?.length ? `<div class="tags">${j.tags.map((t) => `<span class="chip">${esc(t)}</span>`).join("")}</div>` : ""}
    ${j.description ? `<div class="desc">${esc(j.description)}${j.description.length >= 490 ? "…" : ""}</div><small style="color:var(--muted)">Preview only. Open the job posting for the full description.</small>` : ""}
  </div>`;
}

// ---------------------------------------------------------------- settings

function parseCompanyInput(raw) {
  const s = raw.trim();
  const patterns = [
    [/(?:job-)?boards(?:-api)?\.greenhouse\.io\/(?:v1\/boards\/)?([\w.-]+)/i, "greenhouse"],
    [/(?:jobs|api)\.lever\.co\/(?:v0\/postings\/)?([\w.-]+)/i, "lever"],
    [/jobs\.ashbyhq\.com\/([\w.-]+)/i, "ashby"],
  ];
  for (const [re, ats] of patterns) {
    const m = s.match(re);
    if (m) return { ats, slug: m[1] };
  }
  return { ats: null, slug: s };
}

function openSettings() {
  state.draftConfig = structuredClone(state.data.config);
  $("settingsError").hidden = true;
  $("slugInput").value = "";
  renderSettings();
  $("settings").showModal();
}

function renderSettings() {
  const cfg = state.draftConfig;
  $("boardList").innerHTML = Object.entries(BOARDS).map(([id, desc]) =>
    `<label class="board"><input type="checkbox" data-board="${id}" ${cfg.boards[id] ? "checked" : ""}>
      <span><b>${SOURCE_NAMES[id]}</b><small>${esc(desc)}</small></span></label>`).join("");
  const items = [];
  for (const [ats, list] of Object.entries(cfg.companies)) {
    list.forEach((e, i) => {
      const slug = typeof e === "string" ? e : e.slug;
      const name = typeof e === "string" ? "" : e.name;
      items.push(`<li>${esc(name || slug)} <small>${ATS_NAMES[ats]}</small><button type="button" data-remove="${ats}:${i}" aria-label="Remove ${esc(name || slug)}">✕</button></li>`);
    });
  }
  $("companyList").innerHTML = items.join("") || `<li class="none">No companies yet.</li>`;
}

function addCompany() {
  const { ats, slug } = parseCompanyInput($("slugInput").value);
  const err = $("settingsError");
  const target = ats || $("atsSelect").value;
  if (!/^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$/.test(slug)) {
    err.textContent = slug ? "That doesn't look like a company name from a careers link. Use only letters, digits, - _ or ." : "Type a company name or paste a careers link first.";
    err.hidden = false;
    return;
  }
  const list = state.draftConfig.companies[target];
  if (!list.some((e) => (typeof e === "string" ? e : e.slug).toLowerCase() === slug.toLowerCase())) list.push(slug);
  if (ats) $("atsSelect").value = ats;
  err.hidden = true;
  $("slugInput").value = "";
  renderSettings();
  $("slugInput").focus();
}

async function saveSettings() {
  try {
    const cfg = await api("/api/config", state.draftConfig, "PUT");
    state.data.config = cfg;
    $("settings").close();
    refresh();
  } catch (e) {
    $("settingsError").textContent = e.message;
    $("settingsError").hidden = false;
  }
}

// ---------------------------------------------------------------- events

function bindFilters() {
  const f = state.filters;
  for (const id of ["q", "loc", "exclude", "days", "sort"]) {
    $(id).value = f[id];
    $(id).addEventListener("input", () => { f[id] = $(id).value; state.shown = PAGE; render(); });
  }
  $("remote").checked = f.remote;
  $("remote").addEventListener("change", () => { f.remote = $("remote").checked; state.shown = PAGE; render(); });
}

function resetFilters() {
  Object.assign(state.filters, { ...DEFAULT_FILTERS, tab: state.filters.tab, sort: state.filters.sort });
  for (const id of ["q", "loc", "exclude", "days"]) $(id).value = "";
  $("remote").checked = false;
  render();
}

function selectJob(key) {
  state.selected = key;
  render();
}

function toggleSidebar(open) {
  $("sidebar").classList.toggle("open", open);
  $("filtersBtn").setAttribute("aria-expanded", String(open));
}

document.addEventListener("click", (e) => {
  const t = e.target;
  const statusBtn = t.closest("[data-status]");
  if (statusBtn) {
    const key = statusBtn.closest("[data-key]")?.dataset.key || state.selected;
    const job = state.data.jobs.find((j) => j.key === key);
    if (job) setStatus(job, statusBtn.dataset.status);
    return;
  }
  const tab = t.closest("[data-tab]");
  if (tab) { state.filters.tab = tab.dataset.tab; state.shown = PAGE; render(); return; }
  const src = t.closest("[data-source]");
  if (src) {
    const hs = new Set(state.filters.hiddenSources);
    src.checked ? hs.delete(src.dataset.source) : hs.add(src.dataset.source);
    state.filters.hiddenSources = [...hs];
    render();
    return;
  }
  const card = t.closest(".job[data-key]");
  if (card) { selectJob(card.dataset.key); return; }
  const action = t.closest("[data-action]")?.dataset.action;
  if (action === "refresh") refresh();
  if (action === "reset") resetFilters();
  if (action === "close") selectJob(null);
  const rm = t.closest("[data-remove]");
  if (rm) {
    const [ats, i] = rm.dataset.remove.split(":");
    state.draftConfig.companies[ats].splice(Number(i), 1);
    renderSettings();
  }
  const board = t.closest("[data-board]");
  if (board) state.draftConfig.boards[board.dataset.board] = board.checked;
  if ($("sidebar").classList.contains("open") && !t.closest("#sidebar") && !t.closest("#filtersBtn")) toggleSidebar(false);
});

document.addEventListener("keydown", (e) => {
  const typing = /INPUT|SELECT|TEXTAREA/.test(document.activeElement?.tagName);
  if (e.key === "/" && !typing) { e.preventDefault(); $("q").focus(); }
  if (e.key === "Escape" && state.selected && !$("settings").open) selectJob(null);
  if (e.key === "Enter" && document.activeElement?.matches(".job[data-key]")) selectJob(document.activeElement.dataset.key);
  if (e.key === "Enter" && document.activeElement === $("slugInput")) { e.preventDefault(); addCompany(); }
});

$("refreshBtn").addEventListener("click", refresh);
$("settingsBtn").addEventListener("click", openSettings);
$("filtersBtn").addEventListener("click", () => toggleSidebar(!$("sidebar").classList.contains("open")));
$("resetBtn").addEventListener("click", resetFilters);
$("moreBtn").addEventListener("click", () => { state.shown += PAGE; render(); });
$("addCompanyBtn").addEventListener("click", addCompany);
$("settingsForm").addEventListener("submit", (e) => {
  if (e.submitter?.value === "save") { e.preventDefault(); saveSettings(); }
});
// keep the "Updated … ago" text current
setInterval(renderStatus, 60_000);

bindFilters();
load().catch((e) => showEmpty("Couldn't reach the app", `${e.message}. Is it still running in your terminal?`));
