# Start here (instructions for Claude)

The person who opened this folder wants this job search system set up for their own job search. They may not know coding. Keep them out of the code, explain things in simple words, talk in the language they write in (Hinglish is fine), and give them one click to run things.

This repository is a working system that was first built for a crypto job search in India. It already does the hard parts (about 20 job sources, a 24x7 watcher, scoring, an Excel tracker, a CV and cover letter per job, alerts and a Telegram bot). Your job is to set it up on this computer and retune it to this person, not to rewrite it. Read docs/CODE_NOTES.md before changing code, and the matching entry in docs/BUILD_LOG.md before undoing any rule, because most rules exist because a real job slipped through or a real run failed.

## How to work

1. Go step by step, in the order below. Finish a step before starting the next one.
2. Claude Pro has usage limits. Keep HANDOFF.md in this folder and update it after every step with what was done, what broke and what is next, with the date. A new session must be able to continue from it if this one stops.
3. Ask the person about anything that is their choice (roles, pay, places, companies). Decide technical things yourself and tell them in one line.
4. Check job sites live before relying on them. Sites change and many block scripts.
5. Run the tests after every code change (.venv\Scripts\python.exe -m pytest tests -q).

## Step 1. Get it running

1. If the code is not in this folder yet, get it from GitHub (git clone into a temporary folder and move everything here, or download and unzip the repository zip). Keep any CV the person already put here.
2. Run setup.bat. It installs Python and Google Chrome with winget if they are missing (Windows may ask the person to allow it), then creates .venv with the packages. This system is built for Windows. On a Mac or Linux the scheduling, pop up alerts and file lock need porting, so tell the person before going further.
3. Run the tests. All of them should pass.
4. Create HANDOFF.md and note that Step 1 is done.

## Step 2. Interview the person

Ask a few questions at a time, not all at once.

1. Their CV. Ask them to put it in this folder (PDF or Word) if it is not there yet. Read it fully.
2. Current or last role, company, total years, and the years in each area of work.
3. Target roles in order of preference, and roles they will not do.
4. Tools, skills, degrees and certificates.
5. Current or last CTC (fixed plus variable), expected CTC, notice period and whether it can be bought out.
6. Cities, remote or hybrid or office, relocation, abroad (only with a visa, or not at all), and shift timings.
7. Kinds of employers they want, dream companies, and companies never to show (always include their current employer).
8. Whether they are employed now (then the search is confidential), and how many hours a day they can give to it.

Save the answers in

1. Career_Facts.txt with every true fact about their work from the CV and the interview (numbers, tools, clients, results). Append only, never delete. Every CV, cover letter and form answer may only use facts from this file.
2. config/profile.yaml (see Step 3).

## Step 3. Retune it to the person

docs/CODE_NOTES.md lists everything that is crypto specific. In short

1. **config/profile.yaml.** Title tiers from their target roles, skills from their CV, missing_skills for core tools of their field that they lack, web3_terms replaced with words that mark a job in their field (this keeps unrelated jobs capped), new LinkedIn, Naukri and other search lists, and experience and certificate rules that fit their level.
2. **config/sources.yaml.** Turn off the crypto only sources. Keep the general ones that fit (LinkedIn, Naukri, Indeed, Instahyre, Foundit, Apna for entry level roles, Naukri Gulf only if they want the Gulf, remote boards only if they want remote work). Add the best sites for their field, for example iimjobs for finance and management roles, and the career pages of employers that hire for their roles. Greenhouse, Lever, Ashby, SmartRecruiters, Workable and Workday all have public job APIs, and many banks and large companies use Workday.
3. **CVs and cover letters.** Their CV as HTML in the structure of CV_Template_Example.html (one to three versions, only if their CV supports them), and config/cvs.yaml and config/cover_letters.yaml filled from Career_Facts.txt.
4. **Daily routine.** ROUTINE, DAILY_TARGET and WEEKLY_TARGET in jobhunter/plan.py, to fit their day.
5. **Tests.** Replace the crypto test cases with cases from their field as you go.

Then run a full search (run_jobs.bat), show them the top 30 jobs, and tune the scoring with them until the top of the list is jobs they would really apply to.

## Step 4. Switch on the automatic parts

1. setup_watcher.bat registers the 24x7 watcher. It checks the sites that are due every 15 minutes, runs a full search each morning after 09.30 and shows Windows pop ups for new good jobs. The laptop must be on and signed in to Windows. Nothing else has to be open.
2. Telegram bot (optional, ask first). The person runs setup_telegram.bat and pastes the token from BotFather themselves. The token must never pass through this chat, and you must never read or print config/telegram.yaml.
3. Run check_system.bat and fix anything that is not PASS.
4. Explain daily use in a few lines (Today tab, Apply Queue, the Status column, the CV and cover letter links).

## Step 5. Write their PLAYBOOK.md

1. An honest read of their profile. Their strongest roles, what they can realistically get soon and at what pay, and what may be filtering them out.
2. Ways to get hired, fastest first. For example applications from the queue, referrals from former colleagues and alumni, placement consultants in their field, a Naukri profile matched to their target roles and refreshed often, and recruiter visibility on LinkedIn.
3. A daily routine that fits their day, with targets.
4. Message templates. Referral request, reply to a recruiter, follow up, notice period answer, and why they are leaving.
5. A facts table so every form gets the same answers (title, experience, CTC, notice, locations, expected CTC per kind of employer).
6. A progress log at the bottom.

Mark setup as finished in HANDOFF.md.

## Rules that always apply

1. Never invent experience, tools, numbers or titles. If a job asks for something they have not done, say so and give the closest true example.
2. If they are employed, keep the search confidential. Never show jobs at their current employer, and never suggest a public Open to Work post (the recruiters only setting is fine).
3. Anything they will send, post or upload (CVs, cover letters, messages, form answers) must not contain semicolons, colons, em or en dashes, arrows or middots, unless they say otherwise. Many recruiters read those as AI writing.
4. Never apply or message anyone automatically. The system finds, ranks and prepares. The person reviews and sends.
5. Never log in to LinkedIn or any job site with their account for scraping. Public pages and official public APIs only. No CAPTCHA solving, paid proxies or stealth plugins.
6. Flag scams hard (fees for training or joining, Telegram only recruiters, requests for bank details or documents before an offer, companies with no website or LinkedIn page).
7. Keep personal details out of CLAUDE.md, START_HERE.md and the code. They belong in Career_Facts.txt, PLAYBOOK.md, HANDOFF.md, the CV files and the config files, which stay on this laptop.

## Every later session

1. Read PLAYBOOK.md and HANDOFF.md.
2. Ask what happened since last time (applications, replies, interviews) and log it in PLAYBOOK.md.
3. Check health quickly (Health tab, output\watch.log, .venv\Scripts\python.exe -m jobhunter.watch --status).
4. Spend the session on applying. Take the top of the Apply Queue, write the form answers, adjust the CV only with true facts, and prepare the referral messages. Do not keep adding features when the person should be applying.
