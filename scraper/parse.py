"""Parse irishracing.com results pages into plain Python dicts.

Day page:  /raceresults/Sat-16th-Oct-2021            -> list of race page paths
Race page: /raceresults/Sat-16th-Oct-2021/Ascot/1325 -> (race dict, list of runner dicts)
"""
import re
from datetime import date

from bs4 import BeautifulSoup

MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

IRISH_COURSES = {
    "ballinrobe", "bellewstown", "clonmel", "cork", "curragh", "down-royal",
    "downpatrick", "dundalk", "fairyhouse", "galway", "gowran-park",
    "kilbeggan", "killarney", "laytown", "leopardstown", "limerick",
    "listowel", "naas", "navan", "punchestown", "roscommon", "sligo",
    "thurles", "tipperary", "tramore", "wexford",
}


def ordinal(n):
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def day_slug(d: date) -> str:
    """date(2021, 10, 16) -> 'Sat-16th-Oct-2021'"""
    return f"{DAYS[d.weekday()]}-{ordinal(d.day)}-{MONTHS[d.month - 1]}-{d.year}"


def clean(s):
    if s is None:
        return None
    s = re.sub(r"\s+", " ", s.replace("\xa0", " ")).strip()
    return s or None


def to_int(s):
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


def name_country(s):
    """'Trueshan (FR)' -> ('Trueshan', 'FR'); 'Jupiter Island' -> ('Jupiter Island', None)"""
    s = clean(s) or ""
    m = re.match(r"^(.*?)\s*\(([A-Z]{2,4})\)\s*$", s)
    if m:
        return m.group(1).strip(), m.group(2)
    return s or None, None


def distance_to_yards(text):
    """'1m. 7f. 209yds.' -> 3729 ; '6f' -> 1320 ; '3m. 30yds.' -> 5310"""
    if not text:
        return None
    t = text.replace(".", " ")
    m = re.search(r"(\d+)\s*m(?![a-z])", t)
    f = re.search(r"(\d+)\s*f", t)
    y = re.search(r"(\d+)\s*y", t)
    if not (m or f or y):
        return None
    return (int(m.group(1)) * 1760 if m else 0) + \
           (int(f.group(1)) * 220 if f else 0) + \
           (int(y.group(1)) if y else 0)


def split_last_paren(s):
    """'Shao Line (FR)(General Holme (USA))' -> ('Shao Line (FR)', 'General Holme (USA)')"""
    s = (s or "").strip()
    if not s.endswith(")"):
        return s, None
    depth = 0
    for i in range(len(s) - 1, -1, -1):
        if s[i] == ")":
            depth += 1
        elif s[i] == "(":
            depth -= 1
            if depth == 0:
                inner = s[i + 1:-1]
                head = s[:i].strip()
                # a bare country code like '(GB)' alone is the dam's country, not a damsire
                if re.fullmatch(r"[A-Z]{2,4}", inner):
                    return s, None
                return head, inner
    return s, None


def frac_to_decimal(sp):
    """'7/2' -> 4.5 ; 'Evs' -> 2.0 ; '1/1' -> 2.0"""
    if not sp:
        return None
    if sp.lower().startswith("ev"):
        return 2.0
    m = re.match(r"^(\d+)/(\d+)$", sp)
    if not m or int(m.group(2)) == 0:
        return None
    return round(int(m.group(1)) / int(m.group(2)) + 1, 4)


def weight_to_lbs(w):
    m = re.match(r"^(\d+)-(\d+)$", w or "")
    return int(m.group(1)) * 14 + int(m.group(2)) if m else None


def time_to_secs(text):
    """'6m. 13.36 secs' -> 373.36 ; '58.12 secs' -> 58.12"""
    if not text:
        return None
    m = re.search(r"(?:(\d+)m\.?\s*)?(\d+(?:\.\d+)?)\s*s", text)
    if not m:
        return None
    return round((int(m.group(1)) * 60 if m.group(1) else 0) + float(m.group(2)), 2)


# ---------------------------------------------------------------- day page

def parse_day(html, d: date):
    """Return the race page paths for that date, in page order, without duplicates."""
    slug = day_slug(d)
    pat = re.compile(rf"^/raceresults/{re.escape(slug)}/[^/]+/\d{{4}}$")
    soup = BeautifulSoup(html, "html.parser")
    root = soup.find(id="racescontent") or soup
    seen, out = set(), []
    for a in root.find_all("a", href=True):
        h = a["href"].split("?")[0].split("#")[0]
        if pat.match(h) and h not in seen:
            seen.add(h)
            out.append(h)
    return out


# ---------------------------------------------------------------- race page

def _after_strong_text(node):
    """Text of siblings after a node up to the next <br> (used for owner)."""
    parts = []
    for sib in node.next_siblings:
        if getattr(sib, "name", None) in ("br", "p", "div"):
            break
        parts.append(sib.get_text(" ") if hasattr(sib, "get_text") else str(sib))
    return clean("".join(parts))


