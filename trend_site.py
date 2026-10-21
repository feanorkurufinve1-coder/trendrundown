# -*- coding: utf-8 -*-
"""
TrendRundown — генератор сайта трендов США.
Каждые 30 минут: берёт тренды Google (США) + свежие новости по каждой теме из Google News,
копит историю и строит готовый статический сайт в папке site/.
Нужен только Python 3.11 (сертификаты certifi ставятся сами).

Запуск: двойной щелчок. Один проход — RUN_ONCE = True, работать постоянно — False.
Посмотреть результат: открыть site/index.html в Chrome.
"""

# ====== НАСТРОЙКИ ======
SITE_NAME = "TrendRundown"
SITE_URL = "https://trendrundown.com"
TAGLINE = "Why it's trending — the short version"
GA_ID = ""                 # код Google Analytics (G-XXXXXXX), когда появится
# --- Реклама Google AdSense. Пока ADSENSE_CLIENT пустой — рекламы на сайте нет. ---
ADSENSE_CLIENT = ""        # ваш код издателя из AdSense, вида "ca-pub-1234567890123456"
AD_SLOTS = {               # номера рекламных блоков (data-ad-slot) из AdSense → Реклама → По рекламным блокам
    "in_article": "",      # страница темы: после первого абзаца сводки (тип «В статье»)
    "middle": "",          # страница темы: между «Trend data» и заголовками (тип «Медийная», адаптивный)
    "multiplex": "",       # страница темы: внизу, перед «Also trending» (тип «Мультиплекс»)
    "sidebar": "",         # страница темы на компьютере: справа, прилипает (тип «Медийная», 300x600)
    "home": "",            # главная: после главного тренда и между разделами (тип «Медийная»)
}
# Полоса внизу экрана на телефоне включается в AdSense: Реклама → Автоматическая реклама → «Якорные объявления».
CONTACT_EMAIL = "hello@trendrundown.com"
GEO = "US"
RUN_ONCE = True            # True — один проход и выход; False — обновлять каждые INTERVAL_MIN минут
INTERVAL_MIN = 15           # чем раньше страница появилась, тем больше трафика из Google
HOLD_HOURS = 24             # сколько часов тема держится на главной после выхода из трендов
HALF_LIFE_H = 6             # вес темы на главной падает вдвое каждые 6 часов после выхода из трендов
MAX_NEWS_QUERIES = 25      # сколько тем за проход дополнять новостями из Google News
KEEP_DAYS = 120            # сколько дней хранить архив
AI_MODEL = "claude-haiku-5-5"   # модель для сводок
AI_PER_RUN = 15            # сколько сводок писать за проход (экономия)
ONLY_WITH_SUMMARY = True  # публиковать только темы со сводкой ИИ (защита от санкций Google за «массовый контент»)
MAX_NEW_PER_DAY = 20       # сколько новых тем в сутки (по времени США) получают сводку и попадают на сайт — самые крупные
KEY_FILE = "anthropic_key.txt"  # файл с ключом API рядом с программой; нет файла — сайт работает без сводок
BLOCK_FILE = "blocklist.txt"    # ваши запреты: по одному слову/теме на строку — такие темы не публикуются и удаляются
STRICT_SOURCES = True      # True — только проверенные издания из списка TRUSTED
# =======================

import os, sys, re, json, ssl, time, html, math, subprocess, urllib.request, urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data", "topics.json")
OUT = os.path.join(HERE, "site")
LOG = os.path.join(HERE, "site_log.txt")
NS = {"ht": "https://trends.google.com/trending/rss"}


# ---------- сеть ----------
def make_ssl():
    try:
        import certifi
    except ImportError:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "certifi"])
            import certifi
        except Exception:
            certifi = None
    return ssl.create_default_context(cafile=certifi.where()) if certifi else ssl._create_unverified_context()


CTX = make_ssl()


