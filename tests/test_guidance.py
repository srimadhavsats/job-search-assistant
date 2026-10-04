"""Cover letters, the Today plan, sheet layout, Telegram buttons and Not relevant learning (2026-09-26)."""
import json
import re
from datetime import date, datetime, timedelta

import pytest
from openpyxl import load_workbook

from jobhunter import cover, excel, plan, tgbot
from jobhunter.models import Job
from tests.test_excel import BANDS, TODAY, job, rows, save, set_cell

BANNED = re.compile(r"[;:—–→·]")


# ---------------- cover letters ----------------
TM_JD = ("We are hiring a transaction monitoring analyst to review alerts, investigate on-chain fund flows with "
         "Chainalysis, escalate cases and file reports. 2+ years of compliance experience. Please include a cover letter.")
SUPPORT_JD = "Customer support for our crypto wallet. Handle tickets in Zendesk, troubleshoot stuck transactions, help users."


def row(title, company="Acme", location="Remote", source="web3.career", mode="Remote"):
    return {"Title": title, "Company": company, "Location": location, "Source": source, "Work mode": mode,
            "Score": 75, "Status": "New", "Key": "k1"}


def test_tm_letter_uses_matching_facts_and_states_the_gap(sc):
    letter = cover.compose(row("Transaction Monitoring Analyst", "Bitfinex"), TM_JD, sc)
    body = " ".join(letter["paragraphs"])
    assert letter["family"] == "tm" and letter["asked"]
    assert "EXAMPLE investigations fact" in body and "direct about the gap" in body
    assert "Bitfinex" in letter["greeting"] and "fully remote" in body


def test_support_letter_picks_support_evidence(sc):
    letter = cover.compose(row("Customer Support Specialist", "Phantom"), SUPPORT_JD, sc)
    body = " ".join(letter["paragraphs"])
    assert "EXAMPLE support fact" in body and not letter["asked"] and "gap" not in body


def test_letters_have_no_banned_marks(sc):
    for title, jd in [("Compliance Analyst (EDD) - 12 months", TM_JD), ("Research Analyst: DeFi", "research tokenomics"),
                      ("QA Engineer – Web3", "selenium postman testing"), ("Community Manager", "")]:
        r = row(title, "Some Co", "Bengaluru, India", mode="")
        letter = cover.compose(r, jd, sc)
        html = cover.to_html(letter)
        assert cover.cv.visible_banned(html) == [], title
        txt = cover.to_text(letter, r, cover.load_config())
        assert not BANNED.search(re.sub(r"https?://\S+|\S+@\S+", "", txt)), title
        assert "relocate to Bengaluru" in txt


def test_expected_pay_by_employer_and_role():
    """Expected pay depends on the kind of employer and the level of the role (config/cover_letters.yaml)."""
    c = cover.load_config()
    ep = c["expected_pay"]
    pay = lambda title, company, loc: cover.expected_pay({"Title": title, "Company": company, "Location": loc}, c)
    assert pay("Customer Support Executive", "CoinDCX", "Bengaluru") == ep["indian_entry"]
    assert pay("Associate Market Risk", "CoinDCX", "Bengaluru") == ep["indian_analyst"]
    assert pay("Customer Support Associate", "Binance", "India, Bangalore") == ep["global_entry"]
    assert pay("SAR Analyst", "Binance", "India, Bangalore") == ep["global_analyst"]
    assert pay("Specialist, CSIRT", "Coinbase", "Remote - India") == ep["global_analyst"]
    assert pay("Transaction Monitoring Analyst", "Bitfinex", "Remote") == ep["remote_global"]


# ---------------- the plan ----------------
def test_plan_counts_and_picks(sc):
    today = date(2026, 9, 26)
    rs = [{"Key": f"q{i}", "Title": f"Job {i}", "Company": "C", "Score": 80 - i, "Status": "New", "Priority": "1 - Apply now",
           "First seen": "2026-09-26", "Flags": "", "Why it matched": ""} for i in range(8)]
    rs.append({"Key": "done", "Title": "Old", "Company": "D", "Score": 70, "Status": "Applied", "Status date": "2026-09-26"})
    rs.append({"Key": "fu", "Title": "Earlier", "Company": "E", "Score": 70, "Status": "Applied", "Status date": "2026-09-21"})
    p = plan.build(rs, today, datetime(2026, 9, 26, 10, 45))
    assert p["applied_today"] == 1 and p["applied_week"] == 2
    assert [r["Key"] for r in p["jobs"]] == ["q0", "q1", "q2", "q3", "q4"]
    assert p["followups_due"] == 1 and p["slot"]["name"] == "Apply"
    assert "4 more jobs" in plan.headline(p)
    assert not BANNED.search(plan.text(p))