def parse_runner(div, row_index):
    r = {"row_index": row_index}
    sn = div.select_one(".sn strong")
    r["position"] = clean(sn.get_text()) if sn else None
    ex = div.select_one(".extdist strong")
    r["dist_text"] = clean(ex.get_text()) if ex else None
    silk = div.select_one("img.silk")
    r["silk"] = silk["src"] if silk else None

    run = div.select_one("div.runner")
    a = run.find("a", href=re.compile(r"^/horse/")) if run else None
    if a:
        r["horse_name"], r["horse_country"] = name_country(a.get_text())
        m = re.search(r"/(\d+)$", a["href"])
        r["horse_id"] = int(m.group(1)) if m else None
        st = a.find_next_sibling("strong")
        info = clean(st.get_text()) if st else ""
        # '5, b g 9-7'
        m = re.match(r"^(\d+),\s*(.*?)\s+(\d+-\d+)$", info or "")
        if m:
            r["age"] = int(m.group(1))
            cs = m.group(2).split()
            r["colour"] = " ".join(cs[:-1]) if len(cs) > 1 else (cs[0] if cs else None)
            r["sex"] = cs[-1] if len(cs) > 1 else None
            r["weight"] = m.group(3)
            r["weight_lbs"] = weight_to_lbs(m.group(3))
        else:
            r["age_sex_weight_raw"] = info
        own = _after_strong_text(st) if st else None
        if own and own.startswith("(") and own.endswith(")"):
            own = own[1:-1].strip()
        r["owner"] = own

    text = run.get_text(" ") if run else ""
    text_c = clean(text) or ""
    m = re.search(r"\(Drawn (\d+)\)", text_c)
    r["draw"] = int(m.group(1)) if m else None
    m = re.search(r"Rated (\d+)", text_c)
    r["official_rating"] = int(m.group(1)) if m else None
    wears = run.find("span", class_=re.compile(r"^wears(?!enq)")) if run else None
    if wears:
        sup = wears.find("sup")
        cnt = sup.get_text(strip=True) if sup else None
        r["headgear_count"] = to_int(cnt)
        if sup:
            sup.extract()
        r["headgear"] = clean(wears.get_text())
        r["headgear_desc"] = wears.get("title")
    else:
        r["headgear"] = r["headgear_count"] = r["headgear_desc"] = None
    r["stewards_mention"] = bool(run.select_one("span.wearsenq")) if run else False

    sire = run.find("a", href=re.compile(r"^/sire/")) if run else None
    if sire:
        r["sire"], r["sire_country"] = name_country(sire.get_text())
        rest = _after_strong_text(sire) or ""
        rest = rest.lstrip("- ").strip()
        # 'Shao Line (FR)(General Holme (USA))' -> dam, damsire = last top-level (...)
        dam_part, ds_part = split_last_paren(rest)
        r["dam"], r["dam_country"] = name_country(dam_part)
        r["damsire"], r["damsire_country"] = name_country(ds_part) if ds_part else (None, None)
    else:
        r["sire"] = r["sire_country"] = r["dam"] = r["dam_country"] = None
        r["damsire"] = r["damsire_country"] = None
    m = re.search(r"Breeder - (.+?)(?:\(Morning price|\(Ring price|SP \S|$)", text_c)
    r["breeder"] = clean(m.group(1)) if m else None
    m = re.search(r"\(Morning price:\s*([^)]*)\)", text_c)
    r["morning_prices"] = clean(m.group(1)) if m else None
    m = re.search(r"\(Ring price:\s*([^)]*)\)", text_c)
    r["ring_prices"] = clean(m.group(1)) if m else None
    m = re.search(r"SP\s+(Evs|\d+/\d+)\s*([a-zA-Z]*)", text_c)
    if m:
        r["sp"] = m.group(1)
        r["sp_decimal"] = frac_to_decimal(m.group(1))
        r["sp_fav"] = m.group(2) or None
    else:
        r["sp"] = r["sp_decimal"] = r["sp_fav"] = None

    tr = div.select_one(".trainer a")
    r["trainer"] = clean(tr.get_text()) if tr else None
    r["trainer_id"] = to_int(re.search(r"/(\d+)$", tr["href"]).group(1)) if tr and re.search(r"/(\d+)$", tr["href"]) else None
    jk = div.select_one(".jockey a")
    jt = clean(jk.get_text()) if jk else None
    claim = None
    if jt:
        m = re.match(r"^(.*?)\s*\((\d+)\)$", jt)
        if m:
            jt, claim = m.group(1), int(m.group(2))
    r["jockey"], r["jockey_claim"] = jt, claim
    r["jockey_id"] = to_int(re.search(r"/(\d+)$", jk["href"]).group(1)) if jk and re.search(r"/(\d+)$", jk["href"]) else None
    tote = div.select_one(".toteline")
    r["tote"] = clean(tote.get_text(" ")) if tote else None
    com = div.select_one(".rscomment")
    r["comment"] = clean(com.get_text(" ")) if com else None
    rl = div.select_one(".racelinks")
    r["saddle_cloth"] = to_int(rl.get("sn")) if rl else None
    return r


