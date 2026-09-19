# Daily Job Alert

Checks the career sites of companies you care about, once a day, and
emails you anything new — with a direct link to apply.

## How it works

- `companies.yaml` — the list of companies to watch. Add/remove companies here.
- `connectors/` — one file per career-site platform (Workday, iCIMS-backed API, Marsh's Phenom site, plain HTML).
  A company just points at the right one; no code changes needed for
  companies on an already-supported platform.
- `state.json` — remembers what postings we've already seen, so tomorrow's
  email only shows what's genuinely new. Gets committed back to the repo
  automatically after each run.
- `main.py` — ties it together: fetch → diff against state → email → save state.
- `.github/workflows/daily-job-alert.yml` — runs `main.py` every morning
  in GitHub Actions, for free.

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
- Click "Daily Job Alert" → "Run workflow" to trigger it manually right away,
  rather than waiting for the 7:47am EDT schedule.
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
3. Commit and push. Next scheduled run picks it up automatically.

If a company's platform isn't one of the supported ones, it needs a
small new connector file — a reasonable ask for me to help write once you
tell me the company and I can see its career site.

## Running locally (optional)

```bash
pip install -r requirements.txt
export SMTP_HOST=smtp.gmail.com SMTP_PORT=587 SMTP_USER=... SMTP_PASS=... ALERT_TO=...
python main.py --dry-run   # prints what it would email, sends nothing, leaves state.json untouched
python main.py             # actually sends the email
python test_connectors.py  # sanity-checks every connector, no email involved
```
