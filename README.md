# Daily Job Alert

Checks the career sites of companies you care about, once a day, and
emails you anything new — with a direct link to apply.

It runs as a Docker container on an always-on server. The server has a clone
of this repo; you make changes on your own machine, push them, and pull them
on the server.

## How it works

- `companies.yaml` — the list of companies to watch. Add/remove companies here.
- `connectors/` — one file per career-site platform (Workday, iCIMS-backed API, Marsh's Phenom site, Oracle Recruiting Cloud, Taleo, UKG Pro, Eightfold, plain HTML).
  A company just points at the right one; no code changes needed for
  companies on an already-supported platform.
- `state.json` — remembers what postings we've already seen, so tomorrow's
  email only shows what's genuinely new. The container updates it in place
  in the server's copy of this folder.
- `main.py` — ties it together: fetch → diff against state → email → save state.
- `summary.py` — optional: asks Claude to pick up to ten of the day's new
  postings that best fit your resume (entry-level actuarial, underwriting and
  risk roles) and puts them at the top of the email (see "Top matches" below).
- `compose.yaml` + `Dockerfile` — runs `main.py` every morning in a Docker
  container with its own built-in cron (see "Running with Docker" below).

## One-time setup

### 1. Create an email sender
Easiest option: a Gmail account + an **App Password** (not your normal password).
1. Turn on 2-Step Verification on the Gmail account: https://myaccount.google.com/security
2. Create an App Password: https://myaccount.google.com/apppasswords
3. Save the 16-character password it gives you — you'll need it below.

(Any SMTP provider works, not just Gmail — Outlook, a work email, Resend, etc.
Just change `SMTP_HOST` accordingly.)

### 2. Set up the server
On the server (it only needs Docker and git):

```bash
git clone https://github.com/virtualkergan/job-alerts.git
cd job-alerts
cp .env.example .env              # then fill in your SMTP settings
docker compose up -d --build      # start it; runs daily at 7:00am America/New_York
```

The **first run seeds the baseline** — it won't email you every existing
posting, only ones that appear on the *next* run onward. This is
intentional (see `main.py`).

### Files that live only on the server
`.env` and `resume.pdf` are gitignored, so `git pull` never brings them over:
create `.env` on the server and copy `resume.pdf` to it yourself.

`state.json` is in git, but the server's copy is the live one and will always
show as modified there. The copy in the repo is just an old snapshot. Don't
commit `state.json` from another machine — the server's next `git pull` would
conflict with its own copy.

## Updating the server

After pushing changes from your own machine:

```bash
git pull
docker compose up -d --build      # only needed when code changed
```

`companies.yaml` is mounted into the container, so a change to it takes effect
on the next run with just `git pull`. Anything else (`main.py`, `summary.py`,
`connectors/`, `requirements.txt`) needs the rebuild.

## Adding a company later

1. On your own machine, add a block to `companies.yaml` with a `platform`
   that's already supported (see the examples already in the file) and the
   config it needs.
2. Run `python test_connectors.py "Company Name"` to confirm it finds
   postings before trusting it to the daily run.
3. Commit, push, and `git pull` on the server. The next scheduled run picks
   it up; no rebuild needed.

If a company's platform isn't one of the supported ones, it needs a
small new connector file — a reasonable ask for me to help write once you
tell me the company and I can see its career site.

## Running with Docker

The daily schedule runs in a Docker Compose stack: the container runs
[supercronic](https://github.com/aptible/supercronic) as its cron, so the
server needs nothing but Docker.

```bash
docker compose logs -f            # watch the scheduler and each run's output
docker compose exec job-alerts python main.py --dry-run   # run once now, no email/state
docker compose exec job-alerts python main.py             # run once now, for real
```

- `state.json`, `companies.yaml` and `resume.pdf` are bind-mounted from this
  folder. Keep `state.json` present — if it's missing, Docker creates a
  directory there. The same goes for `resume.pdf`: copy it over before
  `docker compose up`, or delete the empty `resume.pdf` directory Docker
  made and then copy it.
- Change the time or timezone with `CRON_SCHEDULE` / `TZ` in `.env`, then
  `docker compose up -d`. The schedule follows `TZ`, including DST.
- To test the scheduler without emailing or touching state, set
  `CRON_SCHEDULE=* * * * *` and `JOB_ARGS=--dry-run` in `.env`, `docker compose up -d`,
  and watch the logs; remove both lines and `up -d` again when done.
- If the server is down at run time, that day's run is skipped
  (cron doesn't catch up); the next run still reports everything new since.
- A run that hit a problem (a company's site failed, or the Claude summary
  failed) is logged as a failed job in `docker compose logs`, with the reason
  on the line starting `[Company Name]` or `[summary]`.

## Top matches (optional)

To get a "Top matches for you" section at the top of each email, on the server:

1. Copy your resume to this folder as `resume.pdf` (it's gitignored).
2. Create an API key at https://console.anthropic.com/settings/keys and put it
   in `.env` as `ANTHROPIC_API_KEY=...`.
3. `docker compose up -d --build`.

Try it without waiting for the morning run:
`docker compose exec job-alerts python summary.py "Aon"` ranks one company's
current postings and prints the picks. Each daily run makes two
Claude API calls, which costs roughly 10 to 25 cents on a busy day (model: `MODEL` in `summary.py`). If
`resume.pdf` is missing the section is simply left out; if the Claude call
fails, the email still arrives without it and the run is marked failed in the logs.
To change what counts as a match, edit `CRITERIA` at the top of `summary.py`.

## Running locally (for testing changes)

Useful on your own machine before pushing:

```bash
pip install -r requirements.txt
python test_connectors.py  # sanity-checks every connector, no email involved
python main.py --dry-run   # prints what it would email, sends nothing, leaves state.json untouched
```

Stick to `--dry-run` here: a real `python main.py` would send a second email
and rewrite the local `state.json`, which isn't the one the server uses.
