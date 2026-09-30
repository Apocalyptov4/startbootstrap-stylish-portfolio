# Job Radar

Job Radar is an app that collects job openings from many sites into one list. You can search it, filter it, and track which jobs you've saved or applied to. It runs on your own computer and opens in your web browser.

![Job Radar screenshot](docs/screenshot.png)

## Start the app

You need [Python 3](https://www.python.org/downloads/) installed. On Windows, tick "Add python.exe to PATH" during installation.

* **Windows:** double-click `start.bat`.
* **macOS:** double-click `start.command`. The first time, you may need to right-click it and choose **Open**.
* **Linux or a terminal:** run `./start.command`, or `pip install -r requirements.txt` followed by `python -m jobscraper ui`.

The app opens at <http://127.0.0.1:8765>. It keeps running while that window is open. Close the window, or press Ctrl+C, to stop it.

To try the app with made-up sample jobs, start it with `python -m jobscraper ui --demo`. This works without an internet connection.

## What you can do in the app

* **Refresh** checks every site you follow and shows the combined list, with duplicate postings removed and the newest first.
* **Search and filter** by keyword, location, remote only, posting date and site. You can also hide titles containing certain words, such as "senior".
* **Save** (star), **Mark applied** (check mark) or **Hide** (crossed-out eye) any job. The tabs across the top list each group.
* The **New** tab shows jobs that appeared since your last refresh.
* **Click a job** to see its details, then use **Open job posting** to apply on the company's site.
* **Settings** (gear icon) lets you turn job sites on or off and follow specific companies. Paste a careers link such as `jobs.lever.co/spotify`, `boards.greenhouse.io/stripe` or `jobs.ashbyhq.com/notion`.

Your settings, the jobs found and your saved, applied and hidden marks are stored in the `~/.jobscraper` folder on your computer. Use `--data-dir` to store them somewhere else.

Other options: `--port 8766` if port 8765 is already in use, and `--no-browser` to stop the app opening a browser tab.

---

## How it gets the jobs

It uses each site's **public JSON API** and does not parse HTML pages. That makes it faster and more reliable than HTML scraping, and it stays within what these sites allow.

| Source | What it covers | Config key |
|---|---|---|
| [RemoteOK](https://remoteok.com) | Remote jobs, mostly tech | `boards.remoteok` |
| [Remotive](https://remotive.com) | Remote jobs, all categories | `boards.remotive` |
| [Arbeitnow](https://www.arbeitnow.com) | Europe and Germany, including visa-sponsored roles | `boards.arbeitnow` |
| Hacker News "Who is hiring?" | Top-level posts in the latest monthly thread | `boards.hackernews` |
| [Greenhouse](https://www.greenhouse.com) | Career pages of any company on Greenhouse | `companies.greenhouse` |
| [Lever](https://www.lever.co) | Career pages of any company on Lever | `companies.lever` |
| [Ashby](https://www.ashbyhq.com) | Career pages of any company on Ashby | `companies.ashby` |

Most tech companies host their careers page on Greenhouse, Lever or Ashby. To track a company, find its slug in the careers URL and add it to your config:

```
boards.greenhouse.io/<slug>   or  job-boards.greenhouse.io/<slug>  -> "greenhouse"
jobs.lever.co/<slug>                                               -> "lever"
jobs.ashbyhq.com/<slug>                                            -> "ashby"
```

## Command-line version

The same search also works in a terminal without the app. This is useful for scripts and scheduled digests.

```bash
# All default boards (RemoteOK, Remotive, Arbeitnow, HN), newest first
python -m jobscraper

# Remote Python or Django jobs from the last 7 days, excluding senior roles
python -m jobscraper -k python -k django --remote --days 7 -x senior -x staff

# Include the companies listed in your config, and save a searchable HTML page
cp sources.example.json sources.json      # then edit the company lists
python -m jobscraper -c sources.json -k "data engineer" -f html -o jobs.html

# Only query some sources
python -m jobscraper -c sources.json -s greenhouse,lever -l berlin -l remote

# Daily digest: print only postings not seen in earlier --new-only runs
python -m jobscraper -c sources.json -k rust --new-only -f md
```

### Options

| Flag | Meaning |
|---|---|
| `-k, --keyword` | Keep jobs that match **any** keyword. Repeatable. Matches whole words, so `java` does not match JavaScript and `go` does not match Google. Searches the title, company, tags and description. |
| `--title-only` | Match keywords against the title only. |
| `-x, --exclude` | Drop jobs whose title contains this word. Repeatable. |
| `-l, --location` | Keep jobs whose location contains this text. Repeatable. `remote` also matches jobs flagged as remote. |
| `--remote` | Remote jobs only. |
| `--days N` | Only jobs posted in the last N days. Jobs without a date are kept. |
| `-s, --sources` | Comma-separated subset: `remoteok,remotive,arbeitnow,hackernews,greenhouse,lever,ashby`. |
| `-f, --format` | `table` (default), `csv`, `json`, `md`, or `html` (a standalone page with a live filter box). |
| `-o, --output` | Write the output to a file. |
| `-n, --limit` | Show at most N jobs. |
| `--new-only` / `--state` | Show only postings not seen before. Seen postings are stored in `.jobscraper-seen.json`. |
| `-v` | Print progress for each source to stderr. |

If a source fails (site down, rate-limited, wrong slug), the run continues. The failure is reported at the end. When the same role is posted on several sites, it appears once.

## Running it on a schedule

Example cron entry for a daily email digest:

```cron
0 8 * * *  cd ~/job-scraper && python -m jobscraper -c sources.json -k python --new-only -f md | mail -s "New jobs" you@example.com
```

## Adding a new source

1. Subclass `Source` (a whole job board) or `CompanySource` (one company on an ATS) in `jobscraper/sources/`.
2. Implement `fetch(session)` so it yields `Job` objects.
3. Register the class in `jobscraper/sources/__init__.py`.
4. Add a fixture and a parsing test in `tests/`.

## Tests

```bash
python -m unittest -v      # offline; all HTTP responses come from tests/fixtures
```

## Project layout

```
jobscraper/
  sources/     one module per kind of site; each yields Job objects
  scraper.py   fetches all sources in parallel, then filters, de-duplicates and sorts
  server.py    the local web app's server and JSON API (standard library only)
  web/         the app's page: index.html, style.css, app.js (no build step)
  cli.py       the command-line version
```

## Be a good citizen

* RemoteOK and Remotive ask you to link back to them when you show their listings. Remotive also asks for no more than about 4 requests a day.
* Keep the run frequency sensible. Once or a few times a day is plenty.
* This tool deliberately does not scrape LinkedIn, Indeed or Glassdoor. Their terms forbid automated scraping, and they actively block it.