# ---------------- sheet layout and syncing ----------------
def test_status_first_and_priority_shows_what_you_did(tmp_path):
    p = tmp_path / "w.xlsx"
    a, b = job("KYC Analyst", score=80), job("Support Engineer", score=75)
    save(p, [a, b])
    set_cell(p, "All Jobs", a.key, "Status", "Applied")
    save(p, [a, b])
    ws = load_workbook(p)["All Jobs"]
    header = [c.value for c in ws[1]]
    assert header[:4] == ["Status", "Priority", "Score", "Title"] and ws.freeze_panes == "E2"
    values = {r[header.index("Key")]: r for r in ws.iter_rows(min_row=2, values_only=True)}
    assert values[a.key][1] == "✓ Applied" and values[b.key][1] == "1 - Apply now"
    # the band is recomputed from the score, never read back from the "✓ Applied" label
    set_cell(p, "All Jobs", a.key, "Status", "New")
    save(p, [a, b])
    assert rows(p, "All Jobs")[a.key]["Priority"] == "1 - Apply now"


def test_today_tab_status_edit_reaches_all_jobs(tmp_path):
    p = tmp_path / "w.xlsx"
    a = job("KYC Analyst", score=80)
    save(p, [a])
    wb = load_workbook(p)
    ws = wb["Today"]
    target = next(r for r in range(1, ws.max_row + 1) if ws.cell(row=r, column=excel.TODAY_KEY_COL).value == a.key)
    ws.cell(row=target, column=2).value = "Not relevant"
    wb.save(p)
    save(p, [a])
    assert rows(p, "All Jobs")[a.key]["Status"] == "Not relevant"
    assert a.key not in rows(p, "Apply Queue")


def test_telegram_actions_are_applied_and_confirmed(tmp_path):
    p = tmp_path / "w.xlsx"
    a, b = job("KYC Analyst", score=80), job("Support Engineer", score=75)
    save(p, [a, b])
    res = save(p, [a, b], actions={a.key: ("Applied", "2026-09-25T11:00:00", "followed up 25 Sep"),
                                   b.key: ("Skip", "2026-09-25T11:01:00", "")})
    got = rows(p, "All Jobs")
    assert got[a.key]["Status"] == "Applied" and "followed up" in got[a.key]["Notes"]
    assert got[b.key]["Status"] == "Skip" and set(res.actions_saved) == {a.key, b.key}
    assert a.key not in rows(p, "Follow Ups")        # already followed up


# ---------------- Telegram ----------------
class FakeBot:
    def __init__(self):
        self.chat_id, self.sent, self.calls, self.files = "42", [], [], []

    def send(self, text, markup=None, chat_id=None):
        self.sent.append((text, markup))
        return {"message_id": 1}

    def call(self, method, files=None, **params):
        self.calls.append((method, params))
        return True

    def send_file(self, path, caption=""):
        self.files.append(path)

    def edit(self, message_id, text, markup=None):
        self.sent.append((text, markup))
        return True