def parse_race(html, path):
    """path like /raceresults/Sat-16th-Oct-2021/Ascot/1325"""
    soup = BeautifulSoup(html, "html.parser")
    _, _, dslug, course_slug, hhmm = path.split("/")
    race = {"race_url": path, "course_slug": course_slug,
            "sched_time": f"{hhmm[:2]}:{hhmm[2:]}"}
    h1 = soup.select_one("h1.race-title")
    race["course"] = clean(h1.get_text().replace(" Result", "")) if h1 else course_slug.replace("-", " ")
    ck = course_slug.lower()
    race["is_point_to_point"] = ck.endswith("-p")
    gi = soup.select_one(".going-info")
    if gi:
        g = clean(gi.get_text(" ")) or ""
        race["going"] = clean(re.sub(r"^Going:\s*", "", g).rstrip(". "))
    else:
        race["going"] = None

    # header paragraph: '<strong>1m. 7f. 209yds. (Class 1 )</strong> 3-y-o plus<strong>10 Ran</strong><br>Name of £500,000.00 3-y-o plus'
    hdr = None
    for p in soup.find_all("p"):
        t = p.get_text(" ")
        if " Ran" in t and p.find("strong") and p.find("br"):
            hdr = p
            break
    race["distance_text"] = race["race_class"] = race["age_text"] = race["race_name"] = None
    race["runners"] = race["total_prize_text"] = race["currency"] = None
    if hdr:
        st = hdr.find_all("strong")
        dc = clean(st[0].get_text()) if st else ""
        m = re.search(r"\(Class\s*(\d+)\s*\)", dc or "")
        race["race_class"] = int(m.group(1)) if m else None
        race["distance_text"] = clean(re.sub(r"\(Class\s*\d+\s*\)", "", dc or ""))
        if st:
            race["age_text"] = clean(st[0].next_sibling) if isinstance(st[0].next_sibling, str) else None
        for s in st:
            m = re.match(r"^(\d+) Ran$", clean(s.get_text()) or "")
            if m:
                race["runners"] = int(m.group(1))
        br = hdr.find("br")
        tail = clean("".join(x.get_text() if hasattr(x, "get_text") else str(x) for x in br.next_siblings)) if br else ""
        m = re.match(r"^(.*?)\s+of\s+([£€$]|[A-Z]{3})?\s*([\d,]+(?:\.\d+)?)", tail or "")
        if m:
            race["race_name"] = m.group(1)
            race["currency"] = {"£": "GBP", "€": "EUR", "$": "USD"}.get(m.group(2), m.group(2))
            race["total_prize_text"] = m.group(3)
        else:
            race["race_name"] = tail
    race["distance_yards"] = distance_to_yards(race["distance_text"])
    if ck in IRISH_COURSES or ck.split("-")[0] in IRISH_COURSES:
        race["country"] = "IRE"
    elif race["currency"] == "GBP":
        race["country"] = "GB"
    else:
        race["country"] = None

    # prize breakdown '1st - £283,550.00, 2nd - ...'
    prizes = []
    for p in soup.find_all("p"):
        t = clean(p.get_text(" ")) or ""
        if re.match(r"^1st - ", t):
            for pos, amt in re.findall(r"(\d+)(?:st|nd|rd|th) - \D?([\d,]+(?:\.\d+)?)", t):
                prizes.append({"pos": int(pos), "amount": float(amt.replace(",", ""))})
            break
    race["prizes"] = prizes

    # footer: Off / Time / bets
    race["off_time"] = race["winning_time_text"] = race["winning_time_secs"] = race["bets_text"] = race["non_runners"] = None
    for b in soup.find_all("b"):
        if clean(b.get_text()) == "Off":
            box = b.parent
            t = clean(box.get_text(" ")) or ""
            m = re.search(r"Off\s+(\d{1,2}\.\d{2})", t)
            race["off_time"] = m.group(1) if m else None
            m = re.search(r"Time\s+(.+?)(?:\s+Tote |\s+CSF|$)", t)
            if m:
                race["winning_time_text"] = m.group(1)
                race["winning_time_secs"] = time_to_secs(m.group(1).split(",")[0])
            m = re.search(r"((?:Tote |CSF).*?)(?=\s+Non runners|\s+(?:19|20)\d\d\s|$)", t)
            race["bets_text"] = m.group(1) if m else None
            m = re.search(r"Non runners\s+(.*?)(?=\s+(?:19|20)\d\d\s|$)", t)
            race["non_runners"] = m.group(1) if m else None
            break

    runners = [parse_runner(div, i) for i, div in enumerate(soup.select("div.runner-line"))]
    return race, runners