def ensure_pillow():
    try:
        import PIL  # noqa
        return True
    except ImportError:
        try:
            print("Устанавливаю Pillow для картинок...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "Pillow"])
            return True
        except Exception:
            return False


HAS_PIL = ensure_pillow()


def get(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": f"TrendRundownBot/1.0 ({SITE_URL}; {CONTACT_EMAIL})"})
    with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
        return r.read()


def log(msg):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S}  {msg}"
    print(line)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ---------- время США (Eastern), без внешних библиотек ----------
def _nth_sunday(year, month, n):
    d = datetime(year, month, 1)
    first = d + timedelta(days=(6 - d.weekday()) % 7)
    return first + timedelta(weeks=n - 1)


def to_et(dt_utc):
    y = dt_utc.year
    start = _nth_sunday(y, 3, 2).replace(hour=7, tzinfo=timezone.utc)    # 2:00 EST = 7:00 UTC
    end = _nth_sunday(y, 11, 1).replace(hour=6, tzinfo=timezone.utc)     # 2:00 EDT = 6:00 UTC
    dst = start <= dt_utc < end
    return dt_utc + timedelta(hours=-4 if dst else -5), ("EDT" if dst else "EST")


def fmt_et(iso, with_date=True):
    dt, z = to_et(datetime.fromisoformat(iso))
    t = dt.strftime("%I:%M %p").lstrip("0")
    return f"{dt.strftime('%b')} {dt.day}, {t} {z}" if with_date else f"{t} {z}"


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ---------- фильтр запрещённого ----------
# Темы и заголовки с такими словами не публикуются (закон + правила рекламы Google).
BLOCK_PATTERNS = [
    # взрослый контент
    r"porn", r"\bxxx\b", r"onlyfans", r"\bnudes?\b", r"\bnaked\b", r"sex ?tape", r"\bescort", r"hentai", r"\bnsfw\b", r"\bleaked (photos|video|pics)",
    # наркотики (продажа/употребление), оружие
    r"buy (weed|cocaine|meth|fentanyl|drugs)", r"how to (make|cook) (meth|drugs|bomb|explosive)", r"\bdark ?web\b", r"ghost gun", r"3d[- ]printed gun",
    # экстремизм, терроризм, призывы
    r"\bisis\b propaganda", r"jihad(i)? recruit", r"manifesto", r"\bbeheading video", r"execution video", r"shooting (video|footage|livestream)",
    # суицид и самоповреждение (как инструкции/видео)
    r"suicide (method|video|note)", r"how to (kill|hurt) (yourself|myself)", r"self[- ]harm (video|method)",
    # азартные игры и мошенничество
    r"\bcasino bonus", r"free spins", r"betting tips", r"crypto giveaway", r"\bhack(ed)? account", r"\bcheat codes? generator",
    # насилие над детьми и пр.
    r"\bminor(s)? (nude|sexual)", r"\bchild (abuse|porn)",
]
_BLOCK_RE = re.compile("|".join(BLOCK_PATTERNS), re.I)

# Проверенные издания (по названию или домену). Местные ТВ-станции США (KTLA, WUSA9 и т.п.) пропускаются по позывным.
TRUSTED = {"associated press", "ap news", "reuters", "cnn", "nbc news", "cbs news", "abc news", "fox news", "npr", "pbs",
           "the new york times", "new york times", "the washington post", "washington post", "the wall street journal",
           "wall street journal", "usa today", "los angeles times", "chicago tribune", "the boston globe", "politico",
           "the hill", "axios", "bloomberg", "cnbc", "fortune", "forbes", "business insider", "the guardian", "bbc",
           "time", "newsweek", "the atlantic", "vox", "nbc sports", "espn", "cbs sports", "yahoo sports", "yahoo news",
           "yahoo finance", "the athletic", "sports illustrated", "fox sports", "nfl.com", "nba.com", "mlb.com",
           "people", "variety", "the hollywood reporter", "deadline", "rolling stone", "billboard", "entertainment weekly",
           "e! news", "today", "good morning america", "the verge", "techcrunch", "wired", "engadget", "cnet",
           "fox weather", "the weather channel", "accuweather", "nasa", "space.com", "scientific american", "national geographic",
           "marketwatch", "barron's", "the independent", "sky news", "al jazeera english", "abc7", "nbc4", "onefootball"}
_TV_RE = re.compile(r"^(k|w)[a-z]{2,3}(-?tv|\d{1,2}|-?\d{1,2}|\s|$)", re.I)


def user_blocks():
    try:
        with open(os.path.join(HERE, BLOCK_FILE), encoding="utf-8") as f:
            return [ln.strip().lower() for ln in f if ln.strip() and not ln.startswith("#")]
    except Exception:
        return []


def bad_text(s, extra=()):
    s = s or ""
    if _BLOCK_RE.search(s):
        return True
    low = s.lower()
    return any(b in low for b in extra)


def trusted(source, url=""):
    if not STRICT_SOURCES:
        return True
    n = (source or "").strip().lower()
    if n in TRUSTED or _TV_RE.match(n):
        return True
    host = urllib.parse.urlparse(url).netloc.lower().removeprefix("www.")
    return any(host == d or host.endswith("." + d) for d in
               ("apnews.com", "reuters.com", "cnn.com", "nbcnews.com", "cbsnews.com", "abcnews.go.com", "foxnews.com", "npr.org",
                "nytimes.com", "washingtonpost.com", "wsj.com", "usatoday.com", "latimes.com", "politico.com", "thehill.com",
                "axios.com", "bloomberg.com", "cnbc.com", "espn.com", "people.com", "variety.com", "bbc.com", "theguardian.com"))


# ---------- данные ----------
def slugify(s):
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s[:70] or "topic"


SMALL = {"a", "an", "and", "as", "at", "but", "by", "for", "in", "of", "on", "or", "the", "to", "vs", "vs.", "via"}


ACRO = {"nfl", "nba", "mlb", "nhl", "ncaa", "ufc", "wwe", "fbi", "cia", "usa", "us", "uk", "ai", "ceo", "gop", "nasa", "sec",
        "irs", "tsa", "fda", "cdc", "espn", "nfc", "afc", "mls", "pga", "lpga", "doj", "ice", "tv", "mvp", "wnba", "nyc",
        "dc", "la", "nyse", "ipo", "uconn", "lsu", "ucla", "usc", "byu", "tcu", "smu", "cnn", "nbc", "abc", "cbs", "hbo",
        "psg", "losc", "aek", "psv", "az", "bvb", "rb", "ac", "fc", "sc", "afc", "uefa", "fifa", "f1", "nascar", "ufl"}


def nice_term(s):
    """'jonathan taylor' -> 'Jonathan Taylor', 'al-nassr vs neom' -> 'Al-Nassr vs Neom'."""
    out = []
    for i, w in enumerate(s.split()):
        if any(ch.isupper() for ch in w) or any(ch.isdigit() for ch in w):
            out.append(w)
        elif i > 0 and w in SMALL:
            out.append(w)
        elif w.strip(".,'") in ACRO:
            out.append(w.upper())
        else:
            out.append("-".join(x[:1].upper() + x[1:] for x in w.split("-")))
    return " ".join(out)


def term_from_titles(raw, titles):
    """Написание как в заголовках СМИ: 'psg - barcelona' -> 'PSG - Barcelona', 'aek' -> 'AEK'."""
    base = nice_term(raw).split()
    out = []
    for i, w in enumerate(raw.split()):
        if i > 0 and w.lower() in SMALL:
            out.append(w.lower()); continue
        votes = {}
        for ti in titles:
            for m in re.finditer(r"(?<![\w])" + re.escape(w) + r"(?![\w])", ti, re.I):
                v = m.group(0)
                if m.start() == 0 and v[:1].isupper() and v[1:].islower():
                    continue            # первое слово заголовка — не показатель
                votes[v] = votes.get(v, 0) + 1
        best = max(votes, key=votes.get) if votes else ""
        out.append(best if best and not best.islower() else base[i])
    return " ".join(out)


def nice_traffic(s):
    n = traffic_num(s)
    if n >= 1_000_000:
        return f"{n // 1_000_000}M+"
    if n >= 1000:
        return f"{n // 1000}K+"
    return s


def latin(s):
    """Только латиница — отсекаем иноязычные издания для американского сайта."""
    letters = [ch for ch in s if ch.isalpha()]
    return not letters or sum(1 for ch in letters if ord(ch) < 0x250) / len(letters) > 0.9


def traffic_num(s):
    m = re.match(r"([\d.,]+)\s*([KkMm]?)", (s or "").replace(",", ""))
    if not m:
        return 0
    v = float(m.group(1))
    return int(v * (1000 if m.group(2).lower() == "k" else 1_000_000 if m.group(2).lower() == "m" else 1))


def fetch_trends():
    root = ET.fromstring(get(f"https://trends.google.com/trending/rss?geo={GEO}"))
    out = []
    for it in root.iter("item"):
        term = (it.findtext("title") or "").strip()
        if not term:
            continue
        try:
            pub = parsedate_to_datetime(it.findtext("pubDate")).astimezone(timezone.utc).replace(microsecond=0).isoformat()
        except Exception:
            pub = now_iso()
        news = []
        for n in it.findall("ht:news_item", NS):
            url = (n.findtext("ht:news_item_url", namespaces=NS) or "").strip()
            if url:
                news.append({"title": (n.findtext("ht:news_item_title", namespaces=NS) or "").strip(),
                             "url": url, "source": (n.findtext("ht:news_item_source", namespaces=NS) or "").strip(),
                             "time": pub})
        out.append({"term": term, "traffic": (it.findtext("ht:approx_traffic", namespaces=NS) or "").strip(),
                    "pub": pub, "news": news})
    return out


def fetch_news(term):
    q = urllib.parse.quote(f'"{term}" when:2d')
    root = ET.fromstring(get(f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"))
    out = []
    for it in list(root.iter("item"))[:20]:
        title = (it.findtext("title") or "").strip()
        src_el = it.find("source")
        source = (src_el.text or "").strip() if src_el is not None else ""
        if source and title.endswith(" - " + source):
            title = title[: -len(" - " + source)]
        try:
            t = parsedate_to_datetime(it.findtext("pubDate")).astimezone(timezone.utc).replace(microsecond=0).isoformat()
        except Exception:
            t = now_iso()
        link = (it.findtext("link") or "").strip()
        if link and title:
            out.append({"title": title, "url": link, "source": source, "time": t})
    return out


def load_store():
    try:
        with open(DATA, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"topics": {}}


def tidy(st):
    for t in st["topics"].values():
        t.setdefault("raw", t["term"].lower())
        t["term"] = term_from_titles(t["raw"], [a["title"] for a in t["articles"]])
        t["traffic"] = [[a, b, nice_traffic(c)] for a, b, c in t["traffic"]]
        t["articles"] = [a for a in t["articles"] if latin(a["title"]) and latin(a["source"])]
    return st


def save_store(st):
    os.makedirs(os.path.dirname(DATA), exist_ok=True)
    tmp = DATA + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False)
    os.replace(tmp, DATA)


def merge_dupes(store):
    """Один и тот же сюжет под разными запросами ('Como vs Man Utd' и 'Como - Manchester United')
    склеиваем в одну страницу: меньшая тема становится псевдонимом большей."""
    topics = store["topics"]; alias = store.setdefault("alias", {})
    recent = [x for x in topics.values() if hours_since(x.get("last_seen", x["first_seen"])) <= 72]
    recent.sort(key=lambda x: (peak(x), len(x["articles"])), reverse=True)
    gone = set()
    for i, big in enumerate(recent):
        if big["slug"] in gone:
            continue
        bu = {a["url"] for a in big["articles"]}; bt = {a["title"].lower() for a in big["articles"]}
        bw = set(words(big.get("raw", big["term"]))) - SMALL
        for small in recent[i + 1:]:
            if small["slug"] in gone:
                continue
            su = {a["url"] for a in small["articles"]}; st = {a["title"].lower() for a in small["articles"]}
            sw = set(words(small.get("raw", small["term"]))) - SMALL
            if not (bw & sw):
                continue                                   # нет общего слова в запросах — разные сюжеты
            common = len(bu & su) + len(bt & st)
            bvocab = set(words(" ".join(bt))); svocab = set(words(" ".join(st)))
            same_words = (sw and sw <= bvocab) or (bw and bw <= svocab)   # слова одного запроса есть в заголовках другого
            close = abs((datetime.fromisoformat(big["first_seen"]) - datetime.fromisoformat(small["first_seen"])).total_seconds()) < 36 * 3600
            if not (common >= min(2, max(1, len(su))) or (same_words and close)):
                continue
            add_articles(big, small["articles"])
            big.setdefault("aliases", [])
            for n in [small["term"]] + small.get("aliases", []):
                if n not in big["aliases"] and n != big["term"]:
                    big["aliases"].append(n)
            big["last_seen"] = max(big.get("last_seen", ""), small.get("last_seen", ""))
            alias[small["slug"]] = big["slug"]
            for k, v in list(alias.items()):
                if v == small["slug"]:
                    alias[k] = big["slug"]
            gone.add(small["slug"])
            log(f"'{small['term']}' — тот же сюжет, что '{big['term']}': объединяю")
    for s in gone:
        topics.pop(s, None)
    cur = []
    for s in store.get("current", []):
        s = alias.get(s, s)
        if s in topics and s not in cur:
            cur.append(s)
    store["current"] = cur
    return len(gone)


def update(store):
    trends = fetch_trends()
    now = now_iso()
    topics = store["topics"]
    seen_now = []
    ub = user_blocks()
    for tr in trends:
        if bad_text(tr["term"], ub):
            log(f"тема заблокирована фильтром: {tr['term']}")
            continue
        slug = slugify(tr["term"])
        slug = store.get("alias", {}).get(slug, slug)      # уже объединённый сюжет
        t = topics.get(slug)
        if not t:
            t = topics[slug] = {"raw": tr["term"], "term": nice_term(tr["term"]), "slug": slug, "first_seen": tr["pub"], "articles": [], "traffic": [], "spikes": []}
        t["last_seen"] = now
        t["traffic"].append([now, traffic_num(tr["traffic"]), nice_traffic(tr["traffic"])])
        t["traffic"] = t["traffic"][-200:]
        day = tr["pub"][:10]
        if day not in t["spikes"]:
            t["spikes"].append(day)
        add_articles(t, tr["news"])
        seen_now.append(slug)
    for slug in seen_now:
        tt = topics[slug]
        tt["term"] = term_from_titles(tt.get("raw", tt["term"]), [a["title"] for a in tt["articles"]])
    # дополняем новостями из Google News самые свежие темы
    for slug in seen_now[:MAX_NEWS_QUERIES]:
        try:
            add_articles(topics[slug], fetch_news(topics[slug]["term"]))
            time.sleep(1.0)
        except Exception as e:
            log(f"новости по '{topics[slug]['term']}' не получены: {e}")
    # чистим старое
    cutoff = (datetime.now(timezone.utc) - timedelta(days=KEEP_DAYS)).isoformat()
    for slug in [s for s, t in topics.items() if t.get("last_seen", "") < cutoff]:
        topics.pop(slug)
    store["updated"] = now
    store["current"] = seen_now
    merge_dupes(store)
    return len(trends)


def add_articles(t, items):
    have = {a["url"] for a in t["articles"]}
    titles = {a["title"].lower() for a in t["articles"]}
    for a in items:
        if a["url"] in have or a["title"].lower() in titles:
            continue
        if not (latin(a["title"]) and latin(a["source"])):
            continue
        if bad_text(a["title"], user_blocks()) or not trusted(a["source"], a["url"]):
            continue
        t["articles"].append(a); have.add(a["url"]); titles.add(a["title"].lower())
    t["articles"].sort(key=lambda a: a["time"])
    t["articles"] = t["articles"][-60:]


# ---------- сводки ИИ: свой текст по фактам из нескольких источников ----------
CLOUD = bool(os.environ.get("GITHUB_ACTIONS"))   # программа запущена в облаке GitHub


def api_key():
    if os.environ.get("ANTHROPIC_API_KEY"):
        return os.environ["ANTHROPIC_API_KEY"].strip()
    try:
        with open(os.path.join(HERE, KEY_FILE), encoding="utf-8") as f:
            return f.read().strip()
    except Exception:
        return ""


def article_text(url):
    """Текст статьи только для чтения ИИ — не сохраняется и не публикуется."""
    if "news.google.com" in url:
        return ""
    try:
        raw = get(url, timeout=20).decode("utf-8", "ignore")
    except Exception:
        return ""
    raw = re.sub(r"(?is)<(script|style|noscript|header|footer|nav|aside)[^>]*>.*?</\1>", " ", raw)
    paras = [html.unescape(re.sub(r"<[^>]+>", " ", p)) for p in re.findall(r"(?is)<p[^>]*>(.*?)</p>", raw)]
    paras = [re.sub(r"\s+", " ", p).strip() for p in paras]
    paras = [p for p in paras if len(p) > 60]
    return " ".join(paras)[:3500]


def words(s):
    return re.findall(r"[a-z0-9']+", s.lower())


def copied(text, sources, n=8):
    """Есть ли в нашем тексте куски по n слов подряд из источников."""
    src = set()
    for s in sources:
        w = words(s)
        src.update(tuple(w[i:i + n]) for i in range(len(w) - n + 1))
    w = words(text)
    return [" ".join(g) for g in (tuple(w[i:i + n]) for i in range(len(w) - n + 1)) if g in src]


PROMPT = """You write short, original explainers for a US website that tells readers why a topic is trending on Google.

Topic people are searching for: "{term}"
Search interest: {traffic}

Below are reports from news outlets. Use them ONLY as sources of facts.
Rules:
- Write entirely in your own words and your own structure. Never copy sentences or distinctive phrasing; never reuse more than 5 words in a row from any source. Do not quote unless a quote is essential; then keep it under 10 words and name who said it.
- Combine facts from several outlets. Attribute claims that are not widely confirmed ("according to CNN", "People reported").
- Neutral, plain American English, no hype, no speculation, no opinions. If outlets disagree, say so. If something is unclear, say it is unclear.
- Never add facts that are not in the sources.
- Set "safe": false if the topic is mainly about sexual or pornographic content, nudity or leaked intimate images, graphic violence or gore videos, terrorist or extremist propaganda, instructions for weapons, drugs, self-harm or crime, hate speech, gambling promotion, scams, or naming/accusing a private person (not a public figure) or identifying a minor in a crime. Ordinary news coverage of crime, accidents, politics or deaths reported by mainstream outlets is safe.

Return ONLY JSON:
{{"safe": true or false, "safety_reason": "if not safe, why", "headline": "the concrete news that explains the searches, max 12 words — a fact, e.g. 'Barcelona beat PSG 3-1 in Paris' or 'Kickoff, TV channel and lineups for tonight's match'; never vague phrases like 'draws interest', 'trends', 'searches spike', 'ahead of'", "summary": "2 short paragraphs, 120-200 words total, separated by \\n\\n", "key_points": ["3-5 short facts"], "unknown": "one sentence on what is not known yet, or empty string"}}

SOURCES:
{sources}"""


AI_TOOL = {
    "name": "publish_explainer",
    "description": "Return the explainer for the trending topic.",
    "input_schema": {
        "type": "object",
        "properties": {
            "safe": {"type": "boolean"},
            "safety_reason": {"type": "string"},
            "headline": {"type": "string"},
            "summary": {"type": "string"},
            "key_points": {"type": "array", "items": {"type": "string"}},
            "unknown": {"type": "string"},
        },
        "required": ["safe", "headline", "summary", "key_points"],
    },
}


def ai_call(prompt, key):
    """Запрос к Claude. Ответ приходит готовыми полями через инструмент — без разбора текста."""
    body = json.dumps({"model": AI_MODEL, "max_tokens": 2000, "tools": [AI_TOOL],
                       "tool_choice": {"type": "tool", "name": AI_TOOL["name"]},
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, method="POST", headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120, context=CTX) as r:
            data = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode(errors='replace')[:300]}")
    for b in data.get("content", []):
        if b.get("type") == "tool_use" and isinstance(b.get("input"), dict):
            return b["input"]
    txt = "".join(b.get("text", "") for b in data.get("content", []))
    m = re.search(r"\{.*\}", txt, re.S)
    if m:
        return json.loads(m.group(0))
    raise RuntimeError(f"ответ без данных (stop_reason={data.get('stop_reason')}): {txt[:200]!r}")


def write_summary(t, key):
    picks, outlets = [], set()
    for a in sorted(t["articles"], key=lambda a: a["time"], reverse=True):
        if a["source"] in outlets:
            continue
        outlets.add(a["source"]); picks.append(a)
        if len(picks) >= 6:
            break
    if len(picks) < 2:
        return None
    texts, blocks = [], []
    for i, a in enumerate(picks, 1):
        body = article_text(a["url"])
        texts.append(a["title"] + " " + body)
        blocks.append(f"[{i}] {a['source']} — {a['title']}\n{body or '(headline only)'}")
    traffic = t["traffic"][-1][2] if t["traffic"] else "unknown"
    prompt = PROMPT.format(term=t["term"], traffic=traffic, sources="\n\n".join(blocks))
    for attempt in range(3):
        try:
            out = ai_call(prompt, key)
        except Exception as e:
            log(f"ИИ не ответил по '{t['term']}': {e}")
            return None
        if out.get("safe") is False:
            log(f"'{t['term']}': ИИ пометил тему как небезопасную ({out.get('safety_reason', '')}) — скрываю")
            t["blocked"] = "ai: " + str(out.get("safety_reason", ""))[:200]
            return None
        full = " ".join([out.get("headline", ""), out.get("summary", ""), " ".join(out.get("key_points", [])), out.get("unknown", "")])
        hits = copied(full, texts)
        if not hits:
            out["sources"] = [a["source"] for a in picks]
            out["made"] = now_iso(); out["n_articles"] = len(t["articles"])
            return out
        log(f"'{t['term']}': найдено совпадение с источником ({hits[0]}…), переписываю")
        bad = "; ".join(f'"{h}"' for h in hits[:5])
        prompt += (f"\n\nYour previous draft repeated these word sequences from the sources: {bad}. "
                   "Write the whole explainer again and phrase those facts differently "
                   "(change word order, use other verbs, split or merge sentences).")
    log(f"'{t['term']}': сводка не прошла проверку на заимствования — не публикую")
    return None


def summarize(store):
    key = api_key()
    if not key:
        return 0
    done = 0
    today = to_et(datetime.now(timezone.utc))[0].strftime("%Y-%m-%d")
    new_today = sum(1 for x in store["topics"].values() if x.get("ai_day") == today)
    cur = [store["topics"][s] for s in store.get("current", []) if s in store["topics"]]
    cur.sort(key=lambda x: x["traffic"][-1][1] if x["traffic"] else 0, reverse=True)   # сначала самые крупные
    for t in cur:
        if done >= AI_PER_RUN:
            break
        ai = t.get("ai")
        vague = ai and re.search(r"draws? interest|\btrend|search|ahead of|buzz|attention", ai.get("headline", ""), re.I)
        if ai and not vague and len(t["articles"]) - ai.get("n_articles", 0) < 3:
            continue
        if not ai and new_today >= MAX_NEW_PER_DAY:
            continue                     # дневной лимит новых тем исчерпан; обновлять старые можно
        res = write_summary(t, key)
        if res:
            if not ai:
                t["ai_day"] = today; new_today += 1
            t["ai"] = res; done += 1
    return done


# ---------- картинки: только свободные лицензии + своя обложка ----------
def _plain(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s or ""))).strip()


