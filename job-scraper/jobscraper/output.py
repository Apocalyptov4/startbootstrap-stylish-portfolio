"""Render results as a terminal table, CSV, JSON, Markdown or a standalone HTML page."""

from __future__ import annotations

import csv
import html
import io
import json
import shutil
from datetime import datetime, timezone

from .models import Job

FORMATS = ("table", "csv", "json", "md", "html")
CSV_FIELDS = ["posted_at", "title", "company", "location", "remote", "salary", "source", "url", "tags"]


def render(jobs: list[Job], fmt: str) -> str:
    return {"table": to_table, "csv": to_csv, "json": to_json, "md": to_markdown, "html": to_html}[fmt](jobs)


def _age(job: Job) -> str:
    if not job.posted_at:
        return "?"
    days = (datetime.now(timezone.utc) - job.posted_at).days
    return "today" if days <= 0 else f"{days}d"


def _clip(s: str, n: int) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def to_table(jobs: list[Job]) -> str:
    width = shutil.get_terminal_size((140, 20)).columns
    cols = [("AGE", 5), ("TITLE", 40), ("COMPANY", 20), ("LOCATION", 22), ("SOURCE", 10)]
    url_w = max(20, width - sum(w + 2 for _, w in cols))
    lines = ["  ".join(h.ljust(w) for h, w in cols) + "  URL"]
    for j in jobs:
        loc = j.location or ("Remote" if j.remote else "")
        vals = [_age(j), j.title, j.company, loc, j.source]
        lines.append("  ".join(_clip(v, w).ljust(w) for v, (_, w) in zip(vals, cols)) + "  " + _clip(j.url, url_w))
    return "\n".join(lines)


def to_csv(jobs: list[Job]) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_FIELDS, extrasaction="ignore")
    w.writeheader()
    for j in jobs:
        d = j.to_dict()
        d["tags"] = "; ".join(j.tags)
        w.writerow(d)
    return buf.getvalue()


def to_json(jobs: list[Job]) -> str:
    return json.dumps([j.to_dict() for j in jobs], indent=2, ensure_ascii=False)


def to_markdown(jobs: list[Job]) -> str:
    esc = lambda s: s.replace("|", "\\|")  # noqa: E731
    rows = ["| Posted | Title | Company | Location | Source |", "|---|---|---|---|---|"]
    for j in jobs:
        posted = j.posted_at.date().isoformat() if j.posted_at else ""
        loc = j.location or ("Remote" if j.remote else "")
        rows.append(f"| {posted} | [{esc(j.title)}]({j.url}) | {esc(j.company)} | {esc(loc)} | {j.source} |")
    return "\n".join(rows)


def to_html(jobs: list[Job]) -> str:
    e = html.escape
    rows = []
    for j in jobs:
        posted = j.posted_at.date().isoformat() if j.posted_at else ""
        loc = j.location or ("Remote" if j.remote else "")
        tags = " ".join(f"<span class=tag>{e(t)}</span>" for t in j.tags[:5])
        rows.append(
            f"<tr><td>{posted}</td><td><a href='{e(j.url)}' target=_blank rel=noopener>{e(j.title)}</a>"
            f"<div>{tags}</div></td><td>{e(j.company)}</td><td>{e(loc)}</td>"
            f"<td>{e(j.salary)}</td><td>{e(j.source)}</td></tr>"
        )
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"""<!doctype html>
<html lang=en><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>Job openings</title>
<style>
:root{{--bg:#fff;--fg:#1d1d1f;--muted:#6e6e73;--line:#e5e5ea;--accent:#0a66c2;--chip:#f2f2f7}}
@media (prefers-color-scheme:dark){{:root{{--bg:#111;--fg:#eee;--muted:#999;--line:#2a2a2a;--accent:#6aa9ff;--chip:#222}}}}
body{{font:14px/1.45 system-ui,sans-serif;margin:0 auto;max-width:1200px;padding:16px;background:var(--bg);color:var(--fg)}}
input{{width:100%;box-sizing:border-box;padding:10px;font:inherit;margin:8px 0 12px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--fg)}}
.wrap{{overflow-x:auto}} table{{border-collapse:collapse;width:100%}}
th,td{{text-align:left;padding:8px;border-bottom:1px solid var(--line);vertical-align:top}}
th{{color:var(--muted);font-weight:600}} a{{color:var(--accent);text-decoration:none;font-weight:600}}
.tag{{display:inline-block;background:var(--chip);color:var(--muted);border-radius:4px;padding:0 6px;margin:4px 4px 0 0;font-size:12px}}
small{{color:var(--muted)}}
</style>
<h1>Job openings</h1>
<small>{len(jobs)} jobs · generated {generated}</small>
<input id=q placeholder="Filter…" autofocus>
<div class=wrap><table><thead><tr><th>Posted<th>Title<th>Company<th>Location<th>Salary<th>Source</thead>
<tbody id=rows>{''.join(rows)}</tbody></table></div>
<script>
q.oninput=()=>{{const t=q.value.toLowerCase();for(const r of rows.rows)r.hidden=!r.textContent.toLowerCase().includes(t)}}
</script>
"""
