# 🎯 Job Search Assistant

**Your own 24x7 job hunter.** It watches job sites around the clock, ranks every job against your CV, and hands you a ready CV, cover letter and referral message for the best ones.

![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![Windows](https://img.shields.io/badge/Windows-10%20%7C%2011-0078D6?logo=windows&logoColor=white)
![Playwright](https://img.shields.io/badge/Playwright-Chrome-2EAD33?logo=playwright&logoColor=white)
![Excel](https://img.shields.io/badge/Tracker-Excel-217346?logo=microsoftexcel&logoColor=white)
![Telegram](https://img.shields.io/badge/Alerts-Telegram-26A5E4?logo=telegram&logoColor=white)
![Tests](https://img.shields.io/badge/tests-125%20passing-brightgreen)

---

## ✨ Features

| | Feature | What you get |
|---|---|---|
| 🔎 | **20+ job sources** | LinkedIn, Naukri, Indeed, Instahyre, Foundit, Naukri Gulf, remote boards and 100+ company career pages |
| ⏱️ | **Checks every 15 minutes** | A new job usually reaches you within half an hour of being posted |
| 🧠 | **Smart scoring** | Every job scored 0 to 100 against your CV, with the reasons shown |
| 🚫 | **Filters what you cannot get** | Country locked remote jobs, wrong level, required languages, student only roles |
| 📊 | **One Excel tracker** | Today, Apply Queue, Follow Ups, Remote Jobs, All Jobs and Health tabs |
| 📄 | **CV per job** | A copy of your CV with the job's own title as the headline |
| ✉️ | **Cover letter per job** | Built only from your real facts, plus ready form answers |
| 🤝 | **Referral helper** | A LinkedIn people search and a ready message for every good job |
| 🔔 | **Alerts** | Windows pop ups, and Telegram cards with one tap Applied or Skip |
| 🛡️ | **Scam flags** | Fee demands, identity rental gigs and fake companies are flagged |
| 🔒 | **Private** | Runs on your laptop. Your CV and data never leave it |

## 🚀 Setup in 3 steps

> No coding needed. About an hour, mostly answering questions about your work.

**1️⃣ Install the Claude app**
Get it from **claude.ai/download**, sign in (Pro plan or higher) and open the **Code** tab.

**2️⃣ Make a folder**
Create an empty folder (for example **JobSearch** in Documents), put your CV inside, and choose this folder in the Code tab.

**3️⃣ Paste this line and press Enter**

```
Set up the job search assistant from github.com/srimadhavsats/job-search-assistant in this folder, then follow its START_HERE.md
```

✅ That is it. Python and Google Chrome are installed if missing, you answer a few questions, and the search is tuned to your field. Allow it when it asks to run something.

## 📅 Every day

| Step | What to do |
|---|---|
| 1 | Open **output\Jobs.xlsx** and start with the **Today** tab |
| 2 | Click **Apply**, then the **CV** and **Cover letter** links for that job |
| 3 | Send the ready **referral message** to someone on that team |
| 4 | Set **Status** to Applied. The next job moves up by itself |

## 🛠️ Tech stack

| Layer | Technology |
|---|---|
| Language | Python 3.11+ |
| Web requests | httpx with retries, back off and a per site circuit breaker |
| Parsing | BeautifulSoup, lxml, feedparser |
| Browser sites and PDFs | Playwright driving installed Google Chrome |
| Job boards | LinkedIn guest search, python-jobspy (Indeed), Greenhouse, Lever, Ashby, Workable and SmartRecruiters APIs |
| Storage | SQLite |
| Tracker | Excel through openpyxl |
| Settings | YAML files, no code changes needed |
| Scheduling | Windows Task Scheduler and PowerShell |
| Alerts | Windows toast notifications, Telegram Bot API, ntfy |
| Tests | pytest, 125 offline tests |

## 🗂️ Project layout

| Path | What it holds |
|---|---|
| `jobhunter/` | The engine. Sources, scoring, watcher, workbook, CVs, cover letters, bot |
| `jobhunter/sources/` | One adapter per kind of job site |
| `config/` | Search words, sites, CV rules, cover letter pieces, alerts |
| `tests/` | Offline tests for parsers, scoring, workbook and watcher |
| `docs/` | User guide, code notes, build log, adding a new site |
| `setup.bat` | One click install |
| `run_jobs.bat` | Search every site now |
| `setup_watcher.bat` | Turn on the 24x7 watcher |
| `check_system.bat` | Health check of everything |

## 💡 Good to know

- 💻 The laptop must be on and signed in to Windows for the 15 minute checks. If it was off, it catches up when you switch it on.
- 🙅 It never applies or messages anyone for you. You review and send.
- 🌐 It only reads public job pages and never logs in to LinkedIn or Naukri as you.
- 🇮🇳 Built for job seekers in India. Other countries need some tuning.

## 📚 Docs

| Doc | For |
|---|---|
| [User guide](docs/USER_GUIDE.md) | The Excel tabs, alerts and Telegram bot |
| [Start here](START_HERE.md) | The step by step setup plan |
| [Code notes](docs/CODE_NOTES.md) | How the code fits together and what to change |
| [Build log](docs/BUILD_LOG.md) | Why each rule exists |
| [Adding a site](docs/ADDING_A_SOURCE.md) | Add a new job board |
