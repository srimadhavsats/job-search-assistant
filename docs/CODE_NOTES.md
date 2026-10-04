# Code notes (read this before changing anything)

This system was first built for one person's crypto job search in India, where it ran 24x7 on a Windows laptop with about 20 sources. Personal details were removed before it was published (CVs, career facts, playbook, salary, tokens and the job database). What is left is the code, the configs as crypto examples, placeholder CV and cover letter configs, and the technical build log in docs/BUILD_LOG.md. All 125 tests pass.

Whoever sets it up should adapt it to the person using it (START_HERE.md), not to rewrite it.

## Running it

1. `setup.bat` finds Python 3.11 or newer (it skips free-threaded builds, which lack wheels for some packages) and Google Chrome, installs them with winget when missing, then creates `.venv` from `requirements.txt`. Playwright uses the installed Chrome (channel chrome), so `playwright install` is never needed.
2. Tests `.venv\Scripts\python.exe -m pytest tests -q` (all offline, mocked).
3. A quick real check `.venv\Scripts\python.exe -m jobhunter.main --only cryptocurrencyjobs --no-alerts` fetches one RSS feed and builds the workbook, CVs and cover letters from the placeholders.
4. Some tools set NoDefaultCurrentDirectoryInExePath, so `cmd` does not find a bare `setup.bat` in the current folder. Call batch files by their full path, and inside batch files use `%~dp0` for sibling files.

## Map of the code

| File | What it does |
|---|---|
| `jobhunter/main.py` | Full run of every source (run_jobs.bat) |
| `jobhunter/watch.py` | 24x7 watcher. Runs sources that are due, the morning full pass and catch ups after gaps. `--status` shows the schedule |
| `jobhunter/pipeline.py` | Shared by both. Fetch, score, merge, link check, CVs, cover letters, save, alerts, state for the bot |
| `jobhunter/net.py` | HTTP client with retries, back off, Retry-After and a per host circuit breaker |
| `jobhunter/lock.py` | OS file lock (Windows msvcrt) so two runs never overlap |
| `jobhunter/store.py` | SQLite memory of every job, source health, alerts sent, custom CVs and feedback |
| `jobhunter/scoring.py` | Score 0 to 100, Why and Flags. Every weight comes from `config/profile.yaml` |
| `jobhunter/verify.py` | Link check that opens the apply pages of good jobs |
| `jobhunter/cv.py`, `jobhunter/cover.py` | Per job CVs and cover letters from HTML templates, `config/cvs.yaml` and `config/cover_letters.yaml` |
| `jobhunter/excel.py` | The workbook `output/Jobs.xlsx` (Today, Apply Queue, Follow Ups, Remote Jobs, Freelance, All Jobs, day tabs, Health, Run Log) with status sync |
| `jobhunter/plan.py` | The Today plan and the daily routine |
| `jobhunter/notify.py` | Windows pop ups, Telegram and ntfy alerts |
| `jobhunter/tgbot.py` | Telegram bot. The token is set by the person with `setup_telegram.bat`, never through chat |
| `jobhunter/doctor.py` | `check_system.bat`, a live health check of everything |
| `jobhunter/sources/` | One adapter per kind of site. `docs/ADDING_A_SOURCE.md` explains how to add one |
| `schedule_job_search.ps1` | Registers the scheduled tasks "Job Search Watcher" and "Job Search Bot" |

`docs/BUILD_LOG.md` explains why the code is the way it is, entry by entry. Read the matching entry before undoing a rule. Code comments that mention "PLAYBOOK section N" refer to the first owner's playbook, which is not included.

## What is crypto specific and must change

