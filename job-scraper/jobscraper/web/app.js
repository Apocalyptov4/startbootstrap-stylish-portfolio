"use strict";

const SOURCE_NAMES = {
  remoteok: "RemoteOK", remotive: "Remotive", arbeitnow: "Arbeitnow", hackernews: "Hacker News",
  greenhouse: "Greenhouse", lever: "Lever", ashby: "Ashby", adzuna: "Adzuna", demo: "Demo",
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
// The website build (jobscraper/site.py) sets this: jobs come from data.json and
// saved/applied/hidden marks live in this browser instead of on a server.
const STATIC = !!window.JOB_RADAR_STATIC;
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

const DEFAULT_FILTERS = {
  q: "", loc: "", radius: "25", category: "", withRemote: true, exclude: "", remote: false, days: "", hiddenSources: [], tab: "all", sort: "newest",
};
const SAVED_FILTERS = store.get("filters", null);
const state = {
  data: null,
  filters: { ...DEFAULT_FILTERS, ...(SAVED_FILTERS || {}) },
  searching: false,
  selected: null,
  shown: PAGE,
  draftConfig: null,
  near: { status: "empty", place: null },
};

// ---------------------------------------------------------------- places (ZIP code / city lookup)
// Mirrors jobscraper/geo.py. The data (places.json, ~700 KB) is only downloaded once someone uses "Near".

const US_STATES = {
  alabama: "AL", alaska: "AK", arizona: "AZ", arkansas: "AR", california: "CA", colorado: "CO", connecticut: "CT",
  delaware: "DE", "district of columbia": "DC", florida: "FL", georgia: "GA", hawaii: "HI", idaho: "ID", illinois: "IL",
  indiana: "IN", iowa: "IA", kansas: "KS", kentucky: "KY", louisiana: "LA", maine: "ME", maryland: "MD",
  massachusetts: "MA", michigan: "MI", minnesota: "MN", mississippi: "MS", missouri: "MO", montana: "MT",
  nebraska: "NE", nevada: "NV", "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM", "new york": "NY",
  "north carolina": "NC", "north dakota": "ND", ohio: "OH", oklahoma: "OK", oregon: "OR", pennsylvania: "PA",
  "rhode island": "RI", "south carolina": "SC", "south dakota": "SD", tennessee: "TN", texas: "TX", utah: "UT",
  vermont: "VT", virginia: "VA", washington: "WA", "west virginia": "WV", wisconsin: "WI", wyoming: "WY", "puerto rico": "PR",
};
const STATE_ABBREVS = new Set(Object.values(US_STATES));
const CITY_ALIASES = {
  nyc: "new york|NY", "new york city": "new york|NY", manhattan: "new york|NY", sf: "san francisco|CA",
  la: "los angeles|CA", dc: "washington|DC", "washington dc": "washington|DC", "washington d.c.": "washington|DC",
  philly: "philadelphia|PA", "bay area": "san francisco|CA", "sf bay area": "san francisco|CA",
};
const BIG_CITY_MIN_ZIPS = 15;
const places = { data: null, status: "idle", biggest: null, cache: new Map() };

function loadPlaces() {
  if (places.status !== "idle") return;
  places.status = "loading";
  fetch(STATIC ? "places.json" : "/places.json")
    .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
    .then((d) => {
      places.data = d;
      places.biggest = {};
      for (const [key, v] of Object.entries(d.cities)) {
        const name = key.split("|")[0];
        const cur = places.biggest[name];
        if (!cur || v[2] > d.cities[cur][2]) places.biggest[name] = key;
      }
      places.status = "ready";
      render();
    })
    .catch(() => { places.status = "failed"; render(); });
}

const titleCase = (s) => s.replace(/\b\w/g, (c) => c.toUpperCase());

function cityKeyPlace(key) {
  const [city, st] = key.split("|");
  const v = places.data.cities[key];
  return v ? { lat: v[0], lon: v[1], label: `${titleCase(city)}, ${st}` } : null;
}

function stateCode(text) {
  const t = text.trim().replace(/\.$/, "");
  return STATE_ABBREVS.has(t.toUpperCase()) ? t.toUpperCase() : US_STATES[t.toLowerCase()] || null;
}

function cityPlace(name, st) {
  name = name.trim().toLowerCase().replace(/\s+/g, " ");
  if (!st && CITY_ALIASES[name]) return cityKeyPlace(CITY_ALIASES[name]);
  name = name.replace(/^(greater|downtown|metro)\s+/, "").replace(/^(st\.?|ste\.?)\s+/, "saint ")
    .replace(/\s+(area|metro area|metropolitan area)$/, "");
  if (st) return cityKeyPlace(`${name}|${st}`);
  if (CITY_ALIASES[name]) return cityKeyPlace(CITY_ALIASES[name]);
  const best = places.biggest[name];
  return best && places.data.cities[best][2] >= BIG_CITY_MIN_ZIPS ? cityKeyPlace(best) : null;
}

/** "60614", "Austin, TX", "austin texas", "Chicago" -> {lat, lon, label} or null. Needs places loaded. */
function lookupPlace(text) {
  const t = (text || "").trim();
  if (!t) return null;
  if (places.cache.has(t)) return places.cache.get(t);
  let hit = null;
  const zip = t.match(/^(\d{5})(?:-\d{4})?$/);
  if (zip) {
    const z = places.data.zips[zip[1]];
    hit = z ? { lat: z[0], lon: z[1], label: z[2] ? `${zip[1]} (${z[2]})` : zip[1] } : null;
  } else if (t.includes(",")) {
    const [city, rest] = [t.slice(0, t.indexOf(",")), t.slice(t.indexOf(",") + 1)];
    const st = stateCode(rest.split(",")[0]);
    hit = st ? cityPlace(city, st) : null;
  } else {
    const words = t.split(/\s+/);
    for (const n of [2, 1]) {
      const st = words.length > n ? stateCode(words.slice(-n).join(" ")) : null;
      if (st && (hit = cityPlace(words.slice(0, -n).join(" "), st))) break;
    }
    hit = hit || cityPlace(t, null);
  }
  places.cache.set(t, hit);
  return hit;
}

function milesBetween(a, b) {
  const rad = Math.PI / 180;
  const dLat = (b.lat - a.lat) * rad;
  const dLon = (b.lon - a.lon) * rad;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLon / 2) ** 2;
  return 2 * 3958.8 * Math.asin(Math.sqrt(h));
}

