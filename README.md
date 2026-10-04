# Job Search Assistant

A personal job search system that Claude Code sets up on your laptop and tunes to your CV. You do not need to know coding.

**What it does**

- Checks LinkedIn, Naukri, Indeed, company career pages and other job sites every 15 minutes, all day.
- Scores every job against your CV and pushes down the ones you cannot get (wrong country, wrong level, a language you do not speak).
- Keeps everything in one Excel file. Its Today tab tells you what to do next.
- Makes a CV copy and a cover letter for each good job, plus a ready referral message.
- Alerts you about new good jobs on Windows, and on Telegram if you want.
- Never applies or messages anyone for you. You stay in control.

It was first built for crypto and web3 jobs in India. During setup Claude retunes it to your own field.

## What you need

- A Windows 10 or 11 laptop
- A Claude Pro (or higher) plan
- Your CV (PDF or Word)

## Setup in 3 steps

1. Install the Claude app from **claude.ai/download**, sign in, and open the **Code** tab.
2. Make a new empty folder (for example **JobSearch** in Documents) and put your CV in it. In the Code tab, choose this folder.
3. Copy this message into the chat and press Enter.

```
Set up the job search assistant from github.com/srimadhavsats/job-search-assistant in this folder, then follow its START_HERE.md
```

That is all. Claude installs what is missing, asks you some questions about your work and the jobs you want, and sets everything up. It takes about an hour, mostly answering questions. When Claude asks for permission to run something, allow it. Windows may also ask you to allow the Python or Chrome installer.

## Every day

- Open **output\Jobs.xlsx** in your folder and start with the **Today** tab. It shows the next jobs to apply to, with the CV and cover letter for each one.
- After you apply, set **Status** to Applied. The list moves on by itself.
- For help with a form, a referral message or what to do next, open the Code tab in the same folder and ask Claude. It remembers where you left off.

## Good to know

- Everything stays on your laptop. Your CV and your answers are not uploaded anywhere.
- New jobs are checked every 15 minutes while the laptop is on and you are signed in to Windows. If it was off, it catches up when you switch it on.
- Claude Pro has a usage limit. If you reach it, come back after it resets and type "continue".
- It only reads public job pages. It never logs in to LinkedIn or Naukri as you.

## More

- **docs/USER_GUIDE.md** explains the Excel tabs, the alerts and the Telegram bot.
- **START_HERE.md** is the setup plan Claude follows.
- **docs/CODE_NOTES.md** and **docs/BUILD_LOG.md** are for Claude, or anyone changing the code.
