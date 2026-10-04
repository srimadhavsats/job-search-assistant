# Build log of the base code

This is the technical build log of the job search tool this kit comes from. It was built for one person's
crypto job search in India, September 2026. Personal details were removed. Each dated entry says what
broke, why, and how it was fixed. Most rules in the code exist because a real job slipped through or a
real run failed, so read the matching entry before undoing one. Crypto specific parts (web3 words,
crypto boards, crypto companies) are examples to replace. Section numbers refer to the original file.

Names changed since this log was written. The workbook Web3_Jobs.xlsx is now Jobs.xlsx, the tasks Web3 Job Watcher and Web3 Job Bot are now Job Search Watcher and Job Search Bot, handoff.md is this file, and the first owner's PLAYBOOK.md and CV files are not included.

## 0B. The 24x7 system (built 2026-09-25, owner request. "more sources, 24x7 watcher, CV column, Remote tab, no job missed")

**Why.** The 18.30 run on 25 Sep lost all ~390 web3.career jobs to one `ReadTimeout` (the whole source raised), LinkedIn hit two 429s, and jobs were only picked up twice a day. The owner asked for more sources, a round-the-clock watcher with alerts, a CV link per job (custom CVs built automatically), a Remote tab, test scripts, and workarounds for fetch errors. Backup of the pre-change code, config, workbook and DB is in `data/backups/2026-09-25_pre_watcher/`.