1. **`config/profile.yaml`** is the heart of it. Title tiers, skills, `missing_skills`, `web3_terms`, the LinkedIn, Naukri and Naukri Gulf search lists, scam words, the required certificate rule and the specialist years rule are all written for crypto. The rule that caps jobs with no web3 word becomes a domain relevance rule for any field once `web3_terms` holds words that mark a job in that field (for finance operations, for example reconciliation, accounts payable, general ledger, month end, treasury, settlement). The names in the code stay `web3_*`, which is fine.
2. **`config/sources.yaml`**. Turn off the crypto only sources (CryptoJobsList, web3.career, crypto.jobs, CryptocurrencyJobs, Telegram channels, Superteam Earn, VC job boards, JobStash, HN Who is hiring, Freelancer) and the crypto company career lists. Keep and retune LinkedIn, Naukri, Indeed, India boards (Instahyre and Foundit suit most fields, Internshala suits students, Cutshort suits tech), Apna for entry level roles, Naukri Gulf only for the Gulf, and Remote APIs only for remote work. Some adapters filter to crypto inside the code (`remote_boards.py`, `hn_hiring.py`, `jobstash.py`, `vc_boards.py`, and a crypto check in `linkedin.py` that decides which descriptions to fetch), so check them before reuse.
3. **Missing adapters.** Workday (many banks and large companies use it, the public search is a JSON POST to the site's `wday/cxs/TENANT/SITE/jobs` path), iimjobs, and lists of employers in the person's field on Greenhouse, Lever, Ashby, SmartRecruiters, Workable and Workday. Probe each live before adding it, and sample titles to catch companies with the same name.
4. **`config/cvs.yaml`, `config/cover_letters.yaml` and `CV_Template_Example.html`** are placeholders. Build the real CV templates from the person's CV in the same HTML structure. `div.role` is the headline and the first span in `div.contact` is the location line, the only two things changed per job. Fill cover letter pieces only from `Career_Facts.txt`. The family ids `tm`, `research`, `general` and `india` are used by name in `jobhunter/cover.py` (`pick_evidence` and the `qa` gap), so rename them in both places if you rename them.
5. **`jobhunter/plan.py`**. ROUTINE is a generic default. Fit it, DAILY_TARGET and WEEKLY_TARGET to the person's day.
6. **Freelance and Earn Platforms tabs** were for bounties and gigs. `config/earn_platforms.yaml` is empty. Keep them, or switch them off if the person only wants salaried jobs.
7. **Tests.** `tests/test_scoring.py`, parts of `tests/test_cv.py`, `tests/test_sources.py` and `tests/test_guidance.py` encode crypto job cases. Replace them with real cases from the person's field as the scoring is retuned. Every new rule should get a test built from the real job that caused it.
8. **Alerts in `config/notify.yaml`** are generic. The Telegram token and chat id stay empty there, and `setup_telegram.bat` writes `config/telegram.yaml`, which git ignores.

## Lessons worth keeping (details in docs/BUILD_LOG.md)

1. LinkedIn guest search needs a fresh 24 hour pass sorted by date on every check, plus a daily relevance backfill, or new posts are buried.
2. Naukri only works through the installed Chrome with a normal user agent, a persistent profile and slow pauses. Never raise how often LinkedIn, Naukri, Naukri Gulf or Apna are checked, they block.
3. One failing site never stops a run, and a site that returns far fewer jobs than usual is flagged as probably blocked. Quick watcher checks keep their own usual count.
4. Status edits are read from every tab and side file, apply links are always rewritten from the database, and saves are atomic with a backup.
5. Region locked remote jobs, required languages, students only, work authorisation in another country, "based in" another country hidden in the text, and required certificates are capped at 45. "Global remote company" is not the same as "hires from India".
6. The morning full search is the first watcher check after 09.30, never a fixed time task, because fixed time tasks are missed when the laptop is off.

## Keeping it private

`.gitignore` keeps the person's files out of git (`Career_Facts.txt`, `PLAYBOOK.md`, `HANDOFF.md`, CV and cover letter files, `config/telegram.yaml`, `data/`, `output/`). The config files are tracked, so once they hold personal details, do not push this folder to a public repository.