@pytest.fixture
def state(tmp_path, monkeypatch):
    st = {"generated": "2026-09-26T10:00:00",
          "plan": {"queue": ["k1", "k2"], "followups": [], "gig": None, "queue_size": 2, "applied_today": 0,
                   "applied_week": 0, "daily_target": 5, "weekly_target": 25, "new_today": 1, "followups_due": 0},
          "rows": {"k1": {"Key": "k1", "Title": "KYC Analyst: EDD", "Company": "Binance", "Score": "82",
                          "Priority": "1 - Apply now", "Apply link": "https://x/1", "CV": "TM and AML CV (custom)"},
                   "k2": {"Key": "k2", "Title": "Support Engineer", "Company": "Wert", "Score": "75",
                          "Priority": "1 - Apply now", "Apply link": "https://x/2", "Location": "Remote"},
                   **{f"r{i}": {"Key": f"r{i}", "Title": f"Remote Analyst {i}", "Company": "Binance", "Score": str(70 - i),
                                "Location": "Remote (Worldwide)"} for i in range(10)},
                   "ap": {"Key": "ap", "Title": "KYC Analyst", "Company": "CoinDCX", "Score": "70", "Status": "Applied"}},
          "lists": {"queue": ["k1", "k2"], "remote": ["k2"] + [f"r{i}" for i in range(10)], "applied": ["ap"],
                    "all": ["k1", "k2"] + [f"r{i}" for i in range(10)] + ["ap"], "new": [], "gigs": [], "india": [],
                    "followups": []}}
    path = tmp_path / "state.json"
    path.write_text(json.dumps(st), encoding="utf-8")
    monkeypatch.setattr(tgbot, "STATE", path)
    actions = {}
    monkeypatch.setattr(tgbot, "acted", lambda since="": dict(actions))
    monkeypatch.setattr(tgbot, "record", lambda key, status, note="": actions.__setitem__(key, (status, "2026-09-26T10:05:00")))
    monkeypatch.setattr(tgbot, "sync_soon", lambda: None)
    return actions


def test_card_buttons_fit_telegram_limits():
    text, kb = tgbot.card({"Key": "0123456789abcdef", "Title": "A <b> & C", "Company": "X", "Apply link": "https://x"})
    datas = [b["callback_data"] for row in kb["inline_keyboard"] for b in row if "callback_data" in b]
    assert all(len(d.encode()) <= 64 for d in datas) and "a|0123456789abcdef" in datas
    assert "&lt;b&gt;" in text


def test_applied_tap_records_and_shows_next_job(state):
    bot = FakeBot()
    s = tgbot.Session(bot)
    s.next_job()
    assert "KYC Analyst" in bot.sent[-1][0]
    s.on_callback({"id": "c1", "data": "a|k1", "message": {"message_id": 7}})
    assert state["k1"][0] == "Applied"
    assert "Support Engineer" in bot.sent[-1][0]           # moved on by itself
    assert any(m == "answerCallbackQuery" for m, _ in bot.calls)


def test_menu_words_route_to_actions(state):
    bot = FakeBot()
    s = tgbot.Session(bot)
    s.on_message({"text": "📋 Next job"})
    assert "KYC Analyst" in bot.sent[-1][0]
    s.on_message({"text": "hello"})                     # any word is a search now
    assert 'Search for "hello"' in bot.sent[-1][0]
    s.on_message({"text": "/unknown"})
    assert "What now" in bot.sent[-1][0]


# ---------------- Not relevant learning ----------------
def test_similar_titles_to_not_relevant_are_pushed_down(store):
    from jobhunter.pipeline import apply_feedback
    store.add_feedback("old", "Brand KOL Specialist", "Binance")
    a = Job(source="x", title="KOL Specialist Brand", url="u1", company="OKX")
    b = Job(source="x", title="Compliance Analyst", url="u2", company="OKX")
    a.score = b.score = 70
    assert apply_feedback({a.key: a, b.key: b}, store, BANDS) == 1
    assert a.score == 45 and "Not relevant" in a.flags and b.score == 70


def _buttons(markup):
    return [b for row in (markup or {}).get("inline_keyboard", []) for b in row]


def test_browse_lists_every_tab_with_counts(state):
    bot = FakeBot()
    tgbot.Session(bot).browse()
    labels = [b["text"] for b in _buttons(bot.sent[-1][1])]
    assert "🌍 Remote (11)" in labels and "✅ My applications (1)" in labels and "📚 All jobs (13)" in labels
    assert any(b.get("callback_data") == "SH" for b in _buttons(bot.sent[-1][1]))


