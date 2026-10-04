# User guide

How to use the job search once Claude has set it up. Everything lives in your folder. The workbook is **output\Jobs.xlsx**.

## Your day

Open either the **Today** tab of the workbook or your **Telegram bot**. Both show the same short plan, so you never have to scan the whole sheet.

1. **Today** shows what to do this hour (from your routine), your progress (applied today and this week against your targets), the next 5 jobs and the follow ups that are due.
2. For a job, click the **Apply** link, then the **CV** and **Cover letter** links to open the files made for that job. The cover letter has a .txt twin in output\cover_letters with ready form answers (experience, notice period, current CTC and expected pay for that kind of employer).
3. Click the **People** link to find someone on that team on LinkedIn, and send them the ready referral message (Apply Queue tab, or the Referral button in Telegram).
4. Set **Status** in any tab. It syncs everywhere. The row turns green, Priority shows Applied, and within 15 minutes the next job moves up.

**Statuses**

| Status | Meaning |
|---|---|
| Applied | You applied |
| Interview | They called you |
| Offer | You got an offer |
| Rejected | They said no |
| Skip | Relevant, but you are not applying |
| Not relevant | Wrong for you. Jobs with nearly the same title are pushed down from then on |

New jobs arrive by themselves. To search every site right now, double-click **run_jobs.bat**.

## The tabs

| Tab | What is in it |
|---|---|
| Today | The plan for now. Progress, this hour's task, the next 5 jobs and follow ups |
| Apply Queue | New jobs worth applying to now (score 55 or more, open to you, not closed), best first, each with its CV, a referrer search and a referral message |
| Follow Ups | Jobs you applied to 5 to 21 days ago with no answer, each with a follow up message |
| Remote Jobs | Every remote job you can do from India, best first |
| Freelance | Part time work, gigs and bounties, if any sources for them are switched on |
| All Jobs | Every relevant job ever found. This is your application tracker |
| One tab per day | The jobs first seen that day |
| Earn Platforms | Places to sign up once for paid work, if you add any in config\earn_platforms.yaml |
| Health | Each job site's last good check, result, failures in a row and next check |
| Run Log | Every check of every site for the last 14 days |

**Columns worth knowing**

- **Score** (0 to 100). Higher means a better fit. **Priority** bands are 1 Apply now (70 and up), 2 Good fit (55 to 69) and 3 Maybe.
- **CV**. The CV to send, as a link. "(custom)" means a copy was made for this job with the job's own title as the headline and a location line that fits the job. Nothing else in it changes.
- **Link check**. The apply page was opened and is Open or Closed, with the date. Pages that say you must live in, or be allowed to work in, another country are flagged and moved down.
- **Found at**. When the watcher first saw the job. Early applicants get read first.
- **Flags**. Possible scam, region locks (Remote but USA only), on site abroad with no visa mentioned, old posts, Gap (a core tool the job needs that you have not used) and "not seen since, maybe closed".

Jobs you cannot really take (remote but tied to another country, on site abroad with no visa, a required language, students only, work permit for another country) are capped at 45 so they never crowd the queue.

## The 24x7 watcher

Windows Task Scheduler runs a hidden check every 15 minutes (task **Job Search Watcher**). Each check only visits the sites that are due. Company career pages and job feeds are checked every 20 to 30 minutes, LinkedIn every hour (newest posts), and Naukri and Apna a few times a day because they block fast visitors. A new job usually reaches you within about half an hour of being posted.

- **Alerts.** A Windows pop up for each new job worth applying to, with Open job and Open CV buttons, and the same job as a Telegram card once the bot is set up. Each job alerts once.
- **Morning search.** The first check after 09.30 each day is a full search of every site. If the laptop is off then, it happens at the first check after you switch it on.
- **Starts by itself** at login, every 15 minutes, and when Wi-Fi reconnects. If the internet is down it simply tries again at the next check.
- **Long gaps.** A site not checked for 6 hours or more (laptop off, no Wi-Fi) gets a full catch up search, so posts from the gap are not missed.
- **Set up or change it.** Double-click setup_watcher.bat. The interval is at the top of schedule_job_search.ps1.
- **Workbook open.** Results wait in a side file and are merged into the main workbook, with your edits kept, on the first check after you close it.
- **A site fails.** It is retried after 15 minutes, then 30, 60 and so on up to 6 hours, and you get one alert a day if it keeps failing. See the Health tab.
- **Log.** It is in output\watch.log

## Telegram (optional)

Double-click **setup_telegram.bat**, paste the token that BotFather gave you (it stays on this laptop in config\telegram.yaml, keep that file private), then press START in your bot's chat. The bot starts by itself at every login. Only your own chat is answered.

- Buttons at the bottom of the chat for What now, Next job, Remote, Browse, Follow ups, Gigs, Progress, Sheet and Help.
- Browse lists every tab of the sheet with counts, 8 jobs a page. Tap a job for its card, and Back returns to the same page.
- Sheet sends the whole workbook as a file to open on your phone. Changes in that copy do not come back, use the buttons to mark jobs.
- Type any word (a company, a skill, a city) to search every job in the sheet.
- Every job card has Open job, Mark applied, Not relevant, Skip, CV (sends the PDF), Cover letter (PDF plus form answers) and Referral (the message to copy). Every status tap can be undone.
- New good jobs arrive as cards, a morning plan comes after the 09.30 search, and an evening check after 20.00.

## Check that everything works

Double-click **check_system.bat**. It tests every job site with a tiny search, Chrome and CV making, the workbook, disk space, the scheduled tasks, the watcher's last check and the alerts, and prints PASS, WARN or FAIL for each. It changes nothing. Add --popup to also send a test alert.

## Change what it looks for

Ask Claude in the Code tab, or edit these files yourself.

- config\profile.yaml for search words, what counts as relevant, and penalties.
- config\sources.yaml to switch sites on or off, or change how often each is checked.
- config\cvs.yaml for which CV goes with which job.
- config\cover_letters.yaml for cover letter pieces and form answers.
- config\notify.yaml for alerts.

Adding a new job site is explained in docs\ADDING_A_SOURCE.md.