| Piece | File | What it does |
|---|---|---|
| Resilient HTTP | `jobhunter/net.py` | Every `util.http_client()` is now a `RetryClient`. Retries timeouts, resets, 429 and 5xx with back-off and `Retry-After`, per-host circuit breaker (after 4 fully failed requests to a host, that host is skipped for the rest of the run), `browser_get()` real-Chrome fallback for Cloudflare pages (`browser_fallback: true` on html sources). LinkedIn and Apna pass `retry_429=False` (they run their own back-off. Link11 punishes retries). html, rss, telegram, superteam now skip a failed page/feed/channel and keep the rest. A source only fails when every part failed. The full run also retries a failed source once after 75 s |
| Pipeline | `jobhunter/pipeline.py` | Shared by `main.py` (full run) and `watch.py`. Fetch, score/merge, per-source state, link check, CVs, save, alerts. Writes `data/last_run.json` |
| Watcher | `jobhunter/watch.py` | Task **Web3 Job Watcher** runs `pythonw -m jobhunter.watch` every 15 min (hidden, log `output/watch.log`). Each source has `every_minutes` in `sources.yaml` (ATS 30, feeds 20, LinkedIn 60 fresh-only via `watch:` overrides, Naukri 240, Apna 360, Naukri Gulf 480…). Failures reschedule after 15, 30, 60… max 360 min (`store.record_source`). `--status`, `--force NAME`, `--loop` |
| Lock | `jobhunter/lock.py` | OS file lock on `data/run.lock` (msvcrt), released by the OS even on crash. Watcher skips a tick if busy, full run waits up to 50 min |
| Store | `jobhunter/store.py` | New tables in `seen_jobs.sqlite`. `source_state`, `notified`, `link_checks`, `custom_cvs`, plus `jobs.found_at` |
| CVs | `jobhunter/cv.py`, `config/cvs.yaml` | PLAYBOOK section 5 rules pick tm / research / general / india template. For New, applicable rows with score ≥ 55 a copy is rendered (Chrome, `prefer_css_page_size`) into `output/cvs/Name_CV_<Company>_<Title>.pdf` with ONLY the `.role` headline (cleaned job title + tagline) and the first contact span (location line fitting the job) changed. Refuses to build if banned punctuation would appear. Rebuilt only when the template or the two lines change (hash). Template PDFs re-render when their HTML is newer. Unlinked custom CVs are deleted after 30 days |
| Link check | `jobhunter/verify.py` | Opens apply pages of New rows with score ≥ 55 (not ATS rows, not Telegram/Naukri/Apna), at most once a day. 404/410/closed wording to "Closed", location/language/student/work-authorisation wording to "Apply page requires…" flag and score capped at 45. Budget 80 per full run, 25 per watcher tick |
| Alerts | `jobhunter/notify.py`, `config/notify.yaml` | Windows toast via PowerShell (`-EncodedCommand`, PowerShell AppID) with Open job / Open CV buttons. Telegram (bot token + chat id, sends the CV PDF) and ntfy optional. Score ≥ 60 (remote open to India ≥ 55), freelance ≥ 65, never locked/closed, once per job. A source failing 3 checks in a row alerts once a day |
| Workbook | `jobhunter/excel.py` | New tabs **Apply Queue** (first, New + applicable + score ≥ 55, band then freshest, with CV, `Find referrer` LinkedIn people search and a filled `Referral message`), **Remote Jobs**, **Health**. New columns CV, Link check, Found at, hidden Saved status / Saved notes. Status sync rewritten. An edit is a cell that differs from its saved copy, in ANY tab or side file (fixes Applied in All Jobs being overwritten by "New" on the same day's tab). Side files are merged row by row (new rows added, edits kept) and deleted. "not seen since" only when the row's source ran fine after the row's last-seen date. Run Log keeps 14 days |
| Doctor | `jobhunter/doctor.py`, `check_system.bat` | Live "test demo". Every source with a tiny search, Chrome/PDF, CV templates clean, workbook, disk, scheduled tasks, watcher heartbeat, alerts. `--popup` sends a test alert |
| Tests | `tests/` | 83 offline pytest tests (mock transports). Retries/breaker, partial-failure sources, Getro/Consider/JobStash/Himalayas/Indeed parsing, scoring regressions from this file, CV rules, workbook sync and side files, link check, watcher backoff, lock, alerts |

**New sources (all probed live 2026-09-25).** `vc_boards` (Getro API needs `Accept: application/json` and `hits_per_page` in snake case, camelCase caps at 20. Consider needs the page's `csrfToken` as `x-csrf-token`), `jobstash` (now indexes non-crypto jobs too, kept only if the org has projects or text has web3 words. Full-time CONTRACT roles stay jobs), `remote_apis` (Himalayas `locationRestrictions`/`timezoneRestrictions`, Jobicy `jobGeo`, written into Location so region rules apply), `indeed` (python-jobspy. Plain requests get 403. "TN, IN" locations converted, they were all read as abroad), `india_boards` (Instahyre API, Internshala cards, Cutshort Next data, Foundit API needs Referer), `hn_hiring` (Algolia, crypto posts only), `freelancer` (public API). Company careers grew from 55 to ~132 after probing ~460 crypto companies on Greenhouse/Lever/Ashby/Workable/SmartRecruiters/Recruitee (new adapters). Name collisions checked by sampling titles. Ramp, Figure (kept as "mixed"), Socket, Amber, Compound, Osmosis, Kenetic, Nexus, Galaxy, Foundry, Sequence, Newton are NOT the crypto firms. Robinhood, Brave, Sardine, Figure are in `Company careers (mixed)` with `web3_native: false`. Blocked and skipped. Glassdoor (400), Wellfound and BeInCrypto (Cloudflare), Reddit JSON (403), remote3/useweb3 (no data), most crypto Telegram job channels (dead since 2022 to 2024). Workable rate-limits bursts (a 460-company probe got 429s), which the retry client absorbs.

**Also fixed on 25 Sep.** One CV template had 45 semicolons/colons in visible text (against the owner's rule). Punctuation only was rewritten in TM CV style (labels as "Label." with the next word capitalised, "Client" plus a colon before Google became "Client Google", "Senior Analyst - Quality / SME" to "Senior Analyst - Quality"), wording and facts unchanged, original in the backup folder. Its PDF re-renders automatically. New scam terms. Flash bitcoin/usdt, drainer, crypto recovery (a "Flash Bitcoin Generator Webapp" gig scored 81 on Freelancer). New scoring rule `WORK_AUTH` in `scoring.out_of_reach` ("must be authorized to work in the US/UK/EU…" unless India or hire-anywhere wording is near).

**Review of the first full run (same evening) and the fixes it led to.** 20/20 sources ok, 794 jobs + 173 gigs, 441 new, 130 custom CVs, 80 apply pages opened. Reading the Apply Queue row by row found. (1) Freelancer.com build and marketing gigs at 83 because any description word ("support", "test") gave full task points, now title match = full points, text-only match −15 (`desc_only_task_penalty`), plus dev/BD/assistant `off_task_words`. Flash-coin and "account setup" moved to `illegal_gig_terms`. (2) the queue is now jobs only, and excludes ⚠ SCAM rows, Senior/Lead/Manager titles under 70 and "Old post" evergreens (PLAYBOOK section 5). (3) Rain "Compliance Associate - Bank Sponsorship" (New York) scored 77, `visa_terms` are now read from the description only and bare "sponsorship" was removed. (4) Himalayas/Jobicy country lists are written "Remote (X only)" and "only" in a location blocks the hire-anywhere rescue (Crypto Banter, South Africa). (5) `title_region_patterns` catch "US MLRO…", "(UK)", "- US". (6) internships abroad are capped (Bybit Operations Intern, UAE), also in `_region_guard` for rows not refetched. (7) link check now reads Ashby/Lever/Greenhouse links through their APIs (VC boards link there without text. Wormhole's "Based in the US" was only visible that way) and flags the careers site's own location. (8) `mark_applied_duplicates`. A New row at a company you applied to with the same title is hidden ("Looks like the job you already applied to"), a contained title gets a warning ("Maybe the same job…", one bank QA job on Apna, Indeed and Naukri), any other row there gets "You already applied at this company (n)". After the fixes the queue went 183 to 103 (46 apply now, 45 remote). Also added the **Follow Ups** tab (Applied 5 to 21 days ago with the PLAYBOOK follow-up message. A Status change stamps `Status date`. Rows applied before 25 Sep use First seen). Test suite. 93.

**2026-09-26, first night of the watcher (rain, Wi-Fi outage, laptop off 05.10 to 11.14).** About 30 checks ran 21.00 to 04.24 with no timeouts, retries or failed sources. Wi-Fi dropped about 04.35 and the next three checks logged "no internet" and exited cleanly. At login the watcher resumed by itself. Three problems found and fixed. (1) False "probably blocked" alerts for LinkedIn and JobStash (22.55, 00.09, 00.44). Quick watcher checks (`watch:` settings) fetch far fewer jobs than full runs, but were compared with the full-run median. Now `pipeline.usual_key()` keeps a separate "<name> [quick]" history, and the Run Log marks quick checks. The false failures had also put LinkedIn on back-off (checked every 2 h instead of hourly). (2) The 10.00 "Web3 Job Search" task never ran because the laptop was off at 10.00 (LastRunTime 1999, 0x41303) despite StartWhenAvailable. It is now unregistered (`$Times = @()`), and the watcher does the morning full search itself. The first check at or after 09.30 each day with no full pass yet (`watch.morning_pass_due`, marker `data/last_full_run.txt`, written by any full run of every source). (3) After a long gap, quick settings would miss posts from the gap (JobStash `publication_date: today`), so a source with quick settings not checked for 6 h or 3 cadences runs once with full settings (`watch.needs_catch_up`, `pipeline.run(full_names=…)`). Also. If a source fails and a post-check internet probe fails, it is postponed 15 min without counting a failure (`store.postpone`), and the watcher task gained a trigger on NetworkProfile event 10000 (network connected). The one 429 of the night came from LinkedIn at 11.19 during the 20-source catch-up and was absorbed by the 60 s back-off. Tests. 97.

**Restart and power-cut check (2026-09-26 afternoon).** Watcher task settings confirmed (time + logon + network-connected triggers, runs on battery, not stopped on battery, StartWhenAvailable, InteractiveToken, so it needs a Windows sign-in, not any app opened). Evidence from the morning. Boot 11.14.16, watcher started 11.14.35 by itself. Two simulated power cuts with `taskkill /F /T`. Mid-fetch (next check ran normally, OS released `run.lock`) and exactly while `Web3_Jobs.saving.tmp` was being written (main workbook untouched, DB `integrity_check` ok, all statuses kept, next save removed the temp file). Both cases are now tests (99). Backup taken first in `data/backups/2026-09-26_powercut_test/`.

**2026-09-26 afternoon, "guide me" upgrade (owner request, 8 points).**
- *Wrong apply links.* 113 rows carried another job's hyperlink (an Applied row opened another company's job). The shift was already in the pre-watcher backup, and every save copied the sheet's hyperlinks forward. Fix. `store.urls()` (jobs.url is now updated on every upsert) overrides every row's Apply link on each save. Hyperlinks in the sheet are never read back as data.
- *70+ review.* Every 70+ page was opened (`scratchpad review70`). New rules. Required languages also as "bilingual English/Mandarin is required" and "Mandarin required". Text place locks as "must reside in…" and "Location Remote - Brazil". `us_benefits_pattern` (401k, HSA, FSA mean a US hire, DV Trading). `required_certificate()` (ACAMS/ACFCS without "preferred", capped, PLAYBOOK section 5). `specialist_years()` (5+ yrs in AML, sanctions, SAR, SOC, market risk… −15). Every internship is flagged.
- *Sheet.* Status is column A, then Priority (shows "✓ Applied", "✗ Not relevant" once acted, recomputed from Score on every save), Score, Title, frozen at E2. Rows are coloured by Status with conditional formatting, so the colour follows a change live. New statuses "Offer" and "Not relevant". New column "Cover letter".
- *Today tab* (first tab, `excel._write_today`, data from `plan.build`). Headline, progress against 5 a day and 25 a week, the PLAYBOOK routine slot for this hour, the next 5 queue jobs, due follow-ups with the message, one gig, and the routine. Status edits there sync too (hidden key column X, saved status column Y).
- *Cover letters* (`jobhunter/cover.py`, `config/cover_letters.yaml`). Built for Apply Queue rows from the family opening, the family anchor fact plus the 2 facts whose triggers best match the job text (stored per job in `job_text`), an honest gap paragraph when triggered, a location line and a close. PDF plus `.txt` with form answers (PLAYBOOK section 10) and expected pay by employer type, in `output/cover_letters`. "(asked for)" when the text mentions a cover or motivation letter. Every fact is from the CVs and the letters already sent.
- *Telegram bot* (`jobhunter/tgbot.py`, `setup_telegram.bat`, task "Web3 Job Bot" registered by `schedule_job_search.ps1` once `config/telegram.yaml` exists, log `output/bot.log`). The token is typed into the setup script by the owner and never passes through a chat. Only the saved chat id is answered. Reads `data/state.json` (written by `pipeline.write_state` after every save), and taps go to the `user_actions` table. `excel.save(actions=…)` applies them and they are marked saved only once they reach the main workbook. `pipeline.sync()` rewrites the workbook without fetching right after a tap (skipped if a check holds the lock). Job alerts are cards with buttons, plus a morning plan after 09.30 and an evening check after 20.00 (`tgbot.daily_messages`).
- *Not relevant learning.* Rows marked Not relevant go to the `feedback` table, and `pipeline.apply_feedback` takes 25 points off jobs whose title words overlap 75% or more.
- Tests. 111.


**Telegram browsing (2026-09-26 evening).** `write_state` now writes every row plus `lists` (queue, remote, india, new, gigs, followups, applied, all). The bot has Remote, Browse (8 per page, callback data `L|list|page`, cards `J|key|list|page` with a Back button, status taps from a list stay in the list), Sheet (sends Web3_Jobs.xlsx), and free-text search over title, company, location and source. Cards for Applied jobs offer Interview, Rejected and Offer. state.json is about 1 MB and is cached by mtime. After changing tgbot.py, restart it with `Stop-ScheduledTask "Web3 Job Bot"; Start-ScheduledTask "Web3 Job Bot"`. Tests. 116.

**2026-09-26 night.** Power cut 17.50 to 20.09. An offline pack went to Telegram before shutdown (sheet, 4 CVs, top 14 jobs with CV, cover letter and referral). The watcher and bot came back by themselves and the catch-up of 17 sources was clean. Owner thought the bot marked a job Applied. Nothing was recorded (user_actions empty, 0 pending updates). The green "✅ Applied" button under "Open job" read like a status. Cards now print "Status New, not applied yet", the CV, cover letter and referral row sits between Open job and the status buttons, labels say "✅ Mark applied", and every status tap has an Undo (`u|key`). New 📈 Stats card (`pipeline.stats`, `role_kind`) shows per kind of role the jobs to do, applied, at interview and skipped, plus to-do by place. Tests. 118.

**Two non-crypto jobs in the top 5 (2026-09-26 late evening).** Reading the queue before applying found (1) Quick Heal "Junior Consultant" (Indeed) at 86, #2. It is a digital forensics trainer job. Crypto forensics is 1 of 11 topics, the must-haves are Cellebrite, EnCase, JTAG, malware and mobile forensics. Web3 word density did not separate it from real crypto jobs with generic titles (12.5 per 1000 words, between OpenFX 10.9 and a KoinBX support job 11.4), so the device and malware forensics stack went into `missing_skills` instead. It hits 6 gaps against `many_gaps: 4`, so it is capped at 50 with the gaps listed in Flags. No other stored job text contains those words. Trainer titles were left alone on purpose, since `blockchain/crypto/web3 trainer` are target titles in `profile.yaml`. (2) Veem, a cross-border payments company on Pantera's board, at 80 (#4) and 70, with no crypto word anywhere, because `vc_boards` set `web3_native` on every listing. Now VC board jobs carry `Job.web3_hint` instead (`sources.yaml` `web3_native: false`, `web3_hint: true`). With no job text the hint counts as web3 as before (why says "crypto VC portfolio"). The link check saves the apply page text of VC board rows to `job_text` (`verify.check_page`, `hint_sources`), `pipeline.fill_saved_texts` uses it before scoring, and text without a web3 word gives the weak bonus, the flag "Job text never mentions crypto (VC portfolio company…)" and the `weak_web3_max_score` cap (50). `verify.apply` applies the same cap at once, so the row leaves the queue without waiting for the next fetch. The two Veem page texts were saved by hand. Freelance scoring treats the hint like before. Tests. 125.

**Operating notes.** The workbook can stay open, results queue in a side file. `python -m jobhunter.watch --status` shows every source's schedule. If a site starts failing, the Health tab and `output/watch.log` say which. Do not lower `every_minutes` for Naukri, Apna, Naukri Gulf or LinkedIn (they block).

---

**Scoring pass 3 (2026-09-23), jobs that could not say yes.** A review of the first applications found the apply-now band full of jobs the owner can't get. New `scoring.out_of_reach()` caps at 45 and flags. Student-only programmes (`student_only_patterns`, e.g. ~20 "Binance Accelerator Program" rows, which say "current university students and recent graduates"), required languages in the title or a "fluent in X" clause in the text (`required_languages`, "plus/preferred" wording exempt), and place names in the title (`title_region_words`, e.g. "… New York", "Community Manager, Korea". Bare "US" left out because "US shift" is normal in India). Also. `visa_negative_patterns` stops "sponsorship is not available" counting as visa support (Deloitte US-only manager post was 79), `manager_title_penalty: -12` for non-community Manager titles (several applications had gone to such roles), and `excel._sorted` puts "not seen since … maybe closed" rows below live ones (closed Superteam bounties topped Freelance). `_region_guard` runs `out_of_reach` on titles of rows not refetched. Result. 78 unreachable rows dropped, apply-now went from 59 to 48, no Applied/Skip rows touched. Pre-change workbook copy was saved to `%TEMP%\Web3_Jobs.pre-0923.xlsx`.

**Lost Applied status on re-classification (2026-09-24).** An Applied job (All Jobs, from web3.career) was re-found on remoteok with contract wording, became `kind = freelance`, and the re-classification step popped the All Jobs copy, so it reappeared in Freelance as "New". `excel.save` now carries a non-New Status/Notes over to the copy it keeps. The row was restored to Applied by hand. Also added `explain*` to freelance task tier A drive Superteam's "Explain Market Tokenization in Your Country" research bounties scored 37 with no task match, now 87.

**Apna source (2026-09-24, owner request).** `sources/apna.py`, plain HTTP. The apna.co search page embeds each card as JSON in the Next.js payload. Job pages carry a schema.org `JobPosting` (description, datePosted). The first test (10 searches + ~150 job pages, 6 parallel, 36 s) got the home IP an HTTP 481 "Link11 access denied" on apna.co (production.apna.co, the app's API, stayed fine). The source is now sequential with 3-6 s pauses, fetches job pages only for relevant-looking titles (`detail_words`, max 30), and stops cleanly on 403/429/481. The first run found Guidehouse crypto AML roles (Chennai) and a Coinbase India support role. The latter scored 30 on title alone, so crypto company names (coinbase, binance, coindcx, …) were added to `web3_terms`. Also new. A one page CV (one page general CV, plain wording).

**Location rule hidden in the description (2026-09-24).** Wormhole's "Trading Operations Associate (Remote - US time zone)" scored 89 with location "Remote". Its last requirement bullet was "Based in the US". `out_of_reach` now also checks `desc_region_pattern` (based/located/residing in the US, UK, EU, Canada…), skipping company descriptions ("we're/team is/headquartered … based in") and texts with `global_remote_words`. `score()` ignores it when the location is already India. Wormhole row now 45 with flag "Text requires being based in the us".

**"Global remote company" is not "hires globally" (2026-09-25).** QuickNode's Technical Support Engineer (locations United States and Portugal only, form asks for US work authorization) was #1 at 87 because its text said "We are a global remote company with offices in Fort Lauderdale and Lisbon", which matched `global_remote_words: global remote` and rescued it from the region lock. Removed the company-describing phrases (`global remote`, `globally distributed`, `fully distributed`) and kept only who-can-apply wording (+ `hire anywhere`, `hiring anywhere`, `from any country`). QuickNode now 45 with the US-only flag. TRM Customer Solutions Engineer (US) and Helius Solutions Engineer (North America) also dropped out of the good bands.

**Statuses set on an older day tab were lost (2026-09-25).** The owner marked three jobs "Applied" on the 2026-09-24 tab. After midnight `save()` only merged statuses from *today's* tab, so All Jobs kept them "New". Also, LibreOffice re-saved the workbook one minute after a side file was written, so `adopt_side_files` (side must be newer) would have skipped the side file. Merged by hand (side file plus user statuses by Key, user copy kept at `%TEMP%\Web3_Jobs.user-0012.xlsx`). `save()` now collects non-New statuses from every day tab and applies them to "New" All Jobs/Freelance rows. Today's tab still overrides.

**Run review and speed-up (2026-09-25).** The 10.00 run took ~15.5 min, of which LinkedIn was 920 s (everything else done by 355 s). Each run re-downloaded the same ~120 LinkedIn descriptions and re-ran the 84-page 14-day backfill pass. Now descriptions are cached in `data/linkedin_details.sqlite` (45 days) and the cap of 120 applies only to uncached ones, so coverage of unclear titles grows each run instead of stopping at the same 120. The backfill pass runs once per `backfill_every_hours: 20` (the 10.00 run), the 18.30 run does the 24 h pass only. Last seen stays within `closed_after_days: 3`. Also. `web3.career/qa-jobs` was a 404 page (0 rows every run), now `quality-assurance-jobs` (16 rows). crypto.jobs down to 1 page (0 kept in every run, its list is mostly 2024-25 posts). New `unpaid_title_words` (volunteer, unpaid, pro bono) caps via `out_of_reach`. "Investigative Journalist (Volunteer)" was 70 in apply-now. More cities in `title_region_words` (Madrid, Amsterdam, Toronto, …). Taxbit "Forward Deployed Engineer Madrid" was 53. Backups of the three changed files in `%TEMP%` (`linkedin.py.bak`, `sources.yaml.bak`, `profile.yaml.bak`).

## 0. Phase 1, as built

**Run.** Double-click `run_jobs.bat` (or the **Web3 Job Search** desktop shortcut from `create_desktop_shortcut.ps1`). Excel opens when it finishes.
**Options.** `run_jobs.bat --only linkedin,naukri` (subset of sources), `run_jobs.bat --days 30` (look further back).
**Fresh machine.** Install Python 3.11+ and Google Chrome, then `setup.bat` (run_jobs.bat calls it automatically the first time).

| Source | How it works | Findings while building |
|---|---|---|
| LinkedIn | Direct calls to LinkedIn's logged-out endpoints (`jobs-guest/.../seeMoreJobPostings/search`), 9 grouped boolean searches (`profile.yaml → linkedin_searches`) × {India, Worldwide remote}, up to 60 results each. Descriptions are fetched only for titles that don't mention crypto (max 120) | `python-jobspy` worked but took ~45 s per search (30+ min total), so it was replaced. The guest endpoint answers in <1 s and supports OR/AND/"quotes". Stops cleanly on HTTP 429. |
| Naukri | Opens the search page in **installed Google Chrome, headless** with a normal user agent, and reads the page's own `jobapi/v3/search` JSON | Direct API calls now return `406 recaptcha required`. Playwright's bundled Chromium, and headless Chrome with its default "HeadlessChrome" user agent, both get Akamai "Access Denied". Real Chrome with a normal UA works. Naukri's keyword matching is loose, so scoring does the filtering. |
| CryptoJobsList | RSS `cryptojobslist.com/rss` (newest ~100 jobs, full descriptions) | The HTML/search pages are behind a Cloudflare challenge, even for headless Chrome. RSS ignores query params. Running daily keeps coverage complete. |
| web3.career | Generic `html` adapter, 14 category pages × 2 pages | Works. Salary shown is often web3.career's *estimate*. `qa-jobs` returns 0. |
| cryptocurrencyjobs.co | RSS `index.xml` (~75 newest) | Works. |
| Company careers | Greenhouse / Lever / Ashby public APIs, ~55 crypto companies | ~2,100 open jobs in ~20 s. Chainalysis and Chainlink use other systems (not added yet). Slugs were verified on 2026-09-16. |

**Excel layout (`output/Web3_Jobs.xlsx`).** `All Jobs` (everything ever found, with First seen / Last seen) to one tab per day, newest first (new jobs only) to `Run Log` (per source. Fetched, kept, new, errors). Sorted by Score, then Source. Status dropdown and Notes are preserved across runs (matched on hidden Key column). If the workbook is open in Excel, results go to `Web3_Jobs_<date_time>.xlsx`, and those jobs are *not* marked as seen, so the next run puts them in the main file.

**Dedupe.** Key = normalized title + company, so the same job on LinkedIn and CryptoJobsList becomes one row with "Also on". `data/seen_jobs.sqlite` remembers first-seen dates.

**Scoring.** `config/profile.yaml`, whole-word matching (`word*` = prefix). The first tuning pass on real data added an off-target title penalty (sales/marketing/design/legal/Java/Android/ML…), a no-title-match penalty, a stricter senior penalty, region-locked remote detection ("Remote - USA" to +2 and flagged), `crypto` as a whole word (not "cryptography" PKI jobs), and a hard cap of 30 for jobs with no web3 word anywhere. That cap filters out Naukri's generic BPO/support results. `min_score: 35`.

**Tuning pass 2 (2026-09-17, after the owner's first two real runs).**
- **Old postings.** Company career pages keep evergreen jobs open for years (168 jobs were posted before Jun 2026, 5 from 2022). Now −10 if older than 90 days and −20 if older than 365, with an `Old post (2022)` / `Posted N months ago` flag. All Jobs rows not re-found for 3+ days are flagged `maybe closed`.
- **Priority column.** `1 - Apply now` ≥70, `2 - Good fit` 55 to 69, `3 - Maybe` <55 (`profile.yaml → priority_bands`).
- **Developer roles.** A dev title asking ≤2 yrs gets +15 (not for senior titles). One asking ≥4 yrs gets −15. The owner's 5+ years are QA/analysis, not development. Bridge roles (solutions/integration engineer, developer support, protocol analyst, security researcher, blockchain SME/consultant/trainer) were added to the title tiers, and prototype/PoC/hackathon/AI-tools to skills.
- **Weak web3 detection.** A single passing "blockchain" in a description (common on Naukri, e.g. EY consultants, teaching jobs) no longer counts as a web3 job. A web3 word in the title or company, a web3 board, or ≥3 mentions is needed. Otherwise +5 and the score is capped at 50.
- **Naukri searches.** Naukri matches any word, so "Blockchain Analyst" returns FP&A analysts. Tested. `blockchain` is clean, `web3` is mixed, `crypto`/`cryptocurrency`/`Web 3.0` are noisy. New `naukri_searches` gives core terms several pages each, plus the owner's Analyst/Consultant/SME/Trainer/Analytics/Engineer/Professional combinations at 1 page. Blocked searches now cool down and retry with a fresh browser session. (The owner's 23.06 run lost Naukri after a few searches and still logged "ok". Warnings now appear in Run Log.)
- **LinkedIn.** Added consultant/SME/trainer, entry-level developer and bridge-role searches (12 in total).
- **Open-file detection.** Also checks the Excel `~$` owner file and LibreOffice `.~lock` file, because LibreOffice doesn't lock the xlsx.
- **Manual keywords.** `KEYWORDS.md`.

**Scheduling (2026-09-17).** Task Scheduler task `Web3 Job Search`, daily at 10.00 and 18.30, registered by `schedule_job_search.ps1` (times at the top of the file. Re-run it to change them). The task runs `run_jobs.bat` with `JOBHUNTER_SCHEDULED=1` (no Excel pop-up, no pause) in a minimised window and logs to `output/last_scheduled_run.log`. Settings. StartWhenAvailable (catches up after sleep/off), allowed on battery, one instance at a time, 1 h limit, runs only while the user is logged in. Twice daily was chosen over hourly because only ~25 new jobs appear per 12 h, and frequent runs raise Naukri/LinkedIn blocking.

**Anti-blocking (2026-09-17).**

| Site | Protection found | Real failures so far | Fix in place |
|---|---|---|---|
| Naukri | Akamai Bot Manager (`ak_bmsc`/`bm_sv`), plus search requests signed with a page-generated `nkparam` token (direct API to 406 reCAPTCHA) | 16 Sep 23.06 run. 87 jobs instead of ~900, after 3 runs in ~1.5 h | Real Chrome, headless, normal UA. **persistent profile** `data/browser_profiles/naukri` (returning-visitor cookies). Home-page warm-up. Random 3 to 6 s pauses and scrolling. On 403/406/429/"Access Denied". Back off 60 s to 120 s, clear cookies, warm up, stop after 3. HTTP 400 = skip that page, not a block. Test run. 928 jobs in 6.5 min |
| LinkedIn | Per-IP rate limit on guest endpoints (HTTP 429) | None in 3 runs | `backoff_seconds: [60, 180]` retry on 429 before stopping. Keeps partial results |
| CryptoJobsList | Cloudflare challenge on HTML/search | n/a | RSS feed (newest ~100 jobs covers several days. ~9 to 40 new per 12 h), so nothing to fix |
| All |, | Silent partial failure logged as "ok" | `runs` table in `seen_jobs.sqlite`. If a source fetches <40% of its median over the last 5 healthy runs, a ⚠ goes in the Run Log and a "PROBLEMS THIS RUN" block prints at the end. Only healthy runs update the median |

**Deliberately not done.** CAPTCHA-solving services, forging Naukri's `nkparam`, paid rotating proxies, and stealth plugins on a logged-in LinkedIn account. These are an arms race and against the sites' terms, and a LinkedIn ban can spread from a secondary account to the main one.

**Fallbacks if blocking gets worse (not built).**
1. **Job-alert emails.** Set up saved-search alerts on LinkedIn and Naukri, and the script reads them from Gmail over IMAP using an app password the owner creates. No scraping, so nothing to block. This is the most robust option.
2. **Visible browser.** Set `headless: false` for Naukri (e.g. on the spare laptop). A visible Chrome is scored as more human.
3. **Different network.** A phone hotspot for a run if the home IP's reputation stays flagged for days.

**Freelance + new sources (2026-09-17 evening).**
- **Freelance tab** with its own scoring (`profile.yaml → freelance_scoring`). Task type the owner can do, pay size, deadline (sweet spot 2 to 14 days), freshness, crowding (Superteam submission counts), region limits. `min_score: 30`. Rows whose deadline passed drop off unless Status was set.
- **Routing.** `kind = freelance` when the source says so or the title matches `freelance_words`. **No bare "contract"**, it matched "smart contract" and pulled salaried jobs in. Fixed-term salaried roles stay in All Jobs. A job re-classified between runs is removed from the wrong sheet. Jobs re-checked and rejected are removed entirely (unless Status was set).
- **Illegal-gig filter.** LaborX carries identity/KYC-rental gigs ("Need US man", "Apple and Google Developer Account Verification", "Teste no Brasil. Cadastro, depósito e saque", "Anyone in the UK Welcome"). `illegal_gig_terms` scores −60 and `main` drops them outright.
- **Rupee parsing.** "4-5.5 Lacs PA" was being read as USD. `reward_usd` now converts INR (lakh-aware) at `inr_to_usd: 90`.
- **New sources.** `telegram` (t.me/s/ web preview, no account. Laborx/DeJob_Global/web3hiring/cryptojobslist/blockchain_job, one parser per channel format, 413 posts/run), `superteam` (Superteam Earn public JSON, ~29 open bounties), `remote_boards` (Remotive, Remote OK, WeWorkRemotely, Working Nomads, filtered to crypto, 77 jobs, most duplicates of known listings).
- **Earn Platforms tab** from `config/earn_platforms.yaml`. 24 platforms scored for fit. AI-training platforms rank high because of the owner's AI evaluation background. Checked live 2026-09-17. **Rova is winding down, Wizz HQ's site is dead, Scribble DAO's domain doesn't resolve, Gitcoin is grants-only, Layer3 blocks scripts**. Carrerlift.in is an unverified aggregator. The SideShift link in that X post was a referral link.
- **remoteweb3jobs** Telegram channel posts a message type the web preview cannot render, left disabled with a note.

**Missed LinkedIn job (2026-09-19, found by the owner on his phone).** "Investment Researcher, Web3 / Digital Assets", Cequire Capital, India, posted 6 h before the 10.00 run, was never fetched. Cause. Each search read only the top 60 of a *relevance*-ranked 14-day window (8 of 12 searches hit that cap), so a fresh post sat below two weeks of older ones. Reading deeper didn't help (LinkedIn stops at ~80), and neither did `sortBy=DD` over 14 days. What worked was a **24-hour window**. Position 8. LinkedIn now runs two passes. **fresh** (`f_TPR` 24 h, `sortBy=DD`, 60 per search) + **backfill** (14 days by relevance, 30 per search). Also added a research search (`researcher / research analyst / investment research / investment analyst` × crypto/web3/tokenomics/defi) and moved crypto research titles into tier A. Verified. The job was found (70, apply now), plus 16 other jobs the morning run missed (e.g. CoinDCX Associate, Custody Operations, 84). Cost. LinkedIn ~11 to ~15 min.

**More portals (2026-09-18 evening, suggested by the owner).**
- **crypto.jobs**, added via the generic `html` source (schema.org markup. `tr.job-entry`. `html_list` now supports a `description` field). Its "3,596 jobs" are mostly 2024 posts, and sort parameters are ignored. Only page 1 to 2 has anything recent (98 of the first 100 were older than 14 days), so `pages: 2`.
- **hashtagweb3.com**, not added. `/jobs` shows the same 12 featured cards on every page, and `/rss` returns a Cloudflare worker error. Its full feed already arrives through the `web3hiring` Telegram digest (~250 jobs/run, links point to hashtagweb3.com).
- **Naukri Gulf** (`naukrigulf` source), plain HTTP times out. Uses the Naukri approach (real Chrome, own persistent profile `data/browser_profiles/naukrigulf`, reads `spapi/jobapi/search`. Page 2 = `<slug>-jobs-2`). `naukri._launch` now takes `profile_dir` so both run in parallel safely. 10 searches (`naukrigulf_searches`), ~440 jobs in ~2 min. Per-source `max_age_days: 30`. Most Gulf crypto roles are trading/sales/BD/senior and score low, which is correct.
- **Gulf visa rule.** `visa_typical_locations` (UAE, Dubai, Abu Dhabi, Saudi, Qatar, Bahrain, Oman, Kuwait…) count as visa-sponsored, because employers there sponsor the work visa for every foreign hire.
- LinkedIn and Naukri confirmed working (923 / 953 jobs in the 18.30 run). The earlier Cloudflare issue was CryptoJobsList only.

**Stranded side files (2026-09-18 evening).** The 18.30 scheduled run worked (9/9 sources, 38 new) but the workbook was open, so it saved `Web3_Jobs_2026-09-18_1841.xlsx` and nothing reached the main sheet. Now `excel.adopt_side_files()` runs at the start of every save. If the main workbook is closed and a side file is **newer** than it, the side file becomes the main workbook (old main to `.bak.xlsx`, older side files deleted), and its keys are written to `seen_jobs.sqlite` via `store.remember()` so those jobs aren't reported as "new" again. Also removed `layer 2` from `web3_terms`. Cisco's networking "Layer 2/Layer 3 switching" was being read as blockchain L2 (Software Engineer 77 to 26).

**Over-scored senior tech roles (2026-09-18, raised by the owner).** Binance "DevOps Engineer, Cloud Infra / Infra" (5+ yrs Kafka/Redis in production, 3 yrs AWS, K8s, Terraform/Ansible) scored 90 to 95. Causes. DevOps/SRE in title tier A. "5+ yrs" read as OK (true for analyst roles, not production infra). Generic skills counted while missing core stack was ignored. The dev-years rule only covered tier-C titles. LLM listed as a *positive* skill. Fixes. DevOps/SRE to tier B. `tech_role_words` applies the dev-years rule to DevOps/SRE/infra/software titles (support/solutions/QA exempt). `min_years` takes the **largest** "N+ years". `missing_skills` (Kafka, Redis, K8s, Terraform, Java, Go, Rust, RAG/vector DBs/LangChain/PyTorch…) −4 each (max −16) and listed in Flags as `Gap: …`. **4+ gaps to capped at 50**. `llm*` removed from skills. Duplicate merge now keeps the copy **with a description** (a description-less web3.career copy at 65 had been replacing Binance's own posting at 49). Result. The DevOps pair 95 to 54, a Binance "SRE" that was really an LLM/RAG engineering role 96 to 50, apply-now 69 to 56. Crypto.com India Application Support stays 76 with `Gap: java`.

**Missed morning run + stale lock (2026-09-21).** The laptop was off/asleep at 10.00 (system events show it waking at 14.06). Task Scheduler's StartWhenAvailable caught up at 14.10, and all 11 sources were fine. But a LibreOffice lock file had been left behind since the previous night with no LibreOffice process running, so `_is_open()` believed the workbook was open, and every run would have saved to side files forever. Fixes. `_is_open()` now honours a lock file only while `soffice`/`scalc`/`excel` is actually running (checked via `tasklist`) and deletes stale ones. `main.wait_for_internet()` waits up to 15 min (checks every 30 s) before searching, because runs that start right after wake or during a Wi-Fi outage would otherwise fail every source. If there's still no connection it exits with code 2 without touching the workbook.

**Global-hiring rescue too loose (2026-09-20).** A Stripe "KYB/KYC Operations Associate" in **Mexico City** scored 84 because its text listed Stripe's delivery-centre cities ("Bengaluru, India") and `global_remote_words` contained a bare `india`. Removed. The list now holds only explicit phrases (work from anywhere, hire globally, fully distributed, hiring in india, …). That job caps at 45 on the next refetch.

**Region-locked jobs (2026-09-18, raised by the owner).** 128 "Remote but X-only" and 265 "abroad on-site" jobs were in the sheet, **32 of them in the apply-now band**. Region-locked remote now scores `remote_locked_points: -20` (was +2) and both cases are capped by `region_locked_max_score: 45`, so they sit in "3 - Maybe". Escape hatch. `global_remote_words` (work from anywhere / fully distributed / hire globally / india) restores the full score. Abroad on-site keeps the +5 when visa/relocation is mentioned. Verified. "Remote - USA" 78 to 42, Warsaw on-site 79 to 45, Bengaluru 74.

Listing country words alone missed "Denver, CO" and "Estonia" (no country term in the string), so the rule is inverted. Strip the words meaning *anywhere* (`_WORK_WORDS`) from the location and treat **any remaining place name** on a remote job as a region lock. Order of checks. India/global location to plain remote to visa/relocation mentioned (+5, no cap) to text says they hire globally (full points) to region-locked (−20, cap 45). Confirmed against 10 real cases. Denver 44, Estonia 42, Remote-USA 42, plain Remote 74, Worldwide 70, "Remote - Anywhere" 72, Bengaluru 76, "Remote - USA" that says it hires globally 60, Singapore with visa sponsorship 65, Manila on-site 45.

**Country-locked bounties (2026-09-18, found by the owner).** 2 of the first 3 Superteam bounties he opened were "only open for people in Nigeria/Nepal". Superteam's **list** endpoint returns `region: null` for every listing, the real region only exists on `api/listings/details/<slug>`. The source now fetches each listing's detail (parallel, ~30 requests) and keeps only `eligible_regions: [Global, India]`. On the next run this dropped **15 of 29** listings (Ukraine×5, North America×2, Spain×2, Poland×2, Nigeria, Germany…). Plus a source-independent guard. `region_lock_patterns` in `freelance_scoring` catches "only open for people in X" / "residents of X only" wording in any gig's text and drops it unless India/Global appears in the phrase. Verified against 5 cases including a "open globally including India" false-positive check.

**Disk incident (2026-09-17 23.28).** C drive hit 0 bytes free. openpyxl writes temp files to C drive, so a save failed mid-write and left `Web3_Jobs.xlsx` corrupt (9 KB). No Status data was lost (nothing was marked yet) and the workbook was rebuilt by a full run. Now `_save_safely()` forces temp files next to the output on D drive, refuses to save under 50 MB free, writes to `.saving.tmp` then atomically replaces, and keeps `Web3_Jobs.bak.xlsx`. **C drive still needs cleaning** (Temp ~5 GB, Brave ~3.3 GB, ms-playwright 706 MB unused since Naukri uses real Chrome, pip cache 278 MB).

**Open for Phase 2 tuning.** Naukri returns ~900 jobs but only ~3% are crypto. Consider trimming broad Naukri queries. LinkedIn takes ~5 to 9 min (description fetches are the slow part. Lower `max_descriptions` to speed up).

---

## 1. What "done" looks like

1. Double-click `Run Job Search` (a desktop shortcut). It runs in 3 to 10 minutes with no other input.
2. `output/Web3_Jobs.xlsx` gets a new tab named after the date, e.g. `2026-09-16`. If you run it twice on the same day, the second run adds to that day's tab. It never makes duplicate rows.
3. Each row has. **Score, Source, Title, Company, Location, Work mode (Remote/Hybrid/Onsite), Posted date, Salary (if shown), Experience asked, Why it matched (the keywords it hit), Apply link (clickable), Status (dropdown. New/Applied/Interview/Rejected/Skip), Notes.**
4. The day tab holds **only jobs first seen that day**, so you never re-read old postings.
5. An `All Jobs` master tab collects every job ever found and keeps your Status and Notes across days. It doubles as your application tracker.
6. Adding a new job website is usually **just a few lines in `config/sources.yaml`**. It only needs a small Python file when the site is unusual.
7. If one website fails (site blocked, layout changed), the other sites still run. The failure goes in a `Run Log` tab, so a broken site never blocks the whole run.

---

## 3. Architecture

```
jobmvp-main/
├─ run_jobs.bat                 # 1-click on Windows (desktop shortcut points here)
├─ run_jobs.sh                  # (deferred) Arch Linux laptop
├─ requirements.txt             # python-jobspy, httpx, selectolax, playwright, openpyxl, pyyaml, feedparser, rapidfuzz
├─ config/
│  ├─ profile.yaml              # search keywords, locations, score weights, negative/scam words
│  └─ sources.yaml              # list of websites (enable/disable, type, params)  ← add sites here
├─ jobhunter/
│  ├─ main.py                   # orchestrates: load config → run sources in parallel → score → dedupe → excel
│  ├─ models.py                 # Job dataclass (the common shape every source returns)
│  ├─ scoring.py                # relevance score 0–100 + "why matched" + scam flag
│  ├─ dedupe.py                 # SQLite seen-jobs store (url hash + fuzzy title/company match)
│  ├─ excel.py                  # day tab, All Jobs tab, NEW view, Run Log, formatting, hyperlinks
│  └─ sources/
│     ├─ base.py                # Source interface: fetch(queries, locations) -> list[Job]
│     ├─ generic_rss.py         # any RSS/Atom feed                     (config-only)
│     ├─ generic_html.py        # any simple site via CSS selectors     (config-only)
│     ├─ generic_ats.py         # Greenhouse / Lever / Ashby / Workable company boards (config-only)
│     ├─ generic_getro.py       # VC portfolio job boards (a16z crypto, Paradigm, Solana, Polygon…)
│     ├─ linkedin.py            # public guest job search (no login)
│     ├─ naukri.py              # Naukri JSON search API, falls back to Playwright
│     ├─ jobleads.py            # Playwright with your own saved login session (see Q3)
│     └─ cryptojobslist.py
├─ data/seen_jobs.sqlite
├─ browser_profile/             # Playwright persistent profile (only if login is needed)
└─ output/Web3_Jobs.xlsx
```

**Common Job shape.** `source, title, company, location, work_mode, posted_at, salary, experience, description_snippet, url, external_id, fetched_at`

### How to add a new website (the "simple way")

Most sites are covered by a generic adapter, so you only add YAML.

```yaml
# config/sources.yaml
- name: web3.career
  type: html                      # rss | html | ats | getro | custom
  enabled: true
  url: "https://web3.career/{query}-jobs"
  item: "tr.table_row"            # CSS selector for one job card
  fields:
    title:    "h2"
    company:  "h3"
    location: "td.job-location-mobile"
    link:     "a@href"
  render_js: false                # true = use headless browser for JS-heavy sites

- name: Chainalysis
  type: ats
  ats: greenhouse
  company_slug: chainalysis       # boards-api.greenhouse.io/v1/boards/chainalysis/jobs
```

If a site needs login, cookies or unusual pagination, copy `sources/_template.py`, fill in `fetch()`, and add `type: custom, module: mysite` to the YAML. `docs/ADDING_A_SOURCE.md` will explain this in about 10 minutes of reading.

---

## 4. Per-site approach and risks

| Site | Method | Difficulty | Notes / risk |
|---|---|---|---|
| **LinkedIn** | Public guest jobs endpoint (the same one logged-out visitors see), via `python-jobspy` or a direct httpx call. Filters. Keywords × location (India, Remote, Worldwide) × past 24h/week | Medium | **Never use your logged-in account for scraping.** LinkedIn bans accounts for it, and your profile is needed for applying. Guest mode gives about 100 to 1,000 results per query and gets rate-limited, so the script uses slow polite delays. |
| **Naukri** | Naukri's internal JSON search API (what the website itself calls). Playwright headless fallback if blocked | Medium | Anti-bot changes now and then. Keep request volume low. India-heavy, so it's good for on-site Gurugram/Bangalore/Noida roles. |
| **jobleads.com** | Playwright with a persistent browser profile. **You log in yourself once** in the opened window, and the script reuses that session | Medium, High | Most details sit behind a free login. Its listings skew senior/high-salary, so relevance may be low. Worth a trial run before investing more time. |
| **cryptojobslist.com** | Plain HTTP + HTML parse (server-rendered) | Low | Needs confirmation that this is the site you meant (see Q1). |

### Recommended extra sources (free, web3-specific, usually easy)

| Source | Type | Why |
|---|---|---|
| web3.career | html | One of the biggest web3 boards. Has non-dev and India filters |
| cryptocurrencyjobs.co | rss/html | Well curated, many support/analyst/community roles |
| remote3.co | html | Remote web3 roles |
| useweb3.xyz/jobs, Wellfound (crypto tag) | html/playwright | Startups |
| **VC portfolio boards (Getro).** A16z crypto, Paradigm, Coinbase Ventures, Pantera, Multicoin, Solana, Polygon, Consensys Mesh | getro | Hundreds of legitimate web3 companies in one API each |
| **Direct company boards (Greenhouse/Lever/Ashby).** Chainalysis, TRM Labs, Elliptic, Coinbase, Kraken, Binance, OKX, Bybit, Crypto.com, Ledger, Alchemy, QuickNode, Blockdaemon, Figment, Chainlink Labs, Consensys, Polygon, CoinDCX, CoinSwitch, Mudrex, Delta Exchange, Giottus, WazirX, Hashed Emergent/India-focused | ats | Official APIs. Fast, legal, reliable, no blocking. **Chainalysis / TRM / Elliptic investigator and support roles fit your forensics background directly.** |
| Indeed India, Glassdoor, Google Jobs | via python-jobspy | Broad coverage with the "blockchain/crypto/web3" keyword filter |
| X/Twitter & Telegram job channels | later phase | High volume but noisy and scam-prone |

---

### LinkedIn, to revisit later (owner is still deciding)
Options raised by the owner, with notes to weigh when we come back to this.

| Option | Pros | Cons / risks |
|---|---|---|
| A. Public guest jobs endpoint *(current)* | No account involved, zero ban risk, simple | Rate-limited, ~1,000 results per query cap, less detail |
| B. LinkedIn jobs already indexed by Google (`site:linkedin.com/jobs/view` + keywords, or Google Jobs via jobspy) | No LinkedIn traffic at all | Index lags by hours to days. Needs a search API or careful Google scraping (Google also rate-limits and shows CAPTCHAs) |
| C. Secondary LinkedIn account + stealth browser (puppeteer-extra-plugin-stealth / undetected-chromedriver / patchright), 5 to 7 s delays | Most complete data | Against LinkedIn's User Agreement (both scraping and duplicate accounts). LinkedIn fingerprints devices, IPs and browsers, so a ban on the secondary account **can spread to your main account** if they share a machine or network. Stealth plugins break whenever LinkedIn updates. Needs ongoing maintenance |

Plan. Ship A in Phase 1 and measure how many relevant LinkedIn jobs it actually returns. Add B as a cheap supplement in Phase 2 if A is thin. Only reconsider C if A+B leave a real gap. If C is ever tried, use a separate machine/network (e.g. the spare laptop) and never your main profile. The `linkedin.py` source will expose `mode: guest | google_index | session` in `sources.yaml`, so switching doesn't need a rewrite.

