# Adding a job website

All sites live in `config/sources.yaml`. Save the file, then test just your new site.

```bash
run_jobs.bat --only "My Site Name"
```

Check the `[My Site Name] ... → N jobs` lines in the window, and the **Run Log** tab in Excel.

---

## 1. The site has an RSS feed (easiest)

Look for `/rss`, `/feed`, `/index.xml` or an RSS icon on the site.

```yaml
  - name: My Board
    type: rss
    enabled: true
    web3_native: true            # true only if the site lists nothing but crypto jobs
    url: https://example.com/jobs/rss
    company_from: title_at       # optional: "author", "title_at" ("Job at Company"), or a feed field name
    location_from: location      # optional: feed field name
```

## 2. The site is a plain list page

1. Open the jobs page in Chrome. Right-click a job title and choose **Inspect**.
2. Find the element that wraps **one whole job card** (for example `<div class="job-card">`). That is `item`.
3. Inside it, find the title, company, location and link elements.

```yaml
  - name: My Board
    type: html
    enabled: true
    web3_native: true
    base_url: https://example.com
    urls:
      - https://example.com/jobs?category=support
      - https://example.com/jobs?category=analyst
    pages: 2                     # follow ?page=2
    page_param: page
    item: div.job-card           # CSS selector of one job card
    fields:
      title: h2                  # "selector" → element text
      company: .company-name
      location: .location
      posted: time@datetime      # "selector@attribute" → attribute value
      salary: .salary
      link: a@href
```

Quick check. In the Chrome DevTools Console, `document.querySelectorAll("div.job-card").length` should equal the number of jobs you can see.
If it returns 0 but the jobs are visible, the site builds the page with JavaScript. Use option 4.

## 3. A company's own careers page

If the careers page URL contains one of these, add one line under **Company careers**, in its **companies** list.

```yaml
      Some Company:   [greenhouse, somecompany]       # boards.greenhouse.io/somecompany
      Other Co:       [lever, otherco]                # jobs.lever.co/otherco
      Third Co:       [ashby, thirdco]                # jobs.ashbyhq.com/thirdco
      Fourth Co:      [workable, fourthco]            # apply.workable.com/fourthco
      Fifth Co:       [smartrecruiters, fifthco]      # jobs.smartrecruiters.com/fifthco
      Sixth Co:       [recruitee, sixthco]            # sixthco.recruitee.com
```

In the crypto setup, a company that is not purely crypto went under **Company careers (mixed)** instead, so only
its crypto jobs scored well. Many banks and large companies use Workday, which needs a new adapter (see docs/CODE_NOTES.md).

## 3b. A VC fund's portfolio job board

Boards like jobs.dragonfly.xyz run on Getro, boards like jobs.panteracapital.com on Consider. Open the
board, view the page source and search for `"network":{"id":` (Getro) or `"board":{"id":` (Consider), then
add it under **VC job boards**.

```yaml
    getro:
      Some Fund:     [jobs.somefund.xyz, 1234]           # host, network id
    consider:
      Other Fund:    [jobs.otherfund.com, other-fund]    # host, board id
```

## 4. Anything else (JavaScript sites, logins, APIs)

Copy `jobhunter/sources/_template.py` to `jobhunter/sources/mysite.py`, fill in `fetch()`, then add it to the sources.

```yaml
  - name: My Site
    type: custom
    module: mysite
    enabled: true
```

For JavaScript-heavy or protected sites, `jobhunter/sources/naukri.py` is a working example. It opens real Chrome headlessly and reads the JSON the page loads.

## How often the watcher checks it

Add `every_minutes: 60` to the source (public APIs can be checked often, sites that block scrapers a few
times a day). Settings only for the quick watcher checks go under `watch`, for example
`watch: { pages: 1 }`. Then test the new source live without touching the workbook.

```bash
.venv\Scripts\python.exe -m jobhunter.doctor --sources --only "My Site Name"
```

## Tuning what counts as relevant

Everything is in `config/profile.yaml`, including search terms, title tiers, penalties, locations and `min_score`.
The **Why it matched** column in Excel shows which rules fired for each job, so you can see what to change.
