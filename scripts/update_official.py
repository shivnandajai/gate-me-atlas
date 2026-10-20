#!/usr/bin/env python3
"""Refresh data/official.json from the official GATE 2027 website.

Reads two public pages of https://gate2027.iitm.ac.in:
  /notifications    -> the two newest notifications
  /important_dates  -> the current schedule (struck-through, superseded dates are ignored)

Both pages are tables. Cells that span several rows (the official page uses one
'GATE 2027 Examinations' cell for three rows of exam dates) are read as part of
every row they cover.

The script never guesses. If the pages cannot be read or do not look right,
it exits with an error and leaves the previous data file untouched, so the
website keeps showing the last good information.

Usage:
  python scripts/update_official.py            # plain download (normal case)
  python scripts/update_official.py --browser  # render the pages in headless Chromium first
  python scripts/update_official.py --news-html a.html --dates-html b.html   # test with saved pages
"""
import argparse
import datetime as dt
import json
import pathlib
import re
import sys
import time
from urllib.parse import urljoin

from bs4 import BeautifulSoup

BASE = "https://gate2027.iitm.ac.in"
NEWS_URL = BASE + "/notifications"
DATES_URL = BASE + "/important_dates"
OUT = pathlib.Path(__file__).resolve().parent.parent / "data" / "official.json"
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/126.0 Safari/537.36 GATE-ME-Atlas-updater")

MONTHS = {}
for i, name in enumerate(["january", "february", "march", "april", "may", "june", "july",
                          "august", "september", "october", "november", "december"], 1):
    MONTHS[name] = i
    MONTHS[name[:3]] = i
MONTHS["sept"] = 9


# ---------------------------------------------------------------- fetching
def fetch_plain(url):
    import requests
    last = None
    for attempt in range(3):
        try:
            r = requests.get(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en"}, timeout=40)
            r.raise_for_status()
            r.encoding = r.apparent_encoding or "utf-8"
            return r.text
        except Exception as exc:  # network hiccups: wait and try again
            last = exc
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"Could not download {url}: {last}")


def fetch_browser(urls):
    from playwright.sync_api import sync_playwright
    pages = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(user_agent=USER_AGENT)
        for url in urls:
            page.goto(url, wait_until="networkidle", timeout=90000)
            pages.append(page.content())
        browser.close()
    return pages


# ---------------------------------------------------------------- helpers
ORDINAL = re.compile(r"\b(\d{1,2})\s+(st|nd|rd|th)\b", re.I)


def norm(text):
    """Collapse white space and rejoin ordinals split by <sup> tags ('14 th' -> '14th')."""
    return ORDINAL.sub(r"\1\2", " ".join((text or "").split()))