/** What the "Near" box currently means: empty, loading, found (with a place) or unknown (match text). */
function resolveNear(text) {
  if (!text.trim()) return { status: "empty", place: null };
  if (places.status !== "ready") {
    loadPlaces();
    return { status: places.status === "failed" ? "unknown" : "loading", place: null };
  }
  const place = lookupPlace(text);
  return place ? { status: "found", place } : { status: "unknown", place: null };
}

function areaCovers(place) {
  return (state.data?.config?.areas || []).some((a) => {
    const p = places.status === "ready" ? lookupPlace(a.where) : null;
    return p && milesBetween(p, place) <= a.miles;
  });
}

// ---------------------------------------------------------------- API

async function api(path, body, method = "POST") {
  const opts = body === undefined ? {} : { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

/** Start from the first search area ("within 50 mi of 08088"): on a first visit, and again whenever it changes. */
function applyHomeArea() {
  const home = state.data?.config?.areas?.[0];
  if (!home) return;
  const homeKey = `${home.where}|${home.miles}|${home.category || ""}`;
  if (SAVED_FILTERS && store.get("homeArea", null) === homeKey) return;
  store.set("homeArea", homeKey);
  const f = state.filters;
  f.loc = home.where;
  const options = [...$("radius").options].map((o) => Number(o.value));
  f.radius = String(options.find((m) => m >= home.miles) ?? options[options.length - 1]);
  f.category = home.category || "";
  $("loc").value = f.loc;
  $("radius").value = f.radius;
}

async function load() {
  if (STATIC) {
    state.data = await loadStatic();
    applyHomeArea();
    render();
    return;
  }
  state.data = await api("/api/state");
  applyHomeArea();
  render();
  if (!state.data.fetched_at) refresh();
}

async function loadStatic() {
  const res = await fetch("data.json", { cache: "no-cache" });
  if (!res.ok) throw new Error(`Couldn't load the job list (${res.status})`);
  const d = await res.json();
  // "New" = not in the list this browser saw last time the data changed.
  const keys = d.jobs.map((j) => j.key);
  const seen = store.get("seen", null);
  let newKeys = [];
  if (seen && seen.fetched_at === d.fetched_at) newKeys = seen.newKeys;
  else if (seen) { const old = new Set(seen.keys); newKeys = keys.filter((k) => !old.has(k)); }
  store.set("seen", { fetched_at: d.fetched_at, keys, newKeys });
  const isNew = new Set(newKeys);
  const marks = store.get("marks", {});
  for (const j of d.jobs) { j.is_new = isNew.has(j.key); j.status = marks[j.key] || null; }
  return d;
}

async function refresh() {
  const btn = $("refreshBtn");
  if (btn.disabled) return;
  btn.disabled = true;
  btn.classList.add("spinning");
  btn.querySelector("span").textContent = "Refreshing…";
  $("status").textContent = STATIC ? "Loading the latest list…" : "Checking all sites for new jobs. This can take up to a minute…";
  if (!state.data?.jobs?.length) showEmpty("Looking for jobs…", "Checking every site you follow. This can take up to a minute.");
  try {
    state.data = STATIC ? await loadStatic() : await api("/api/refresh", {});
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
  if (STATIC) {
    const marks = store.get("marks", {});
    if (next) marks[job.key] = next; else delete marks[job.key];
    store.set("marks", marks);
    return;
  }
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

function matches(job, f, { ignoreSource = false, ignoreCategory = false } = {}) {
  if (!ignoreSource && f.hiddenSources.includes(job.source)) return false;
  if (!ignoreCategory && f.category && job.category !== f.category) return false;
  if (f.remote && !job.remote) return false;
  if (f.days) {
    const age = ageDays(job);
    if (age != null && age > Number(f.days)) return false;
  }
  const near = state.near;
  if (near.status === "found") {
    if (job.lat != null) {
      job._dist = milesBetween(near.place, job);
      if (job._dist > Number(f.radius)) return false;
    } else {
      job._dist = null;
      if (!(f.withRemote && job.remote)) return false;
    }
  } else if (f.loc.trim()) {
    // Not a known US place (yet): match the location text, e.g. "Berlin" or "London, Remote".
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
    nearest: (a, b) => (a._dist ?? 1e9) - (b._dist ?? 1e9) || (Date.parse(b.posted_at) || 0) - (Date.parse(a.posted_at) || 0),
    company: (a, b) => a.company.localeCompare(b.company) || a.title.localeCompare(b.title),
    title: (a, b) => a.title.localeCompare(b.title),
  }[how === "nearest" && state.near.status !== "found" ? "newest" : how];
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

function categoryName(tag) {
  return state.data?.categories?.[tag] || titleCase(tag.replace(/-jobs$/, "").replace(/-/g, " "));
}

function renderCategories() {
  const f = state.filters;
  const counts = {};
  for (const j of state.data.jobs) {
    if (j.category && inTab(j, "all") && matches(j, f, { ignoreCategory: true })) counts[j.category] = (counts[j.category] || 0) + 1;
  }
  // The app can search Adzuna for a kind of job not loaded yet; the website can only filter what it has.
  const tags = new Set([...Object.keys(counts), ...(STATIC ? [] : Object.keys(state.data.categories || {})), f.category].filter(Boolean));
  const opts = [...tags].sort((a, b) => (counts[b] || 0) - (counts[a] || 0) || categoryName(a).localeCompare(categoryName(b)));
  $("category").innerHTML = `<option value="">All kinds of jobs</option>` +
    opts.map((t) => `<option value="${esc(t)}">${esc(categoryName(t))}${counts[t] ? ` (${counts[t].toLocaleString()})` : ""}</option>`).join("");
  $("category").value = f.category;
}

function renderNear() {
  const f = state.filters;
  const { status, place } = state.near;
  const hint = $("nearHint");
  hint.className = status === "found" ? "ok" : status === "unknown" ? "warn" : "";
  hint.textContent = {
    empty: "e.g. 60614 or Austin, TX",
    loading: "Looking up that place…",
    found: place ? `Within ${f.radius} mi of ${place.label}` : "",
    unknown: "Not a US ZIP code or city I know, so matching the location text instead.",
  }[status];
  if (status === "found" && STATIC && !areaCovers(place)) {
    const home = state.data.config.areas?.[0];
    const note = document.createElement("span");
    note.className = "note";
    note.textContent = home
      ? `This website collects jobs within ${home.miles} mi of ${home.where}, so there may be few jobs here. The Job Radar program can search any ZIP code.`
      : "The Job Radar program can search any ZIP code.";
    hint.append(note);
  }
  const btn = $("searchBtn");
  btn.hidden = STATIC || status !== "found";
  if (!btn.hidden) {
    btn.disabled = state.searching;
    const kind = f.category ? categoryName(f.category).toLowerCase() + " jobs" : "all jobs";
    btn.textContent = state.searching ? "Searching…" : `Search ${kind} within ${f.radius} mi of ${place.label}`;
  }
}

function renderStatus() {
  const d = state.data;
  if (!d || $("refreshBtn").disabled) return;
  const n = d.sources.length;
  $("status").textContent = d.fetched_at
    ? `Updated ${relTime(d.fetched_at)} · ${d.jobs.length.toLocaleString()} jobs from ${n} ${n === 1 ? "source" : "sources"}${STATIC ? " · updates automatically" : ""}`
    : "Not refreshed yet";
}

function render() {
  const d = state.data;
  if (!d) return;
  const f = state.filters;
  store.set("filters", f);

  renderStatus();
  state.near = resolveNear(f.loc);
  renderNear();
  const nSites = d.sources.length;
  const errs = Object.entries(d.errors || {});
  if (d.demo) {
    showBanner(STATIC
      ? "<b>Demo mode.</b> These are made-up sample jobs."
      : "<b>Demo mode.</b> These are made-up sample jobs. Start the app without <code>--demo</code> to see real ones.");
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

  renderCategories();

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
  if (label.startsWith("adzuna:")) return `Adzuna near ${label.slice(7)}`;
  const [src, slug] = label.split(":");
  const name = SOURCE_NAMES[src] || src;
  return slug ? `${slug.replace(/[-_]/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())} (${name})` : name;
}

function friendlyError(msg) {
  if (/Adzuna/.test(msg)) return msg.replace(/^AdzunaError:\s*/, "");
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
  const dist = state.near.status === "found" && j._dist != null ? j._dist : null;
  const meta = [
    dist != null ? `<span class="chip dist">${dist < 1 ? "under 1 mi" : `${Math.round(dist)} mi`}</span>` : "",
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
    ["Kind of job", j.category ? categoryName(j.category) : "Not known"],
    ["Found on", SOURCE_NAMES[j.source] || j.source],
  ];
  if (state.near.status === "found" && j._dist != null) facts.splice(1, 0, ["Distance", `about ${Math.max(1, Math.round(j._dist))} mi from ${state.near.place.label}`]);
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

function openSettings(message) {
  state.draftConfig = structuredClone(state.data.config);
  state.draftConfig.areas = state.draftConfig.areas || [];
  if (STATIC) {
    // The website can't change its own settings; they live in sources.json in the repository.
    const repo = state.data.repo;
    $("editOnGithub").href = repo ? `https://github.com/${repo}/edit/master/job-scraper/sources.json` : "#";
    $("editOnGithub").hidden = !repo;
    document.querySelector(".modal-foot [value=cancel]").textContent = "Close";
  }
  $("settingsError").textContent = message || "";
  $("settingsError").hidden = !message;
  for (const id of ["slugInput", "areaWhere", "areaWhat", "adzunaId", "adzunaKey"]) $(id).value = "";
  const hasKeys = state.data.config.adzuna?.has_keys;
  $("adzunaStatus").innerHTML = hasKeys
    ? `<span class="key-status-ok">✓ Adzuna codes saved.</span> Type new ones below only if you want to replace them.`
    : `Search areas need free Adzuna codes. Sign up at <a href="https://developer.adzuna.com/signup" target="_blank" rel="noopener">developer.adzuna.com</a>,
       then copy the <b>App ID</b> and <b>App Key</b> from your Adzuna dashboard into these boxes.`;
  renderSettings();
  $("settings").showModal();
}

function renderSettings() {
  const cfg = state.draftConfig;
  $("boardList").innerHTML = Object.entries(BOARDS).map(([id, desc]) =>
    `<label class="board"><input type="checkbox" data-board="${id}" ${cfg.boards[id] ? "checked" : ""} ${STATIC ? "disabled" : ""}>
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
  $("areaCategory").innerHTML = `<option value="">All kinds of jobs</option>` + Object.keys(state.data.categories || {})
    .sort((a, b) => categoryName(a).localeCompare(categoryName(b)))
    .map((t) => `<option value="${esc(t)}">${esc(categoryName(t))}</option>`).join("");
  $("areaList").innerHTML = cfg.areas.map((a, i) => {
    const text = `${a.where} · ${a.miles} mi${a.category ? ` · ${categoryName(a.category)}` : ""}${a.what ? ` · “${a.what}”` : ""}`;
    return `<li>${esc(text)}<button type="button" data-remove-area="${i}" aria-label="Remove ${esc(text)}">✕</button></li>`;
  }).join("") || `<li class="none">No search areas yet. Add your ZIP code to see local jobs.</li>`;
}

function addArea() {
  const where = $("areaWhere").value.trim().replace(/\s+/g, " ");
  const what = $("areaWhat").value.trim().replace(/\s+/g, " ");
  const err = $("settingsError");
  if (!/^[A-Za-z0-9][A-Za-z0-9 .,'-]{0,79}$/.test(where)) {
    err.textContent = where ? "That doesn't look like a ZIP code or city." : "Type a ZIP code or city first.";
    err.hidden = false;
    return;
  }
  const areas = state.draftConfig.areas;
  const category = $("areaCategory").value;
  if (!areas.some((a) => a.where.toLowerCase() === where.toLowerCase() && a.what.toLowerCase() === what.toLowerCase() && (a.category || "") === category)) {
    areas.push({ where, miles: Number($("areaMiles").value), what, category });
  }
  err.hidden = true;
  $("areaWhere").value = "";
  $("areaWhat").value = "";
  renderSettings();
  $("areaWhere").focus();
}

/** Search Adzuna right now for the ZIP/city, distance and kind of job in the sidebar (app only). */
async function searchHere() {
  const f = state.filters;
  if (STATIC || state.searching || state.near.status !== "found") return;
  if (!state.data.config.adzuna?.has_keys) {
    openSettings("Searching needs your free Adzuna codes. Paste them below and press “Save & refresh”, then search again.");
    return;
  }
  state.searching = true;
  renderNear();
  $("status").textContent = `Searching near ${state.near.place.label}…`;
  try {
    state.data = await api("/api/search", { where: f.loc.trim(), miles: Number(f.radius), category: f.category, what: "" });
  } catch (e) {
    showBanner(`<b>Search failed:</b> ${esc(e.message)}`, true);
  } finally {
    state.searching = false;
    render();
  }
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
    const body = {
      ...state.draftConfig,
      // blank = keep the codes already saved (the page is never sent them)
      adzuna: { app_id: $("adzunaId").value.trim(), app_key: $("adzunaKey").value.trim(), max_pages: state.draftConfig.adzuna?.max_pages },
    };
    const cfg = await api("/api/config", body, "PUT");
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
  $("radius").value = f.radius;
  $("radius").addEventListener("change", () => { f.radius = $("radius").value; state.shown = PAGE; render(); });
  $("category").addEventListener("change", () => { f.category = $("category").value; state.shown = PAGE; render(); });
  $("withRemote").checked = f.withRemote;
  $("withRemote").addEventListener("change", () => { f.withRemote = $("withRemote").checked; state.shown = PAGE; render(); });
}

function resetFilters() {
  Object.assign(state.filters, { ...DEFAULT_FILTERS, tab: state.filters.tab, sort: state.filters.sort });
  for (const id of ["q", "loc", "exclude", "days"]) $(id).value = "";
  $("remote").checked = false;
  $("radius").value = DEFAULT_FILTERS.radius;
  $("category").value = "";
  $("withRemote").checked = DEFAULT_FILTERS.withRemote;
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
  const rmArea = t.closest("[data-remove-area]");
  if (rmArea) {
    state.draftConfig.areas.splice(Number(rmArea.dataset.removeArea), 1);
    renderSettings();
    return;
  }
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
  if (e.key === "Enter" && document.activeElement === $("loc") && !STATIC) { e.preventDefault(); searchHere(); }
  if (e.key === "Enter" && ["areaWhere", "areaWhat"].includes(document.activeElement?.id)) { e.preventDefault(); addArea(); }
  if (e.key === "Enter" && ["adzunaId", "adzunaKey"].includes(document.activeElement?.id)) e.preventDefault();
});

$("refreshBtn").addEventListener("click", refresh);
$("settingsBtn").addEventListener("click", () => openSettings());
$("filtersBtn").addEventListener("click", () => toggleSidebar(!$("sidebar").classList.contains("open")));
$("resetBtn").addEventListener("click", resetFilters);
$("moreBtn").addEventListener("click", () => { state.shown += PAGE; render(); });
$("addCompanyBtn").addEventListener("click", addCompany);
$("addAreaBtn").addEventListener("click", addArea);
$("searchBtn").addEventListener("click", searchHere);
$("settingsForm").addEventListener("submit", (e) => {
  if (e.submitter?.value === "save") { e.preventDefault(); saveSettings(); }
});
// keep the "Updated … ago" text current
setInterval(renderStatus, 60_000);

if (STATIC) document.body.classList.add("static");
bindFilters();
load().catch((e) => STATIC
  ? showEmpty("Couldn't load the job list", `${e.message}. Try reloading the page.`)
  : showEmpty("Couldn't reach the app", `${e.message}. Is it still running in your terminal?`));