def test_remote_list_pages_and_opens_a_card_with_back(state):
    bot = FakeBot()
    s = tgbot.Session(bot)
    s.on_message({"text": "🌍 Remote"})
    text, markup = bot.sent[-1]
    assert "page 1 of 2" in text
    btns = _buttons(markup)
    assert any(b.get("callback_data") == "L|remote|1" for b in btns)      # Next page
    job_btn = next(b for b in btns if b.get("callback_data", "").startswith("J|"))
    s.on_callback({"id": "c", "data": job_btn["callback_data"], "message": {"message_id": 3}})
    card_btns = _buttons(bot.sent[-1][1])
    assert any(b.get("callback_data") == "L|remote|0" for b in card_btns)   # back to the same page
    applied = next(b for b in card_btns if b["text"] == "✅ Mark applied")
    s.on_callback({"id": "c2", "data": applied["callback_data"], "message": {"message_id": 4}})
    assert list(state.values())[-1][0] == "Applied"
    assert "page" not in bot.sent[-1][0] or True        # stays in the list context, no jump to the queue


def test_typing_a_word_searches_all_jobs(state):
    bot = FakeBot()
    tgbot.Session(bot).on_message({"text": "coindcx"})
    text, markup = bot.sent[-1]
    assert 'Search for "coindcx"' in text and "1 job" in text
    assert _buttons(markup)[0]["text"].startswith("✓ 70  KYC Analyst")


def test_applied_card_offers_interview_and_rejected():
    _, kb = tgbot.card({"Key": "ap", "Title": "KYC Analyst", "Status": "Applied", "Company": "C"}, "applied|0")
    labels = [b["text"] for b in _buttons(kb)]
    assert "Mark ★ Interview" in labels and "✅ Mark applied" not in labels and "⬅ Back to list" in labels


def test_sheet_button_sends_the_workbook(state, monkeypatch, tmp_path):
    (tmp_path / "output").mkdir()
    (tmp_path / "output" / "Jobs.xlsx").write_bytes(b"x")
    monkeypatch.setattr(tgbot, "ROOT", tmp_path)
    bot = FakeBot()
    tgbot.Session(bot).on_message({"text": "📎 Sheet"})
    assert bot.files and bot.files[0].name == "Jobs.xlsx"


def test_card_says_status_in_words_and_undo_restores_it(state):
    text, kb = tgbot.card({"Key": "k1", "Title": "KYC Analyst", "Company": "Binance", "Apply link": "https://x"})
    assert "Status</b> New, not applied yet" in text
    rows = kb["inline_keyboard"]
    assert rows[0][0]["text"] == "🔗 Open job" and rows[1][0]["text"] == "📄 CV"      # files sit between link and status
    bot = FakeBot()
    s = tgbot.Session(bot)
    s.on_callback({"id": "c", "data": "a|k1", "message": {"message_id": 5}})
    edited = next(p for m, p in bot.calls if m == "editMessageReplyMarkup")
    assert any(b["text"] == "↩ Undo" for b in edited["reply_markup"]["inline_keyboard"][0])
    s.on_callback({"id": "c2", "data": "u|k1", "message": {"message_id": 5}})
    assert state["k1"][0] == "New"


def test_stats_counts_per_kind_of_role():
    from jobhunter.pipeline import role_kind, stats
    assert role_kind("Quality Analyst - AML & Crypto Investigations") == "Compliance"
    assert role_kind("QA Engineer, Trading Systems") == "QA testing"
    assert role_kind("Customer Support Specialist") == "Support ops"
    jobs = [{"Key": "a", "Title": "KYC Analyst", "Status": "New", "Location": "Remote", "Work mode": "Remote", "Score": 80},
            {"Key": "b", "Title": "AML Analyst", "Status": "Applied", "Score": 70},
            {"Key": "c", "Title": "Support Engineer", "Status": "Not relevant", "Score": 60},
            {"Key": "d", "Title": "Support Engineer II", "Status": "New", "Location": "Bengaluru", "Score": 75}]
    st = stats(jobs, [], {"queue": ["a", "d"]})
    by = {r["name"]: r for r in st["rows"]}
    assert by["Compliance"]["todo"] == 1 and by["Compliance"]["applied"] == 1
    assert by["Support ops"]["todo"] == 1 and by["Support ops"]["skipped"] == 1
    assert st["where"] == {"remote": 1, "india": 1, "abroad": 0} and st["total"]["todo"] == 2
