# Daily Job Alert

Checks the career sites of companies you care about, once a day, and
emails you anything new — with a direct link to apply.

## How it works

- `companies.yaml` — the list of companies to watch. Add/remove companies here.
- `connectors/` — one file per career-site platform (Workday, iCIMS-backed API, Marsh's Phenom site, Oracle Recruiting Cloud, Taleo, UKG Pro, Eightfold, plain HTML).
  A company just points at the right one; no code changes needed for
  companies on an already-supported platform.
- `state.json` — remembers what postings we've already seen, so tomorrow's
  email only shows what's genuinely new. The Docker stack updates it in place
  in this folder; a manual GitHub Actions run commits it back to the repo.
- `main.py` — ties it together: fetch → diff against state → email → save state.
- `compose.yaml` + `Dockerfile` — runs `main.py` every morning in a Docker
  container with its own built-in cron (see "Running with Docker" below).
- `.github/workflows/daily-job-alert.yml` — runs `main.py` in GitHub Actions
  when triggered manually (its daily schedule is off, since Docker handles that).

## One-time setup (about 10 minutes)

### 1. Create a GitHub repo
Push this folder to a new **private** GitHub repository.

### 2. Create an email sender
Easiest option: a Gmail account + an **App Password** (not your normal password).
1. Turn on 2-Step Verification on the Gmail account: https://myaccount.google.com/security
2. Create an App Password: https://myaccount.google.com/apppasswords
3. Save the 16-character password it gives you — you'll need it below.

(Any SMTP provider works, not just Gmail — Outlook, a work email, Resend, etc.
Just change `SMTP_HOST` accordingly.)

For the Docker setup (the daily scheduler), these same values go in `.env`
instead; see "Running with Docker" below. Steps 3–4 are only needed if you
also want to be able to run it manually from GitHub Actions.

### 3. Add secrets to the GitHub repo
Repo → Settings → Secrets and variables → Actions → New repository secret.
Add these:

| Secret | Value |
|---|---|
| `SMTP_HOST` | `smtp.gmail.com` |
| `SMTP_PORT` | `587` |
| `SMTP_USER` | the Gmail address |
| `SMTP_PASS` | the 16-character app password |
| `ALERT_TO` | the email address you want alerts sent to (can be the same address) |

### 4. Turn on Actions and test it
- Repo → Actions tab → enable workflows if prompted.
- Click "Daily Job Alert" → "Run workflow" to trigger it manually (it has no
  schedule of its own).
- Check the run's logs to see how many postings each company found.

The **first run seeds the baseline** — it won't email you every existing
posting, only ones that appear on the *next* run onward. This is
intentional (see `main.py`).

## Adding a company later

1. Add a block to `companies.yaml` with a `platform` that's already supported
   (`workday`, `attract_api`, `marsh_phenom`, or `html_scrape`) and the config it needs (see the
   examples already in the file).
2. Run `python test_connectors.py "Company Name"` locally to confirm it
   finds postings before trusting it to the daily run.
3. Save it. The Docker stack's next scheduled run picks it up automatically
   (`companies.yaml` is mounted, so no rebuild needed). Commit and push if
   you want it in GitHub too.

If a company's platform isn't one of the supported ones, it needs a
small new connector file — a reasonable ask for me to help write once you
tell me the company and I can see its career site.

## Running with Docker

The daily schedule runs in a Docker Compose stack: the container runs
[supercronic](https://github.com/aptible/supercronic) as its cron, so the host
needs nothing but Docker.

```bash
cp .env.example .env              # then fill in your SMTP settings
docker compose up -d --build      # start it; runs daily at 7:00am America/New_York
docker compose logs -f            # watch the scheduler and each run's output
docker compose exec job-alerts python main.py --dry-run   # run once now, no email/state
docker compose exec job-alerts python main.py             # run once now, for real
```

- `state.json` and `companies.yaml` are bind-mounted from this folder:
  edits to `companies.yaml` apply on the next run (no rebuild), and
  `state.json` is updated in place, so it'll show as modified in git.
  Keep `state.json` present — if it's missing, Docker creates a directory there.
- Change the time or timezone with `CRON_SCHEDULE` / `TZ` in `.env`, then
  `docker compose up -d`. The schedule follows `TZ`, including DST.
- To test the scheduler without emailing or touching state, set
  `CRON_SCHEDULE=* * * * *` and `JOB_ARGS=--dry-run` in `.env`, `docker compose up -d`,
  and watch the logs; remove both lines and `up -d` again when done.
- If the machine is off or asleep at run time, that day's run is skipped
  (cron doesn't catch up); the next run still reports everything new since.
- Avoid also running the GitHub workflow manually: it commits its own
  `state.json`, which will conflict with the local one.

## Running locally (optional)

```bash
pip install -r requirements.txt
export SMTP_HOST=smtp.gmail.com SMTP_PORT=587 SMTP_USER=... SMTP_PASS=... ALERT_TO=...
python main.py --dry-run   # prints what it would email, sends nothing, leaves state.json untouched
python main.py             # actually sends the email
python test_connectors.py  # sanity-checks every connector, no email involved
```