def _match(term, title):
    a = set(words(term)); b = set(words(re.sub(r"\(.*?\)", "", title)))
    return bool(b) and (b <= a or a <= b)


def wiki_image(t):
    """Фото из Википедии, только если файл на Commons под CC / Public domain."""
    q = urllib.parse.quote(t["term"])
    s = json.loads(get(f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={q}&srlimit=3&format=json"))
    for hit in s.get("query", {}).get("search", []):
        title = hit["title"]
        if not _match(t["term"], title):
            continue
        summ = json.loads(get("https://en.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(title.replace(" ", "_"))))
        thumb = (summ.get("thumbnail") or {}).get("source")
        orig = (summ.get("originalimage") or {}).get("source")
        if not thumb or not orig:
            return None
        fname = urllib.parse.unquote(orig.rsplit("/", 1)[-1])
        info = json.loads(get("https://commons.wikimedia.org/w/api.php?action=query&prop=imageinfo&iiprop=extmetadata|url"
                              f"&iiurlwidth=800&titles=File:{urllib.parse.quote(fname)}&format=json"))
        page = next(iter(info.get("query", {}).get("pages", {}).values()), {})
        if "imageinfo" not in page:
            return None          # файла нет на Commons — значит, несвободный, не берём
        ii = page["imageinfo"][0]; md = ii.get("extmetadata", {})
        lic = _plain(md.get("LicenseShortName", {}).get("value", ""))
        if not re.search(r"(?i)(^cc|creative commons|public domain|pd|cc0)", lic):
            return None
        url = ii.get("thumburl") or thumb
        os.makedirs(os.path.join(OUT, "img"), exist_ok=True)
        ext = ".png" if url.lower().endswith(".png") else ".jpg"
        fn = f"img/{t['slug']}{ext}"
        with open(os.path.join(OUT, fn), "wb") as f:
            f.write(get(url))
        return {"file": fn, "credit": _plain(md.get("Artist", {}).get("value", ""))[:80] or "Wikimedia Commons",
                "license": lic, "src": ii.get("descriptionurl", ""), "wiki": summ.get("content_urls", {}).get("desktop", {}).get("page", "")}
    return None


def _font(size, bold=True):
    from PIL import ImageFont
    for name in (["georgiab.ttf", "arialbd.ttf", "DejaVuSerif-Bold.ttf", "DejaVuSans-Bold.ttf"] if bold else ["arial.ttf", "DejaVuSans.ttf"]):
        for d in ("C:/Windows/Fonts/", "/usr/share/fonts/truetype/dejavu/", ""):
            try:
                return ImageFont.truetype(d + name, size)
            except Exception:
                pass
    return ImageFont.load_default()


def make_card(t):
    """Своя обложка 1200x630: название темы, поиски, дата. Для превью в соцсетях и для тем без фото."""
    if not HAS_PIL:
        return None
    from PIL import Image, ImageDraw
    W, H = 1200, 630
    im = Image.new("RGB", (W, H), (22, 23, 27)); d = ImageDraw.Draw(im)
    d.rectangle([0, 0, 18, H], fill=(210, 70, 31))
    d.text((70, 60), "WHY IT'S TRENDING", font=_font(30, False), fill=(255, 140, 100))
    title = t["term"]; size = 92
    while size > 40:
        f = _font(size); lines = []; cur = ""
        for w in title.split():
            test = (cur + " " + w).strip()
            if d.textlength(test, font=f) > W - 140 and cur:
                lines.append(cur); cur = w
            else:
                cur = test
        lines.append(cur)
        if len(lines) * size * 1.15 < 330:
            break
        size -= 6
    y = 130
    for ln in lines:
        d.text((70, y), ln, font=f, fill=(240, 238, 232)); y += int(size * 1.15)
    tr = t["traffic"][-1][2] if t["traffic"] else ""
    sub = (f"{tr} US searches · " if tr else "") + fmt_et(t["first_seen"])
    d.text((70, H - 120), sub, font=_font(32, False), fill=(170, 174, 182))
    d.text((70, H - 75), "Trend", font=_font(40), fill=(240, 238, 232))
    d.text((70 + d.textlength("Trend", font=_font(40)), H - 75), "Rundown", font=_font(40), fill=(255, 122, 77))
    os.makedirs(os.path.join(OUT, "img"), exist_ok=True)
    fn = f"img/card-{t['slug']}.png"
    im.save(os.path.join(OUT, fn), optimize=True)
    return fn


def images(store):
    n = 0
    for slug in store.get("current", []):
        t = store["topics"].get(slug)
        if not t:
            continue
        if not t.get("img_tried"):
            t["img_tried"] = True
            try:
                img = wiki_image(t)
                if img:
                    t["img"] = img; n += 1
            except Exception as e:
                log(f"фото для '{t['term']}' не найдено: {e}")
        try:
            t["card"] = make_card(t)
        except Exception as e:
            log(f"обложка для '{t['term']}' не сделана: {e}")
    return n


# ---------- сайт ----------
E = html.escape
CSS = """
:root{--bg:#fbfaf7;--fg:#1d1f23;--muted:#62666e;--line:#e4e1da;--card:#ffffff;--accent:#d2461f;--chip:#f1eee7}
@media (prefers-color-scheme:dark){:root{--bg:#131417;--fg:#e8e6e1;--muted:#9a9ea6;--line:#2a2c31;--card:#1a1c20;--accent:#ff7a4d;--chip:#23252a}}
*{box-sizing:border-box}html,body{background:var(--bg);color:var(--fg)}
body{margin:0;font:16px/1.55 Georgia,"Times New Roman",serif}
a{color:inherit}a:hover{color:var(--accent)}
.wrap{max-width:860px;margin:0 auto;padding:18px max(16px,env(safe-area-inset-left)) 48px max(16px,env(safe-area-inset-right))}
header.top{display:flex;justify-content:space-between;align-items:baseline;gap:12px;flex-wrap:wrap;border-bottom:2px solid var(--fg);padding-bottom:10px;margin-bottom:18px}
.brand{font:700 26px/1 "Helvetica Neue",Arial,sans-serif;letter-spacing:-.02em;text-decoration:none}
.brand span{color:var(--accent)}
.tag,.meta,nav,.small{font-family:"Helvetica Neue",Arial,sans-serif}
.tag{color:var(--muted);font-size:13px}
nav a{font-size:14px;margin-left:14px;text-decoration:none}
h1{font-size:34px;line-height:1.15;margin:6px 0 10px;text-wrap:balance}
h2{font:700 13px "Helvetica Neue",Arial,sans-serif;text-transform:uppercase;letter-spacing:.08em;color:var(--muted);margin:30px 0 10px}
.meta{color:var(--muted);font-size:13px}
.box{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--accent);padding:14px 16px;border-radius:4px}
.list{list-style:none;padding:0;margin:0}
.list li{padding:10px 0;border-bottom:1px solid var(--line)}
.list .src{font:600 12px "Helvetica Neue",Arial,sans-serif;text-transform:uppercase;letter-spacing:.05em;color:var(--accent)}
.list .t{display:block;font-size:17px;line-height:1.35;text-decoration:none;margin:2px 0}
.trend{display:grid;grid-template-columns:44px 1fr;gap:10px;padding:12px 0;border-bottom:1px solid var(--line)}
.rank{font:700 22px "Helvetica Neue",Arial,sans-serif;color:var(--accent);text-align:right}
.trend a.name{font-size:21px;font-weight:700;text-decoration:none;line-height:1.2}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{background:var(--chip);border-radius:20px;padding:3px 10px;font:13px "Helvetica Neue",Arial,sans-serif;text-decoration:none}
footer{margin-top:40px;padding-top:14px;border-top:1px solid var(--line);color:var(--muted);font:13px "Helvetica Neue",Arial,sans-serif}
footer a{margin-right:14px}
svg.spark{display:block;max-width:100%}
figure.hero{margin:6px 0 16px}figure.hero img{width:100%;max-height:440px;object-fit:cover;border-radius:4px;display:block;background:var(--chip)}
figure.hero figcaption{font:12px "Helvetica Neue",Arial,sans-serif;color:var(--muted);margin-top:5px}
.wrap{max-width:1040px}
h1.front{font-size:22px;font-family:"Helvetica Neue",Arial,sans-serif;text-transform:uppercase;letter-spacing:.06em;margin:4px 0 16px}
.lead{display:grid;gap:18px;text-decoration:none;background:var(--card);border:1px solid var(--line);border-radius:6px;padding:22px 24px;margin-bottom:18px}
.lead.has-img{grid-template-columns:minmax(0,1.1fr) minmax(0,1fr)}
.lead img{width:100%;height:100%;max-height:300px;object-fit:cover;border-radius:4px}
.lead-term{font:700 44px/1.05 Georgia,serif;letter-spacing:-.01em;text-transform:none;color:var(--fg);margin:10px 0 8px}
.lead-head{font-size:19px;line-height:1.4;margin:0 0 10px}
.lead:hover .lead-term,.card:hover h3{color:var(--accent)}
.badge,.chip-s{display:inline-block;font:700 12px "Helvetica Neue",Arial,sans-serif;letter-spacing:.04em;color:#fff;background:var(--accent);border-radius:3px;padding:3px 8px}
.chip-s{white-space:nowrap;background:var(--chip);color:var(--fg);font-weight:600}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:14px}
.card{display:flex;flex-direction:column;gap:6px;text-decoration:none;background:var(--card);border:1px solid var(--line);border-top:3px solid var(--accent);border-radius:6px;padding:14px 16px;min-width:0}
.card img{width:calc(100% + 32px);margin:-14px -16px 6px;height:150px;object-fit:cover;border-radius:3px 3px 0 0;max-width:none}
.card-top{display:flex;justify-content:space-between;align-items:center}
.num{font:700 15px "Helvetica Neue",Arial,sans-serif;color:var(--accent)}
.card h3{font:700 22px/1.15 Georgia,serif;margin:0;overflow-wrap:anywhere}
.card .head{margin:0;font-size:15px;line-height:1.4;display:-webkit-box;-webkit-line-clamp:3;-webkit-box-orient:vertical;overflow:hidden}
.card .meta{margin-top:auto}
.ad{margin:30px 0;padding:10px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line);text-align:center;min-height:120px}
.ad-l{font:11px "Helvetica Neue",Arial,sans-serif;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin-bottom:6px}
.tp{display:block}.tp article{max-width:720px}.tp aside{display:none}
@media (min-width:1060px){.tp.side{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:40px}.tp.side aside{display:block}
.tp aside .ad{position:sticky;top:16px;margin:0;border:0;padding:0}}
h2.sec{font:700 15px "Helvetica Neue",Arial,sans-serif;text-transform:uppercase;letter-spacing:.06em;margin:30px 0 12px;padding-top:14px;border-top:2px solid var(--fg)}
@media (max-width:640px){.lead.has-img{grid-template-columns:1fr}.lead-term{font-size:32px}}
"""


def ga_snippet():
    if not GA_ID:
        return ""
    return (f'<script async src="https://www.googletagmanager.com/gtag/js?id={E(GA_ID)}"></script>'
            f"<script>window.dataLayer=window.dataLayer||[];function gtag(){{dataLayer.push(arguments);}}"
            f"gtag('js',new Date());gtag('config','{E(GA_ID)}');</script>")


def ad(kind):
    """Рекламный блок. Пустая строка, пока не вписаны ADSENSE_CLIENT и номер блока."""
    slot = AD_SLOTS.get(kind, "")
    if not ADSENSE_CLIENT or not slot:
        return ""
    attrs = {"in_article": 'style="display:block;text-align:center" data-ad-layout="in-article" data-ad-format="fluid"',
             "multiplex": 'style="display:block" data-ad-format="autorelaxed"',
             "sidebar": 'style="display:inline-block;width:300px;height:600px"'}.get(
        kind, 'style="display:block" data-ad-format="auto" data-full-width-responsive="true"')
    return (f'<div class="ad ad-{kind}"><div class="ad-l">Advertisement</div>'
            f'<ins class="adsbygoogle" {attrs} data-ad-client="{E(ADSENSE_CLIENT)}" data-ad-slot="{E(slot)}"></ins>'
            f'<script>(adsbygoogle=window.adsbygoogle||[]).push({{}});</script></div>')


def ads_head():
    if not ADSENSE_CLIENT:
        return ""
    return (f'<script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={E(ADSENSE_CLIENT)}" '
            f'crossorigin="anonymous"></script>')


NO_ADS = {"about.html", "privacy.html", "contact.html", "404.html"}


def page(title, desc, body, path, depth, extra_head="", og_img=""):
    up = "../" * depth
    canon = SITE_URL + "/" + path.replace("index.html", "").replace(".html", "")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{E(title)}</title><meta name="description" content="{E(desc)}">
<link rel="canonical" href="{E(canon)}"><link rel="alternate" type="application/rss+xml" title="{SITE_NAME}" href="{up}feed.xml">
{f'<meta property="og:image" content="{E(SITE_URL + "/" + og_img)}"><meta name="twitter:card" content="summary_large_image">' if og_img else ''}<meta property="og:title" content="{E(title)}"><meta property="og:description" content="{E(desc)}"><meta property="og:type" content="website">
<style>{CSS}</style>{ga_snippet()}{"" if path in NO_ADS else ads_head()}{extra_head}</head><body><div class="wrap">
<header class="top"><a class="brand" href="{up}index.html">Trend<span>Rundown</span></a>
<nav><a href="{up}index.html">Trending now</a><a href="{up}archive.html">Archive</a><a href="{up}about.html">About</a></nav></header>
{body}
<footer><a href="{up}about.html">About</a><a href="{up}privacy.html">Privacy</a><a href="{up}contact.html">Contact</a>
<p>{SITE_NAME} tracks what Americans are searching for and links to the outlets covering it. Headlines belong to their publishers; every link goes to the original source.</p></footer>
</div></body></html>"""


def spark(points, w=320, h=48):
    vals = [p[1] for p in points if p[1]]
    if len(vals) < 2:
        return ""
    mx = max(vals); n = len(vals)
    pts = " ".join(f"{i * (w - 4) / (n - 1) + 2:.1f},{h - 4 - (v / mx) * (h - 10):.1f}" for i, v in enumerate(vals))
    return (f'<svg class="spark" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="Search interest over time">'
            f'<polyline points="{pts}" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/></svg>')


def topic_summary(t):
    arts = t["articles"]
    srcs = []
    for a in arts:
        if a["source"] and a["source"] not in srcs:
            srcs.append(a["source"])
    peak = max(t["traffic"], key=lambda x: x[1]) if t["traffic"] else None
    first = arts[0] if arts else None
    s = [f"<b>{E(t['term'])}</b> started trending in the US on {E(fmt_et(t['first_seen']))}"]
    if peak and peak[2]:
        s[-1] += f", reaching about <b>{E(peak[2])}</b> Google searches"
    s[-1] += "."
    if srcs:
        top = ", ".join(E(x) for x in srcs[:3])
        s.append(f"{len(srcs)} news outlet{'s' if len(srcs) != 1 else ''} covered it in our feed, including {top}.")
    if first:
        s.append(f"The earliest report we found came from {E(first['source'] or 'a news outlet')} at {E(fmt_et(first['time']))}.")
    if len(t.get("spikes", [])) > 1:
        s.append(f"This topic has trended on {len(t['spikes'])} different days.")
    return " ".join(s), srcs


def build_topic(t, related):
    summ, srcs = topic_summary(t)
    arts = t["articles"]
    latest = sorted(arts, key=lambda a: a["time"], reverse=True)
    items = "".join(f'<li><span class="src">{E(a["source"] or "News")}</span>'
                    f'<a class="t" href="{E(a["url"])}" target="_blank" rel="noopener nofollow">{E(a["title"])}</a>'
                    f'<span class="meta">{E(fmt_et(a["time"]))}</span></li>' for a in latest[:25])
    timeline = "".join(f'<li><span class="meta">{E(fmt_et(a["time"]))}</span> — {E(a["source"] or "News")}: '
                       f'<a href="{E(a["url"])}" target="_blank" rel="noopener nofollow">{E(a["title"])}</a></li>' for a in arts[:12])
    rel = "".join(f'<a class="chip" href="{E(r["slug"])}.html">{E(r["term"])}</a>' for r in related)
    sp = spark(t["traffic"])
    upd = t.get("last_seen", t["first_seen"])
    ld = {"@context": "https://schema.org", "@type": "Article", "headline": f"Why is {t['term']} trending?",
          "datePublished": t["first_seen"], "dateModified": upd, "publisher": {"@type": "Organization", "name": SITE_NAME},
          "mainEntityOfPage": f"{SITE_URL}/t/{t['slug']}"}
    ai = t.get("ai")
    ai_html = ""
    if ai:
        pl = [f"<p>{E(p)}</p>" for p in ai.get("summary", "").split("\n\n") if p.strip()]
        paras = "".join(pl[:1]) + ad("in_article") + "".join(pl[1:])
        kp = "".join(f"<li>{E(k)}</li>" for k in ai.get("key_points", []))
        unk = ai.get("unknown", "")
        ai_html = (f'<p style="font-size:20px;line-height:1.35;margin:4px 0 14px">{E(ai.get("headline", ""))}</p>{paras}'
                   + (f"<h2>Key facts</h2><ul>{kp}</ul>" if kp else "")
                   + (f"<h2>What we don't know yet</h2><p>{E(unk)}</p>" if unk else "")
                   + f'<p class="meta">Our summary of reporting by {E(", ".join(ai.get("sources", [])))}. Written with AI assistance and checked against the sources; read the full stories at the links below. Updated {E(fmt_et(ai["made"]))}.</p>')
    img = t.get("img"); card = t.get("card")
    if img:
        hero = (f'<figure class="hero"><img src="../{E(img["file"])}" alt="{E(t["term"])}" loading="eager">'
                f'<figcaption>Photo: {E(img["credit"])} / <a href="{E(img["src"])}" target="_blank" rel="noopener">{E(img["license"])}</a>, via Wikimedia Commons</figcaption></figure>')
    else:   # обложка-заглушка на странице не показывается, только в превью ссылки (og:image)
        hero = ""
    side = ad("sidebar")
    body = f"""<div class="tp{' side' if side else ''}"><article>
<p class="meta">Trending in the US · updated {E(fmt_et(upd))}</p>
<h1>Why is “{E(t['term'])}” trending?</h1>
{hero}
{ai_html}
<h2>Trend data</h2>
<div class="box"><p style="margin:0">{summ}</p>{('<p class="meta" style="margin:10px 0 0">Search interest while it trended</p>' + sp) if sp else ''}</div>
{ad("middle")}
<h2>What the headlines say</h2><ul class="list">{items or '<li class="meta">Coverage is still coming in.</li>'}</ul>
{('<h2>How the story unfolded</h2><ul class="list">' + timeline + '</ul>') if len(arts) > 2 else ''}
{ad("multiplex") if ai else ""}
{('<h2>Also trending</h2><div class="chips">' + rel + '</div>') if rel else ''}
</article><aside>{side}</aside></div>"""
    desc = (ai["headline"] + ". " if ai else "") + f"Why {t['term']} is trending in the US right now: what happened, who's reporting it, and links to {len(srcs) or 'the'} sources."
    head = f'<script type="application/ld+json">{json.dumps(ld)}</script>'
    if img:
        ld["image"] = f"{SITE_URL}/{img['file']}"
    elif card:
        ld["image"] = f"{SITE_URL}/{card}"
    head = f'<script type="application/ld+json">{json.dumps(ld)}</script>'
    return page(f"Why is {t['term']} trending? | {SITE_NAME}", desc, body, f"t/{t['slug']}.html", 1, head, card or (img or {}).get("file", ""))


def peak(t):
    return max([x[1] for x in t["traffic"]] or [0])


def peak_label(t):
    return max(t["traffic"], key=lambda x: x[1])[2] if t["traffic"] else ""


def hours_since(iso):
    return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds() / 3600


def front_lists(store):
    """live: в трендах сейчас; still: вышли из трендов, но ещё ищут (до HOLD_HOURS); week: самые большие за 7 дней."""
    topics = store["topics"]
    cur = set(store.get("current", []))
    live = [topics[s] for s in cur if s in topics]
    live.sort(key=lambda t: (t["traffic"][-1][1] if t["traffic"] else 0, t["first_seen"]), reverse=True)
    def score(t):
        return peak(t) * 0.5 ** (hours_since(t.get("last_seen", t["first_seen"])) / HALF_LIFE_H)
    still = [t for s, t in topics.items() if s not in cur and hours_since(t.get("last_seen", t["first_seen"])) <= HOLD_HOURS]
    still.sort(key=score, reverse=True)
    shown = {t["slug"] for t in live + still}
    week = [t for t in topics.values() if t["slug"] not in shown and hours_since(t.get("last_seen", t["first_seen"])) <= 24 * 7]
    week.sort(key=peak, reverse=True)
    return live, still[:12], week[:8]


def build_index(store):
    live, still, week = front_lists(store)

    def info(t):
        srcs = []
        for a in reversed(t["articles"]):
            if a["source"] and a["source"] not in srcs:
                srcs.append(a["source"])
        head = (t.get("ai") or {}).get("headline") or (t["articles"][-1]["title"] if t["articles"] else "")
        return srcs, head

    def card(t, label, chip):
        srcs, head = info(t)
        img = (t.get("img") or {}).get("file")
        return (f'<a class="card" href="t/{E(t["slug"])}.html">'
                + (f'<img src="{E(img)}" alt="" loading="lazy">' if img else "")
                + f'<div class="card-top"><span class="num">{E(label)}</span><span class="chip-s">{E(chip)}</span></div>'
                f'<h3>{E(t["term"])}</h3><p class="head">{E(head)}</p>'
                f'<p class="meta">{E(", ".join(srcs[:2]))}</p></a>')

    top = live or still
    parts = []
    if top:
        t = top[0]; srcs, head = info(t)
        img = (t.get("img") or {}).get("file")
        tr = (t["traffic"][-1][2] if live else peak_label(t)) if t["traffic"] else ""
        parts.append(f'<a class="lead{" has-img" if img else ""}" href="t/{E(t["slug"])}.html">'
                     + (f'<img src="{E(img)}" alt="">' if img else "")
                     + f'<div class="lead-txt"><span class="badge">#1 · {E(tr)} searches</span>'
                     f'<h2 class="lead-term">{E(t["term"])}</h2><p class="lead-head">{E(head)}</p>'
                     f'<p class="meta">Since {E(fmt_et(t["first_seen"]))} · {E(", ".join(srcs[:3]))}</p></div></a>')
    parts.append(ad("home"))
    rest = top[1:]
    if live:
        parts.append('<div class="grid">' + "".join(card(t, str(i), t["traffic"][-1][2] if t["traffic"] else "")
                                                     for i, t in enumerate(rest, 2)) + "</div>")
        rest = still
    if rest:
        parts.append('<h2 class="sec">Still being searched today</h2><div class="grid">'
                     + "".join(card(t, fmt_et(t["first_seen"], with_date=False), peak_label(t) + " peak") for t in rest) + "</div>")
    if week:
        if rest:
            parts.append(ad("home"))
        parts.append('<h2 class="sec">Biggest this week</h2><div class="grid">'
                     + "".join(card(t, fmt_et(t["first_seen"]).split(",")[0], peak_label(t) + " peak") for t in week) + "</div>")
    body = (f'<p class="tag">{E(TAGLINE)} · Updated {E(fmt_et(store.get("updated", now_iso())))}</p>'
            f'<h1 class="front">Trending in the US right now</h1>{"".join(parts)}' if top else "<p>No trends yet — check back in a few minutes.</p>")
    return page(f"{SITE_NAME} — What's trending in the US right now", "What Americans are searching for right now, and why. Every trend explained in one minute with links to the sources.", body, "index.html", 0)


def build_archive(store):
    by_day = {}
    for t in store["topics"].values():
        by_day.setdefault(to_et(datetime.fromisoformat(t["first_seen"]))[0].strftime("%Y-%m-%d"), []).append(t)
    parts = []
    for day in sorted(by_day, reverse=True):
        d = datetime.strptime(day, "%Y-%m-%d")
        chips = "".join(f'<a class="chip" href="t/{E(t["slug"])}.html">{E(t["term"])}</a>' for t in sorted(by_day[day], key=lambda t: t["first_seen"]))
        parts.append(f"<h2>{d.strftime('%A, %B')} {d.day}, {d.year}</h2><div class='chips'>{chips}</div>")
    return page(f"Trend archive | {SITE_NAME}", "Every topic that trended in the US, day by day.", "<h1>Trend archive</h1>" + "".join(parts), "archive.html", 0)


STATIC = {
    "about.html": ("About", f"<h1>About {SITE_NAME}</h1><p>{SITE_NAME} watches what people across the United States are searching for on Google and, for every trending topic, puts together a one-minute rundown: when it started trending, how big the interest is, which outlets are covering it, and how the story developed.</p><p>We don't copy articles. We link to the original reporting so you can read it at the source.</p>"),
    "privacy.html": ("Privacy policy", f"<h1>Privacy policy</h1><p>{SITE_NAME} does not ask you to create an account and does not collect personal information directly. We use Google Analytics to understand how many people visit and which pages they read, and we may show ads served by Google. Google and its partners use cookies to serve ads based on prior visits to this and other websites. You can opt out of personalized advertising at <a href='https://www.google.com/settings/ads'>Google Ads Settings</a>.</p><p>Questions: {CONTACT_EMAIL}</p>"),
    "contact.html": ("Contact", f"<h1>Contact</h1><p>Corrections, publisher requests or anything else: <b>{CONTACT_EMAIL}</b></p><p>If you are a publisher and want a link removed, email us and we'll remove it within 24 hours.</p>"),
}


def related_for(t, lists):
    """«Also trending»: то, что сейчас на главной — чтобы читатель переходил дальше по сайту."""
    out = []
    for x in lists:
        if x["slug"] != t["slug"] and x not in out:
            out.append(x)
    return out[:10]


def visible(store):
    ub = user_blocks()
    out = {}
    for s, t in store["topics"].items():
        if t.get("blocked") or bad_text(t["term"], ub) or not t["articles"]:
            continue
        if ONLY_WITH_SUMMARY and not t.get("ai"):
            continue
        out[s] = t
    return out


def build_site(store):
    os.makedirs(os.path.join(OUT, "t"), exist_ok=True)
    allt = store["topics"]
    topics = visible(store)
    # удалить страницы скрытых тем, если они были опубликованы раньше
    for s in allt:
        if s not in topics:
            for fn in (f"t/{s}.html", f"img/{s}.jpg", f"img/{s}.png", f"img/card-{s}.png"):
                try:
                    os.remove(os.path.join(OUT, fn))
                except FileNotFoundError:
                    pass
    view = dict(store); view["topics"] = topics
    view["current"] = [s for s in store.get("current", []) if s in topics]
    store = view
    live, still, week = front_lists(store)
    lists = live + still + week
    def w(path, text):
        p = os.path.join(OUT, path); os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
    for t in topics.values():
        w(f"t/{t['slug']}.html", build_topic(t, related_for(t, lists)))
    for s, target in store.get("alias", {}).items():
        if target in topics and s not in topics:
            url = f"{SITE_URL}/t/{target}"
            w(f"t/{s}.html", f'<!doctype html><html><head><meta charset="utf-8"><link rel="canonical" href="{E(url)}">'
                             f'<meta http-equiv="refresh" content="0; url={E(target)}.html"><title>Moved</title></head>'
                             f'<body><a href="{E(target)}.html">Continue</a></body></html>')
    w("index.html", build_index(store))
    w("archive.html", build_archive(store))
    for fn, (title, body) in STATIC.items():
        w(fn, page(f"{title} | {SITE_NAME}", f"{title} — {SITE_NAME}", body, fn, 0))
    w("404.html", page(f"Not found | {SITE_NAME}", "Page not found", "<h1>Page not found</h1><p><a href='index.html'>See what's trending now</a></p>", "404.html", 0))
    urls = [f"{SITE_URL}/", f"{SITE_URL}/archive"] + [f"{SITE_URL}/t/{t['slug']}" for t in topics.values()]
    lm = {f"{SITE_URL}/t/{t['slug']}": t.get("last_seen", t["first_seen"]) for t in topics.values()}
    w("sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
      + "".join(f"<url><loc>{E(u)}</loc>" + (f"<lastmod>{lm[u]}</lastmod>" if u in lm else "") + "</url>" for u in urls) + "</urlset>")
    if ADSENSE_CLIENT:
        w("ads.txt", f"google.com, {ADSENSE_CLIENT.replace('ca-', '')}, DIRECT, f08c47fec0942fa0\n")
    w("robots.txt", f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}/sitemap.xml\n")
    items = sorted(topics.values(), key=lambda t: t["first_seen"], reverse=True)[:50]
    w("feed.xml", '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
      f"<title>{SITE_NAME}</title><link>{SITE_URL}</link><description>{E(TAGLINE)}</description>"
      + "".join(f"<item><title>Why is {E(t['term'])} trending?</title><link>{SITE_URL}/t/{t['slug']}</link>"
                f"<guid>{SITE_URL}/t/{t['slug']}</guid><pubDate>{datetime.fromisoformat(t['first_seen']).strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate></item>" for t in items)
      + "</channel></rss>")
    return len(topics)


def run_once():
    store = tidy(load_store())
    n = update(store)
    save_store(store)
    os.makedirs(OUT, exist_ok=True)
    ni = images(store)
    if ni:
        log(f"Найдено свободных фото: {ni}")
    if ONLY_WITH_SUMMARY and not api_key():
        log(f"ВНИМАНИЕ: нет файла {KEY_FILE} — сводки не пишутся, а без сводок темы не публикуются. Сайт будет пустым.")
    k = summarize(store)
    if k:
        log(f"Написано сводок: {k}")
    save_store(store)
    total = build_site(store)
    log(f"Трендов сейчас: {n}, тем в архиве: {total}. Сайт: {os.path.join(OUT, 'index.html')}")


def main():
    while True:
        try:
            run_once()
        except Exception as e:
            log(f"ОШИБКА прохода: {e}")
        if RUN_ONCE or CLOUD:
            break
        time.sleep(INTERVAL_MIN * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print("ОШИБКА:", e)
        if CLOUD:
            sys.exit(1)
    if not CLOUD:
        input("\nГотово. Откройте site\\index.html в Chrome. Нажмите Enter, чтобы закрыть окно...")