def clean_soup(html):
    """Parse HTML and drop everything a reader would not see as current text."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    for tag in soup.find_all(["del", "s", "strike"]):
        tag.decompose()
    for tag in soup.find_all(style=re.compile(r"line-through", re.I)):
        tag.decompose()
    strike_class = re.compile(r"(^|[-_ ])(strike|strikethrough|line-through|deleted|old-date)($|[-_ ])", re.I)
    for tag in soup.find_all(class_=lambda c: bool(c) and bool(strike_class.search(" ".join(c) if isinstance(c, list) else c))):
        tag.decompose()
    return soup


def parse_dates(text, default_year=None):
    """Return every calendar date mentioned in a short piece of text, in order.

    Handles '2 September 2026 (Wednesday)', '14 October to 31 October 2026',
    '15 October 2026, 10:30 AM to 16 October 2026, 10:29 AM',
    '6-7, 13-14 and 20-21 February 2027', '16-10-2026' and '2026-10-16'.
    """
    s = (text or "").replace("–", "-").replace("—", "-").replace("−", "-")
    s = re.sub(r"\([^)]*\)", " ", s)                                     # (Monday), (with late fee)
    found = []

    def keep(y, m, d):
        try:
            found.append(dt.date(y, m, d))
        except ValueError:
            pass
        return " "

    # numeric dates first, so '15.10.2026' is not mistaken for a time
    s = re.sub(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", lambda m: keep(int(m[1]), int(m[2]), int(m[3])), s)
    s = re.sub(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b", lambda m: keep(int(m[3]), int(m[2]), int(m[1])), s)
    s = re.sub(r"\b\d{1,2}[:.]\d{2}\s*(?:[ap]\.?\s?m\.?|hrs?\.?|ist)?", " ", s, flags=re.I)  # times
    s = re.sub(r"\b\d{1,2}\s*[ap]\.?m\.?(?=\W|$)", " ", s, flags=re.I)

    pending = []  # [day, month, year]
    carry = None  # month written before its day, as in 'Sept 2, 2026'
    for tok in re.findall(r"[A-Za-z]+|\d+", s):
        low = tok.lower()
        if tok.isdigit():
            n = int(tok)
            if len(tok) == 4 and 2000 <= n <= 2100:
                for p in pending:
                    if p[2] is None:
                        p[2] = n
                carry = None
            elif 1 <= n <= 31 and len(tok) <= 2:
                pending.append([n, carry, None])
        elif low.rstrip('.') in MONTHS:
            month = MONTHS[low.rstrip('.')]
            waiting = [p for p in pending if p[1] is None]
            if waiting:
                for p in waiting:
                    p[1] = month
                carry = None
            else:
                carry = month
    for d, m, y in pending:
        if m is None:
            continue
        if y is None:
            y = default_year
        if y is None:
            continue
        keep(y, m, d)
    return found


def trim_title(title, limit=220):
    title = norm(title)
    title = re.sub(r"\s*[\[(]?(read more|click here|download|view|more details)[\])]?\.?$", "", title, flags=re.I).strip()
    if len(title) <= limit:
        return title
    cut = title[:limit]
    stop = max(cut.rfind(". "), cut.rfind("; "))
    return (cut[:stop + 1] if stop > 80 else cut.rsplit(" ", 1)[0] + "…").strip()


def official_url(href, page_url):
    if not href:
        return None
    url = urljoin(page_url, href.strip())
    return url if re.match(r"^https://([a-z0-9-]+\.)*iitm\.ac\.in(/|$)", url, re.I) else None


def span(cell, attr, cap):
    try:
        return max(1, min(cap, int(str(cell.get(attr, 1)).strip() or 1)))
    except ValueError:
        return 1


def table_rows(soup):
    """Yield (tr, cells, texts) for every table row, as the row looks on screen.

    A cell with rowspan or colspan is repeated in every row and column it covers.
    The same cell object can therefore appear more than once in `cells`.
    """
    for table in soup.find_all("table"):
        spans = {}  # column -> [rows still covered, cell]
        for tr in table.find_all("tr"):
            if tr.find_parent("table") is not table:
                continue  # a nested table's rows are read with that table
            row, col = [], 0

            def take(c):
                left, cell = spans[c]
                row.append(cell)
                if left <= 1:
                    del spans[c]
                else:
                    spans[c][0] = left - 1

            for cell in tr.find_all(["td", "th"], recursive=False):
                while col in spans:
                    take(col)
                    col += 1
                rows_down, cols_across = span(cell, "rowspan", 30), span(cell, "colspan", 12)
                for _ in range(cols_across):
                    row.append(cell)
                    if rows_down > 1:
                        spans[col] = [rows_down - 1, cell]
                    col += 1
            for c in sorted(k for k in spans if k >= col):
                take(c)
            if row:
                yield tr, row, [norm(c.get_text(" ", strip=True)) for c in row]


# ---------------------------------------------------------------- notifications


def parse_news(html, page_url=NEWS_URL, today=None):
    today = today or dt.datetime.now(IST).date()
    soup = clean_soup(html)
    items = []
    for tr, cells, texts in table_rows(soup):
        date, di = None, None
        for i, t in enumerate(texts):
            if 0 < len(t) <= 40:
                ds = parse_dates(t, default_year=today.year)
                if len(ds) == 1:
                    date, di = ds[0], i
                    break
        if date is None:
            continue
        others = [i for i in range(len(cells)) if cells[i] is not cells[di] and len(texts[i]) >= 10]
        if not others:
            continue
        bi = max(others, key=lambda i: len(texts[i]))
        link = cells[bi].find("a", href=True) or tr.find("a", href=True)
        items.append({"date": date, "title": texts[bi], "url": official_url(link["href"], page_url) if link else None})

    if not items:  # fallback: list items or paragraphs that start with a date
        for el in soup.find_all(["li", "p"]):
            t = norm(el.get_text(" ", strip=True))
            m = re.match(r"^(\d{1,2}[\s./-]+[A-Za-z]{3,9}[\s./-]+\d{4}|\d{1,2}[./-]\d{1,2}[./-]\d{4})\s*[:\-–]?\s*(.{10,})$", t)
            if not m:
                continue
            ds = parse_dates(m[1])
            if len(ds) != 1:
                continue
            link = el.find("a", href=True)
            items.append({"date": ds[0], "title": m[2], "url": official_url(link["href"], page_url) if link else None})

    if not items:  # last resort: any line of text that starts with a date
        lines = [norm(x) for x in soup.get_text("\n").split("\n") if norm(x)]
        start = re.compile(r"^(\d{1,2}(?:st|nd|rd|th)?[\s./-]+[A-Za-z]{3,9}\.?[\s./-]+\d{4}|\d{1,2}[./-]\d{1,2}[./-]\d{4})")
        for i, line in enumerate(lines):
            m = start.match(line)
            if not m:
                continue
            ds = parse_dates(m[1])
            rest = line[m.end():].strip(" :-–|")
            title = rest if len(rest) >= 10 else (lines[i + 1] if i + 1 < len(lines) and not start.match(lines[i + 1]) else "")
            if len(ds) == 1 and len(title) >= 10:
                items.append({"date": ds[0], "title": title, "url": None})

    items = [x for x in items if x["date"] <= today + dt.timedelta(days=1)]
    items.sort(key=lambda x: x["date"], reverse=True)  # stable: keeps page order within a day
    out = []
    for x in items[:2]:
        out.append({"date": x["date"].isoformat(), "title": trim_title(x["title"]),
                    "url": x["url"] or NEWS_URL})
    return out


# ---------------------------------------------------------------- important dates
# Activities that happen on one day. Windows (correction, answer key, score card) keep both ends.
SINGLE = {"reg_open", "reg_close", "reg_late", "city", "admit", "result"}
LABELS = {
    "reg_open": "Online application portal (GOAPS) opened",
    "reg_close": "Regular registration closed",
    "reg_late": "Extended registration closed",
    "reg_special": "Special registration window",
    "rectify": "Application rectification window",
    "correction": "Data correction window (with fee)",
    "city": "Exam city allotment notification",
    "admit": "Admit card download",
    "exam": "GATE 2027 examinations",
    "result": "Results announced",
}


def event_key(activity):
    t = activity.lower()
    if "special" in t:
        return "reg_special"
    if "rectif" in t:
        return "rectify"
    if "correction" in t or "modification" in t:
        return "correction"
    if "regular" in t and ("clos" in t or "last date" in t or "end" in t):
        return "reg_close"
    if ("extended" in t or "late fee" in t) and ("clos" in t or "last date" in t or "end" in t or "regist" in t):
        return "reg_late"
    if ("clos" in t or "last date" in t) and ("regist" in t or "applic" in t or "goaps" in t):
        return "reg_close"
    if ("open" in t or "start" in t or "commenc" in t or "begin" in t) and ("goaps" in t or "regist" in t or "applic" in t or "portal" in t):
        return "reg_open"
    if "city" in t or "cities" in t:
        return "city"
    if "admit" in t:
        return "admit"
    if "answer key" in t or "response sheet" in t:
        return "answer_key"
    if "score" in t and "card" in t:
        return "scorecard"
    if "result" in t:
        return "result"
    if "exam" in t or "test date" in t:
        return "exam"
    return "x_" + "_".join(re.findall(r"[a-z]+", t)[:3])


DAY_WORDS = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
             "mon", "tue", "tues", "wed", "thu", "thur", "thurs", "fri", "sat", "sun",
             "to", "and", "or", "onwards", "tba"}
HEADERS = {"activity", "activities", "event", "events", "particulars", "description", "day", "days"}


def is_day_names(text):
    """True for Day-column cells such as 'Saturday Sunday' or 'Thursday to Friday'."""
    words = re.findall(r"[a-z]+", (text or "").lower())
    return bool(words) and all(w in DAY_WORDS for w in words)


def is_activity(text, year):
    return (len(re.findall(r"[A-Za-z]", text)) >= 4 and not is_day_names(text)
            and not parse_dates(text, default_year=year))


def date_cell_index(cells, texts, act_i):
    """The cell with the most dates (or 'TBA'), never the activity cell itself."""
    best, best_n = None, 0
    for i, t in enumerate(texts):
        if act_i is not None and cells[i] is cells[act_i]:
            continue
        n = len(parse_dates(t, default_year=2026))
        if re.search(r"announce|\btba\b|to be notified", t, re.I):
            n = max(n, 0.5)
        if n > best_n:
            best, best_n = i, n
    return best


def compact_when(text):
    """'15th October 2026, 10:30AM to 16th October 2026, 10:29AM' -> '15 Oct 10:30 AM to 16 Oct 10:29 AM'."""
    t = re.sub(r"\b(\d{1,2})\s*(st|nd|rd|th)\b", r"\1", norm(text), flags=re.I)
    t = re.sub(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?(?=\s|,|$)",
               lambda m: m[1].title(), t, flags=re.I)
    t = re.sub(r"\b(\d{1,2}[:.]\d{2})\s*([ap])\.?\s?m\.?", lambda m: m[1].replace(".", ":") + " " + m[2].upper() + "M", t, flags=re.I)
    t = re.sub(r",?\s*\b20\d\d\b", "", t)
    t = re.sub(r"(\d{1,2} [A-Z][a-z]{2}),\s*(?=\d)", r"\1 ", t)
    return norm(t).strip(" ,")


def parse_schedule(html, today=None):
    today = today or dt.datetime.now(IST).date()
    soup = clean_soup(html)
    merged, order, last_key = {}, [], None
    for tr, cells, texts in table_rows(soup):
        if len({id(c) for c in cells}) < 2:
            continue  # a heading or a footnote across the whole table
        act_i = next((i for i, t in enumerate(texts) if is_activity(t, today.year)), None)
        if act_i is not None:
            low = texts[act_i].lower().rstrip(" *:")
            if low in HEADERS or ("date" in low and len(low) < 15):
                continue
        di = date_cell_index(cells, texts, act_i)
        if di is None:
            continue
        if act_i is None:
            # Only dates and day names: the row continues the activity above it.
            if last_key is None:
                continue
            key, activity = last_key, merged[last_key]["activity"]
        else:
            key, activity = event_key(texts[act_i]), texts[act_i]
        date_text = texts[di]
        dates = sorted(set(parse_dates(date_text, default_year=today.year)))
        if key in SINGLE and len(dates) > 1:
            # If an old date survived as plain text, the newest one is the current one.
            dates = [dates[-1]]
        if key not in merged:
            merged[key] = {"activity": activity, "texts": [], "dates": []}
            order.append(key)
        merged[key]["texts"].append(date_text)
        merged[key]["dates"].extend(dates)
        last_key = key

    out = []
    for key in order:
        m = merged[key]
        ds = sorted(set(m["dates"]))
        start = ds[0].isoformat() if ds else None
        end = ds[-1].isoformat() if len(ds) > 1 else None
        act = m["activity"].lower()
        if key == "reg_close":
            note = "Without late fee"
        elif key == "reg_late":
            note = "With late fee"
        elif key == "rectify":
            note = "For applications with scrutiny defects" if "scrutiny" in act or "defect" in act else ""
        elif key == "reg_special":
            note = compact_when(" ".join(m["texts"])) + (", with late fee" if "late" in act else "")
        elif key == "exam":
            note = (day_runs(ds) + ". " if ds else "") + "Check the official exam schedule for the ME paper date."
        else:
            note = "" if ds else "To be announced"
        out.append({"k": key, "label": LABELS.get(key, norm(m["activity"])[:100]),
                    "start": start, "end": end, "note": note[:180]})
    return out


def day_runs(days):
    """[6,7,13,14,20,21 Feb 2027] -> '6–7, 13–14 and 20–21 Feb 2027'."""
    runs = []
    for d in days:
        if runs and (d - runs[-1][-1]).days == 1 and d.month == runs[-1][-1].month:
            runs[-1].append(d)
        else:
            runs.append([d])
    mon = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    parts = []
    for i, r in enumerate(runs):
        txt = str(r[0].day) if len(r) == 1 else f"{r[0].day}–{r[-1].day}"
        last_in_month = i == len(runs) - 1 or runs[i + 1][0].month != r[0].month
        if last_in_month:
            txt += " " + mon[r[0].month - 1]
        parts.append(txt)
    text = parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]
    return text + " " + str(days[-1].year)


# ---------------------------------------------------------------- main
def validate(news, dates):
    problems = []
    if not news:
        problems.append("no dated notifications found")
    keys = {d["k"]: d for d in dates}
    if len(dates) < 5:
        problems.append(f"only {len(dates)} schedule rows found")
    if not (keys.get("exam") and keys["exam"]["start"]):
        problems.append("examination dates not found")
    if "result" not in keys:
        problems.append("result date row not found")
    if len(dates) > 18:
        problems.append(f"{len(dates)} schedule rows found, more than the website shows")
    for d in dates:
        if is_day_names(d["label"]) or len(re.findall(r"[A-Za-z]", d["label"])) < 4:
            problems.append(f"schedule row with an odd name: {d['label']!r}")
        if d["start"] and d["end"] and d["end"] < d["start"]:
            problems.append(f"{d['label']!r} ends before it starts")
    exam, result = keys.get("exam"), keys.get("result")
    if exam and exam["start"] and not ("2026-12-01" <= exam["start"] <= "2027-03-31"):
        problems.append(f"examination start date looks wrong: {exam['start']}")
    if exam and result and exam["start"] and result["start"] and result["start"] <= (exam["end"] or exam["start"]):
        problems.append("result date is not after the examinations")
    return problems


def describe(html, limit=24):
    """Short text picture of the tables on a page, printed when a page does not look right."""
    soup = clean_soup(html)
    lines = []
    for _, cells, texts in table_rows(soup):
        lines.append(" | ".join(t[:70] for t in texts))
        if len(lines) >= limit:
            break
    return "\n".join("    " + x for x in lines) or "    (no table rows found)"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--browser", action="store_true", help="render pages in headless Chromium")
    ap.add_argument("--news-html")
    ap.add_argument("--dates-html")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    if a.news_html and a.dates_html:
        news_html = pathlib.Path(a.news_html).read_text(encoding="utf-8")
        dates_html = pathlib.Path(a.dates_html).read_text(encoding="utf-8")
    elif a.browser:
        news_html, dates_html = fetch_browser([NEWS_URL, DATES_URL])
    else:
        news_html, dates_html = fetch_plain(NEWS_URL), fetch_plain(DATES_URL)

    news = parse_news(news_html)
    dates = parse_schedule(dates_html)
    problems = validate(news, dates)
    if problems:
        print("Official pages did not look as expected: " + "; ".join(problems), file=sys.stderr)
        print("The previous data file was left unchanged.", file=sys.stderr)
        print("Notifications page as read:\n" + describe(news_html), file=sys.stderr)
        print("Important dates page as read:\n" + describe(dates_html), file=sys.stderr)
        sys.exit(1)

    data = {
        "checkedAt": dt.datetime.now(IST).replace(microsecond=0).isoformat(),
        "source": BASE + "/",
        "news": news,
        "dates": dates,
    }
    if a.dry_run:
        print(json.dumps(data, indent=1, ensure_ascii=False))
        return
    out = pathlib.Path(a.out)
    old = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    changed = {k: data[k] for k in ("news", "dates")} != {k: old.get(k) for k in ("news", "dates")}
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(("Updated" if changed else "No change in dates or news;") + " checked at " + data["checkedAt"])


if __name__ == "__main__":
    main()
