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
GA_ID = "G-F166MQDSTT"                 # код Google Analytics (G-XXXXXXX), когда появится
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
CATS = {                   # разделы сайта: тема попадает в один из них (решает ИИ)
    "sports": "Sports", "entertainment": "Entertainment", "politics": "Politics", "business": "Business & Money",
    "tech": "Tech & Science", "world": "World", "lifestyle": "Lifestyle", "other": "More news",
}
ONLY_WITH_SUMMARY = True  # публиковать только темы со сводкой ИИ (защита от санкций Google за «массовый контент»)
MAX_NEW_PER_DAY = 20       # сколько новых тем в сутки (по времени США) получают сводку и попадают на сайт — самые крупные
EXPLAIN = True             # объяснения: что люди начнут гуглить после новости (термины, законы, места, малоизвестные люди)
MAX_EXPLAINERS_PER_DAY = 15   # сколько новых объяснений в сутки
EXPLAINERS_PER_TOPIC = 2      # не больше стольких объяснений из одной новости
MIN_FULL_ARTICLES = 1      # писать сводку, только если хотя бы столько статей удалось прочитать целиком (не одни заголовки)
AI_REVIEW = True           # второй ИИ-«редактор» проверяет каждую сводку и объяснение перед публикацией и снимает плохие
INDEXNOW = True            # мгновенно сообщать Bing/Yahoo/DuckDuckGo о новых страницах
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
- Do NOT name news outlets in the text ("according to ESPN", "Yahoo reported"). The sources are listed under the article.
  Name an outlet only when a claim is disputed or exclusive, and only if that outlet's own text says it.
- Many sources are headlines only. Then write shorter (80-120 words) and state only what the headlines say; never fill gaps.
- Do not write about search interest or guess why people are searching ("fans are curious", "likely because").
- Set "safe": false if the topic is mainly about sexual or pornographic content, nudity or leaked intimate images, graphic violence or gore videos, terrorist or extremist propaganda, instructions for weapons, drugs, self-harm or crime, hate speech, gambling promotion, scams, or naming/accusing a private person (not a public figure) or identifying a minor in a crime. Ordinary news coverage of crime, accidents, politics or deaths reported by mainstream outlets is safe.

Also pick ONE category for the topic: sports, entertainment, politics, business, tech, world, lifestyle or other
(sports = games, players, leagues; entertainment = celebrities, music, TV, movies, games; business = companies, stocks, money, jobs;
tech = technology, science, health research, space; world = news outside the US; lifestyle = food, travel, weather, holidays, shopping).

Finally, predict FOLLOW-UP SEARCHES: after reading this news, what will ordinary Americans google next because they don't
know it or want to know more? An unfamiliar term, law or rule, place, organization, product, event, or a public figure most
people don't know well. Give 0-4 items. Rules: only things the sources explain or give facts about; never private individuals
(non-public people, victims, private suspects, minors); skip household names everyone already knows (e.g. Taylor Swift,
LeBron James, Apple, the NFL, Congress). "subject" = the thing itself as people would type it (1-5 words);
"query" = the exact search, e.g. "what is a continuing resolution", "who is sam laporta", "where is sinigaglia stadium".

Return ONLY JSON:
{{"safe": true or false, "safety_reason": "if not safe, why", "headline": "the concrete news that explains the searches, max 12 words — a fact, e.g. 'Barcelona beat PSG 3-1 in Paris' or 'Kickoff, TV channel and lineups for tonight's match'; never vague phrases like 'draws interest', 'trends', 'searches spike', 'ahead of'", "summary": "2 short paragraphs, 120-200 words total, separated by \\n\\n", "key_points": ["3-5 short facts"], "unknown": "one sentence on what is not known yet, or empty string", "category": "one of the categories above", "followups": [{{"subject": "...", "query": "...", "kind": "term|law|place|organization|product|event|person|other"}}], "main_person": "full name of the ONE well-known public figure the story is mainly about (athlete, celebrity, politician), or empty string if the story is not about one specific public figure", "image_query": "2-4 plain English words to find a matching free photo. If the story is about a specific team, club, company, place, event, show or product, NAME IT (e.g. 'Real Madrid players', 'Santiago Bernabeu stadium', 'Tesla factory', 'Lambeau Field', 'Marine Corps Marathon runners'); only if it is about nothing specific, use a generic scene (e.g. 'judge gavel', 'stock market screen'). Never a private person"}}

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
            "category": {"type": "string", "enum": list(CATS)},
            "image_query": {"type": "string"},
            "main_person": {"type": "string"},
            "followups": {"type": "array", "items": {"type": "object", "properties": {
                "subject": {"type": "string"}, "query": {"type": "string"},
                "kind": {"type": "string", "enum": ["term", "law", "place", "organization", "product", "event", "person", "other"]}},
                "required": ["subject", "query", "kind"]}},
        },
        "required": ["safe", "headline", "summary", "key_points", "category"],
    },
}


def ai_call(prompt, key, tool=None):
    """Запрос к Claude. Ответ приходит готовыми полями через инструмент — без разбора текста."""
    tool = tool or AI_TOOL
    body = json.dumps({"model": AI_MODEL, "max_tokens": 2000, "tools": [tool],
                       "tool_choice": {"type": "tool", "name": tool["name"]},
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
            return _clean(b["input"])
    txt = "".join(b.get("text", "") for b in data.get("content", []))
    m = re.search(r"\{.*\}", txt, re.S)
    if m:
        return json.loads(m.group(0))
    raise RuntimeError(f"ответ без данных (stop_reason={data.get('stop_reason')}): {txt[:200]!r}")


RUN_SOURCES = {}   # тексты статей этого прохода — только в памяти, нужны для объяснений, не сохраняются


def write_summary(t, key, feedback=""):
    picks, outlets = [], set()
    # сначала статьи, которые можно прочитать целиком (ссылки Google News открываются только как заголовок)
    for a in sorted(t["articles"], key=lambda a: ("news.google.com" not in a["url"], a["time"]), reverse=True):
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
        blocks.append(f"[{i}] {a['source']} — {a['title']}\n"
                      + (body or "(HEADLINE ONLY — use only what this headline itself states; do not attribute any other detail to this outlet)"))
    full = sum(1 for x in texts if len(x) > 400)
    if full < MIN_FULL_ARTICLES:
        t["thin_at"] = len(t["articles"])        # вернёмся к теме, когда появятся новые статьи
        log(f"'{t['term']}': только заголовки, полных статей нет — пока не пишу")
        return None
    traffic = t["traffic"][-1][2] if t["traffic"] else "unknown"
    prompt = PROMPT.format(term=t["term"], traffic=traffic, sources="\n\n".join(blocks))
    if feedback:
        prompt += ("\n\nAn editor rejected your previous draft for this reason: " + feedback
                   + "\nWrite a new draft that fixes this. When unsure about a detail, leave it out.")
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
            if out.get("category") in CATS:
                t["cat"] = out["category"]
            fu = []
            for f in out.pop("followups", None) or []:
                subj = re.sub(r"\s+", " ", str(f.get("subject", ""))).strip()
                if 2 < len(subj) <= 60 and latin(subj) and not bad_text(subj, user_blocks()):
                    fu.append({"subject": subj, "query": str(f.get("query", ""))[:90].strip() or subj, "kind": f.get("kind", "other")})
            t["followups"] = fu[:4]
            mp = re.sub(r"[^\w .'\-]", "", str(out.pop("main_person", "") or "")).strip()
            t["main_person"] = mp[:60]; t["person_checked"] = True
            iq = re.sub(r"[^A-Za-z0-9 \-]", "", str(out.pop("image_query", "") or "")).strip()
            if iq:
                t["image_query"] = iq[:50]; t["iq_v"] = 2
            RUN_SOURCES[t["slug"]] = {"texts": texts, "blocks": blocks,
                                      "links": [(a["source"], a["title"], a["url"]) for a in picks]}
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


CAT_TOOL = {"name": "set_categories", "description": "Category for each topic.",
            "input_schema": {"type": "object", "properties": {"items": {"type": "array", "items": {
                "type": "object", "properties": {"n": {"type": "integer"}, "category": {"type": "string", "enum": list(CATS)}},
                "required": ["n", "category"]}}}, "required": ["items"]}}


def classify_missing(store, key):
    """Темам, у которых уже есть сводка, но нет раздела — одним коротким запросом проставить раздел."""
    todo = [t for t in store["topics"].values() if t.get("ai") and t.get("cat") not in CATS][:40]
    if not todo:
        return 0
    lines = "\n".join(f"{i}. {t['term']} — {t['ai'].get('headline', '')}" for i, t in enumerate(todo))
    prompt = ("Assign one category to each trending US topic: sports, entertainment, politics, business, tech, world, "
              "lifestyle or other (sports = games, players, leagues; entertainment = celebrities, music, TV, movies, games; "
              "business = companies, stocks, money; tech = technology, science, health research; world = news outside the US; "
              "lifestyle = food, travel, weather, holidays, shopping).\n\n" + lines)
    try:
        out = ai_call(prompt, key, CAT_TOOL)
    except Exception as e:
        log(f"разделы не проставлены: {e}")
        return 0
    n = 0
    for it in out.get("items", []):
        i, c = it.get("n"), it.get("category")
        if isinstance(i, int) and 0 <= i < len(todo) and c in CATS:
            todo[i]["cat"] = c; n += 1
    return n


def mixed_order(topics):
    """Чередуем крупные и средние темы: по крупным конкурируют большие СМИ, по средним у нового сайта больше шансов."""
    s = sorted(topics, key=lambda x: x["traffic"][-1][1] if x["traffic"] else 0, reverse=True)
    half = (len(s) + 1) // 2
    big, mid = s[:half], s[half:]
    out = []
    for i in range(max(len(big), len(mid))):
        if i < len(big):
            out.append(big[i])
        if i < len(mid):
            out.append(mid[i])
    return out


REVIEW_PROMPT = """You are a strict fact-checking editor for a US news explainer website. Below is a DRAFT written by another AI
and the SOURCE reports it was based on. Decide if the draft can be published.

Verdict "block" if ANY of these is true:
- it states a fact that matters (a name, number, score, date, quote, cause, accusation) that is NOT supported by the sources
  (allowed without a source: well-established, uncontroversial public knowledge such as a definition, the year a famous film
  came out, where a city or landmark is, a famous person's well-known profession or team);
- it presents speculation or rumor as fact, or the headline/title misleads about what happened;
- it identifies or accuses a private individual (not a public figure), a minor, or a crime victim;
- it is sexual, graphic, hateful, or promotes gambling, drugs, weapons or self-harm;
- it is empty or useless: mostly says nothing is known, repeats the topic name, or does not answer the question it claims to answer;
- it is not in clear, correct English.
Otherwise verdict "ok". Do NOT block for: minor style issues; which outlet a fact is credited to, as long as some source supports
the fact itself; harmless generic phrasing; small date-format differences; a detail that is a reasonable plain-words reading
of a headline. Block only for problems a careful reader would call wrong or misleading. Be specific in "reason" (max 25 words).

DRAFT ({kind}):
{draft}

SOURCES:
{sources}"""

REVIEW_TOOL = {"name": "review", "description": "Editor's verdict.",
               "input_schema": {"type": "object", "properties": {
                   "verdict": {"type": "string", "enum": ["ok", "block"]},
                   "reason": {"type": "string"}}, "required": ["verdict", "reason"]}}


def review(store, kind, title, draft, src, key):
    """Второй ИИ проверяет текст по источникам. True — можно публиковать. Решения пишутся в журнал data → review_log."""
    if not (AI_REVIEW and src):
        return True
    try:
        out = ai_call(REVIEW_PROMPT.format(kind=kind, draft=draft[:6000], sources="\n\n".join(src["blocks"])[:24000]),
                      key, REVIEW_TOOL)
    except Exception as e:
        log(f"редактор не ответил ({title}): {e} — публикую без проверки")
        return True
    ok = out.get("verdict") != "block"
    journal = store.setdefault("review_log", [])
    journal.append({"time": now_iso(), "kind": kind, "title": title[:120], "verdict": "ok" if ok else "block",
                    "reason": str(out.get("reason", ""))[:200]})
    store["review_log"] = journal[-300:]
    if not ok:
        log(f"РЕДАКТОР СНЯЛ ({kind}) «{title}»: {out.get('reason', '')}")
    return ok


def summarize(store):
    key = api_key()
    if not key:
        return 0
    done = 0
    today = to_et(datetime.now(timezone.utc))[0].strftime("%Y-%m-%d")
    new_today = sum(1 for x in store["topics"].values() if x.get("ai_day") == today)
    # лимит распределяем по суткам США: ночью не тратим всё, днём (когда трендов больше всего) остаётся запас
    et_hour = to_et(datetime.now(timezone.utc))[0].hour
    allowed = min(MAX_NEW_PER_DAY, math.ceil(MAX_NEW_PER_DAY * (et_hour + 1) / 24) + 2)
    cur = [store["topics"][s] for s in store.get("current", []) if s in store["topics"]]
    cur = mixed_order(cur)            # крупные вперемешку со средними
    for t in cur:
        if done >= AI_PER_RUN:
            break
        ai = t.get("ai")
        vague = ai and re.search(r"draws? interest|\btrend|search|ahead of|buzz|attention", ai.get("headline", ""), re.I)
        if ai and not vague and len(t["articles"]) - ai.get("n_articles", 0) < 3:
            continue
        if not ai and t.get("thin_at") and len(t["articles"]) - t["thin_at"] < 2:
            continue                     # раньше были одни заголовки; ждём новых статей
        if not ai and new_today >= allowed:
            continue                     # лимит на это время суток исчерпан; обновлять старые можно
        res = write_summary(t, key)
        if res:
            draft = (f"{t['term']}: {res.get('headline', '')}\n\n{res.get('summary', '')}\n\nKey facts: "
                     + "; ".join(res.get("key_points", [])) + f"\nUnknown: {res.get('unknown', '')}")
            ok = review(store, "news summary", f"{t['term']}: {res.get('headline', '')}", draft, RUN_SOURCES.get(t["slug"]), key)
            if not ok:                           # одна попытка исправить по замечанию редактора
                res = write_summary(t, key, store["review_log"][-1]["reason"])
                if res:
                    draft = (f"{t['term']}: {res.get('headline', '')}\n\n{res.get('summary', '')}\n\nKey facts: "
                             + "; ".join(res.get("key_points", [])) + f"\nUnknown: {res.get('unknown', '')}")
                    ok = review(store, "news summary (fixed)", f"{t['term']}: {res.get('headline', '')}", draft,
                                RUN_SOURCES.get(t["slug"]), key)
            if not ok:
                RUN_SOURCES.pop(t["slug"], None)
                if not ai:                       # новая тема — не публикуем; у старой оставляем прежнюю проверенную сводку
                    t["blocked"] = "review: " + store["review_log"][-1]["reason"]
                continue
            if not ai:
                t["ai_day"] = today; new_today += 1
            t["ai"] = res; done += 1
    return done


# ---------- объяснения: что люди будут гуглить после новости ----------
def suggest(q):
    """Подсказки Google (то, что выпадает при вводе в поиск) — реальные запросы людей в США."""
    url = "https://suggestqueries.google.com/complete/search?" + urllib.parse.urlencode(
        {"client": "firefox", "hl": "en", "gl": "us", "q": q})
    data = json.loads(get(url, timeout=15).decode("utf-8", "replace"))
    return [s for s in data[1] if isinstance(s, str)]


def demand(item):
    """Ищут ли это на самом деле. Возвращает (да/нет/None если подсказки недоступны, список вопросов людей)."""
    key = [w for w in words(item["subject"]) if len(w) > 2] or words(item["subject"])
    got, failed = [], 0
    for q in (item["subject"], item["query"]):
        try:
            got += suggest(q.lower())
        except Exception:
            failed += 1
        time.sleep(0.3)
    if failed == 2:
        return None, []
    qs = []
    for s in got:
        if all(k in words(s) for k in key) and s.lower() != item["subject"].lower() and s not in qs:
            qs.append(s)
    hit = any(all(k in words(s) for k in key) for s in got)
    return hit, qs[:8]


EXPLAIN_PROMPT = """You write short explainer pages for a US website. A reader just saw a news story and searched Google for:
"{query}"

Subject: {subject} ({kind})
Why it is in the news now: {headline}. {summary}
Questions Americans are typing into Google about it: {questions}

Write a page that answers the search directly.
Rules:
- Start with a direct answer of 40-60 words: what/who it is, in plain words. Then background, then why it matters in today's news.
- Facts about the current situation, people, numbers and dates must come ONLY from the sources below.
- For general background you may use well-established, uncontroversial public knowledge: a definition, how a rule works,
  the year a famous film came out, where a city or landmark is, what a well-known organization does. Never guess beyond that.
- Do NOT name news outlets in the text; the sources are listed on the page.
- Never invent or guess personal details (age, family, salary, address, health). Include them only if the sources state them.
- Answer only the people's questions that the sources (or well-established general knowledge) can answer; skip the rest.
- Answer only questions ABOUT the subject (what, who, where, when, how it works, why it matters). Skip personal advice questions:
  health, diet, training, medical, legal, money or betting advice ("when should runners eat", "how to avoid cramps").
- Own words only; never reuse more than 5 words in a row from a source. Neutral plain American English, no hype, no opinions.
- Set "ok": false if this is a private individual (not a public figure), a minor, a crime victim, if the sources don't give enough to
  explain it, or if the subject is sexual, extremist, or about weapons, drugs, self-harm or gambling.

SOURCES:
{sources}"""

EXPLAIN_TOOL = {
    "name": "publish_page",
    "description": "Return the explainer page.",
    "input_schema": {"type": "object", "properties": {
        "ok": {"type": "boolean"},
        "title": {"type": "string", "description": "the search as a question, max 60 characters, e.g. 'What is a continuing resolution?'"},
        "answer": {"type": "string", "description": "direct answer, 40-60 words"},
        "body": {"type": "string", "description": "2-3 short paragraphs of background, separated by \\n\\n"},
        "in_the_news": {"type": "string", "description": "1-2 sentences: why it is in the news now"},
        "faq": {"type": "array", "items": {"type": "object", "properties": {
            "q": {"type": "string"}, "a": {"type": "string"}}, "required": ["q", "a"]}},
    }, "required": ["ok", "title", "answer", "body", "in_the_news"]},
}


def _clean(o):
    """Убирает мусор вроде \\' и \\" из ответов ИИ."""
    if isinstance(o, str):
        return o.replace("\\'", "'").replace('\\"', '"').strip()
    if isinstance(o, list):
        return [_clean(v) for v in o]
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()}
    return o


def short_desc(s, n=155):
    """Описание для Google: обрезаем по границе слова, а не посреди."""
    s = re.sub(r"\s+", " ", s or "").strip()
    if len(s) <= n:
        return s
    cut = s[:n].rsplit(" ", 1)[0].rstrip(",;:—-")
    return cut + "…"


def write_explainer(item, t, src, questions, key, feedback=""):
    ai = t.get("ai") or {}
    prompt = EXPLAIN_PROMPT.format(query=item["query"], subject=item["subject"], kind=item["kind"],
                                   headline=ai.get("headline", ""), summary=ai.get("summary", "")[:900],
                                   questions="; ".join(questions) or "(no data)", sources="\n\n".join(src["blocks"]))
    if feedback:
        prompt += ("\n\nAn editor rejected your previous draft for this reason: " + feedback
                   + "\nFix it. Answer only what the sources or well-established general knowledge support; drop the rest.")
    for attempt in range(3):
        try:
            out = ai_call(prompt, key, EXPLAIN_TOOL)
        except Exception as e:
            log(f"объяснение '{item['subject']}' не написано: {e}")
            return None
        if not out.get("ok"):
            return None
        full = " ".join([out.get("answer", ""), out.get("body", ""), out.get("in_the_news", "")]
                        + [f.get("a", "") for f in out.get("faq", [])])
        hits = copied(full, src["texts"])
        if not hits:
            return out
        bad = "; ".join(f'"{h}"' for h in hits[:5])
        prompt += f"\n\nYour previous draft repeated these word sequences from the sources: {bad}. Rewrite in different words."
    return None


def explain(store):
    """Для свежих новостей этого прохода: предсказанные запросы → проверка подсказками Google → страница-объяснение."""
    key = api_key()
    if not (EXPLAIN and key):
        return 0
    ex = store.setdefault("explainers", {})
    today = to_et(datetime.now(timezone.utc))[0].strftime("%Y-%m-%d")
    made_today = sum(1 for x in ex.values() if x.get("day") == today)
    done = 0
    ub = user_blocks()
    for slug, src in RUN_SOURCES.items():
        t = store["topics"].get(slug)
        if not t or t.get("blocked") or not t.get("ai"):
            continue
        per_topic = 0
        for item in t.get("followups", []):
            if made_today >= MAX_EXPLAINERS_PER_DAY or per_topic >= EXPLAINERS_PER_TOPIC:
                break
            xs = slugify(item["subject"])
            old = ex.get(xs)
            if old:
                if slug not in old["topics"]:
                    old["topics"].append(slug)
                    old["seen"] = now_iso()
                if hours_since(old["made"]) < 72 or slug == old.get("from"):
                    continue                  # недавно писали — только добавили ссылку на новую новость
            hit, questions = demand(item)
            if hit is False:
                log(f"'{item['query']}' — в подсказках Google не ищут, пропускаю")
                continue
            res = write_explainer(item, t, src, questions, key)
            if not res or bad_text(res.get("title", ""), ub):
                continue
            draft = (f"{res['title']}\n\n{res['answer']}\n\n{res['body']}\n\nIn the news: {res['in_the_news']}\n\n"
                     + "\n".join(f"Q: {f.get('q', '')} A: {f.get('a', '')}" for f in res.get("faq", [])))
            if not review(store, item["kind"] + " explainer", res["title"], draft, src, key):
                res = write_explainer(item, t, src, questions, key, store["review_log"][-1]["reason"])
                if not res or bad_text(res.get("title", ""), ub):
                    continue
                draft = (f"{res['title']}\n\n{res['answer']}\n\n{res['body']}\n\nIn the news: {res['in_the_news']}\n\n"
                         + "\n".join(f"Q: {f.get('q', '')} A: {f.get('a', '')}" for f in res.get("faq", [])))
                if not review(store, item["kind"] + " explainer (fixed)", res["title"], draft, src, key):
                    continue
            page_ = {"subject": item["subject"], "kind": item["kind"], "query": item["query"],
                     "title": res["title"][:80], "answer": res["answer"], "body": res["body"],
                     "in_the_news": res["in_the_news"], "faq": res.get("faq", [])[:8], "questions": questions,
                     "links": src["links"], "from": slug, "made": now_iso(), "seen": now_iso(),
                     "first": (old or {}).get("first", now_iso()), "day": today if not old else old.get("day"),
                     "topics": (old or {}).get("topics", []) + ([slug] if slug not in (old or {}).get("topics", []) else []),
                     "slug": xs, "new": True}
            ex[xs] = page_
            done += 1; per_topic += 1
            if not old:
                made_today += 1
            log(f"объяснение: {res['title']}")
    # чистим очень старые
    for s in [s for s, x in ex.items() if hours_since(x.get("seen", x["made"])) > 24 * 365]:
        ex.pop(s)
    return done


# ---------- IndexNow: мгновенное оповещение Bing / Yahoo / DuckDuckGo ----------
def indexnow_key(store):
    if not store.get("indexnow_key"):
        import uuid
        store["indexnow_key"] = uuid.uuid4().hex
    return store["indexnow_key"]


def indexnow_ping(store):
    """Пингуем адреса, собранные в прошлый проход (к этому моменту они уже выложены на сайт)."""
    urls = store.pop("indexnow_pending", [])
    if not (INDEXNOW and urls and CLOUD):
        return 0
    host = urllib.parse.urlparse(SITE_URL).netloc
    body = json.dumps({"host": host, "key": indexnow_key(store), "keyLocation": f"{SITE_URL}/{indexnow_key(store)}.txt",
                       "urlList": urls[:1000]}).encode()
    try:
        req = urllib.request.Request("https://api.indexnow.org/indexnow", data=body, method="POST",
                                     headers={"Content-Type": "application/json; charset=utf-8"})
        with urllib.request.urlopen(req, timeout=30, context=CTX) as r:
            log(f"IndexNow: отправлено {len(urls)} адресов (ответ {r.status})")
        return len(urls)
    except Exception as e:
        log(f"IndexNow не ответил: {e}")
        return 0


# ---------- картинки: только свободные лицензии + своя обложка ----------
def _plain(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s or ""))).strip()


def _match(term, title):
    a = set(words(term)); b = set(words(re.sub(r"\(.*?\)", "", title)))
    return bool(b) and (b <= a or a <= b)


def wiki_image(t, name=None):
    """Фото из Википедии, только если файл на Commons под CC / Public domain. Причину отказа пишем в журнал."""
    term = name or t["term"]
    q = urllib.parse.urlencode({"action": "query", "generator": "search", "gsrsearch": term, "gsrlimit": 5,
                                "prop": "pageimages", "piprop": "original|name", "format": "json", "formatversion": 2})
    data = json.loads(get("https://en.wikipedia.org/w/api.php?" + q))
    if "error" in data:
        log(f"фото '{term}': Википедия вернула ошибку {data['error']}")
        return None
    pages = sorted(data.get("query", {}).get("pages", []), key=lambda p: p.get("index", 99))
    if not pages:
        log(f"фото '{term}': в Википедии ничего не найдено")
        return None
    for pg in pages:
        title = pg.get("title", "")
        if not _match(term, title):
            continue
        fname = pg.get("pageimage")
        if not fname:                      # например, страница-неоднозначность «Ann Li» — смотрим следующую («Ann Li (tennis)»)
            log(f"фото '{term}': у статьи «{title}» нет главной картинки — смотрю следующую")
            continue
        q = urllib.parse.urlencode({"action": "query", "prop": "imageinfo", "iiprop": "extmetadata|url", "iiurlwidth": 800,
                                    "titles": "File:" + fname, "format": "json", "formatversion": 2})
        info = json.loads(get("https://commons.wikimedia.org/w/api.php?" + q))
        cp = (info.get("query", {}).get("pages") or [{}])[0]
        if not cp.get("imageinfo"):
            log(f"фото '{term}': картинки «{fname}» нет на Commons (несвободная) — не берём")
            continue
        ii = cp["imageinfo"][0]; md = ii.get("extmetadata", {})
        lic = _plain(md.get("LicenseShortName", {}).get("value", ""))
        if not re.search(r"(?i)(^cc|creative commons|public domain|pd|cc0)", lic):
            log(f"фото '{term}': лицензия «{lic}» не свободная — не берём")
            continue
        url = ii.get("thumburl") or ii.get("url")
        os.makedirs(os.path.join(OUT, "img"), exist_ok=True)
        ext = ".png" if url.lower().endswith(".png") else ".jpg"
        fn = f"img/{t['slug']}{ext}"
        with open(os.path.join(OUT, fn), "wb") as f:
            f.write(get(url))
        log(f"фото '{term}': взято «{fname}» ({lic})")
        return {"file": fn, "credit": _plain(md.get("Artist", {}).get("value", ""))[:80] or "Wikimedia Commons",
                "license": lic, "src": ii.get("descriptionurl", ""),
                "wiki": "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))}
    log(f"фото '{term}': нет статьи с подходящим названием (нашлось: {', '.join(p.get('title', '') for p in pages)})")
    return None


PICK_TOOL = {"name": "pick_image", "description": "Choose the best illustration or none.",
             "input_schema": {"type": "object", "properties": {"n": {"type": "integer"}, "why": {"type": "string"}},
                              "required": ["n"]}}


def commons_generic(t):
    """Иллюстрация «по смыслу» из Wikimedia Commons (только свободные лицензии).
    Кандидатов отбирает ИИ по названию и описанию файла — чтобы к теннису не попал «мальчик со щёткой в Африке»."""
    query = t.get("image_query", "")
    key = api_key()
    if not query or not key:
        return None
    q = urllib.parse.urlencode({"action": "query", "generator": "search", "gsrnamespace": 6, "gsrlimit": 20,
                                "gsrsearch": f"{query} filetype:bitmap -logo -map -diagram", "prop": "imageinfo",
                                "iiprop": "url|extmetadata|size|mime", "iiurlwidth": 1200, "format": "json", "formatversion": 2})
    data = json.loads(get("https://commons.wikimedia.org/w/api.php?" + q))
    pages = sorted(data.get("query", {}).get("pages", []), key=lambda p: p.get("index", 99))
    cands = []
    for pg in pages:
        ii = (pg.get("imageinfo") or [{}])[0]
        if ii.get("mime") not in ("image/jpeg", "image/png"):
            continue
        w, h = ii.get("width", 0), ii.get("height", 0)
        if w < 900 or w < h * 1.2:                 # нужна горизонтальная и достаточно большая
            continue
        md = ii.get("extmetadata", {})
        lic = _plain(md.get("LicenseShortName", {}).get("value", ""))
        if not re.search(r"(?i)(^cc|creative commons|public domain|pd|cc0)", lic):
            continue
        desc = _plain(md.get("ImageDescription", {}).get("value", ""))[:300]
        if bad_text(desc + " " + pg.get("title", ""), user_blocks()):
            continue
        cands.append((pg, ii, md, lic, desc))
        if len(cands) >= 10:
            break
    if not cands:
        log(f"иллюстрация '{t['term']}': по запросу «{query}» свободных картинок нет")
        return None
    listing = "\n".join(f"{i}. {c[0].get('title', '')[5:]} — {c[4] or '(no description)'}" for i, c in enumerate(cands))
    prompt = (f"News story: {t['term']} — {(t.get('ai') or {}).get('headline', '')}\n"
              f"We need a generic illustration for it (idea: '{query}').\n"
              "Pick the ONE image below that a reader would immediately connect with this story's subject. If the idea names "
              "a specific team, club, place, company or event, the image MUST show that exact one (its players in its kit, "
              "its stadium, its building) — not another team or place. Otherwise pick the right sport / setting / object. "
              "Reject images of something else, an unrelated event, place or country, a private person as the main subject, "
              "logos, or anything odd or misleading. "
              "If none fits well, answer n = -1.\n\n" + listing)
    try:
        n = int(ai_call(prompt, key, PICK_TOOL).get("n", -1))
    except Exception as e:
        log(f"иллюстрация '{t['term']}': выбор не получился: {e}")
        return None
    if not 0 <= n < len(cands):
        log(f"иллюстрация '{t['term']}': среди найденных по «{query}» подходящей нет")
        return None
    pg, ii, md, lic, desc = cands[n]
    url = ii.get("thumburl") or ii.get("url")
    os.makedirs(os.path.join(OUT, "img"), exist_ok=True)
    fn = f"img/{t['slug']}.jpg"
    with open(os.path.join(OUT, fn), "wb") as f:
        f.write(get(url))
    log(f"иллюстрация '{t['term']}': «{pg.get('title', '')}» по запросу «{query}» ({lic})")
    return {"file": fn, "credit": _plain(md.get("Artist", {}).get("value", ""))[:80] or "Wikimedia Commons",
            "license": lic, "src": ii.get("descriptionurl", ""), "generic": True, "gv": 3}


IQ_RULE = "2-4 plain English words to find a matching free photo. If the story is about a specific team, club, company, place, event, show or product, NAME IT (e.g. 'Real Madrid players', 'Santiago Bernabeu stadium', 'Tesla factory', 'Lambeau Field', 'Marine Corps Marathon runners'); only if it is about nothing specific, use a generic scene (e.g. 'judge gavel', 'stock market screen'). Never a private person."

IQ_TOOL = {"name": "set_image_queries", "description": "Generic photo search words for each story.",
            "input_schema": {"type": "object", "properties": {"items": {"type": "array", "items": {
                "type": "object", "properties": {"n": {"type": "integer"}, "q": {"type": "string"}},
                "required": ["n", "q"]}}}, "required": ["items"]}}


PERSON_TOOL = {"name": "set_people", "description": "Main public figure of each story.",
               "input_schema": {"type": "object", "properties": {"items": {"type": "array", "items": {
                   "type": "object", "properties": {"n": {"type": "integer"}, "person": {"type": "string"}},
                   "required": ["n", "person"]}}}, "required": ["items"]}}


def backfill_people(store, key):
    """Старым темам: о каком известном человеке новость (чтобы взять его фото, а не иллюстрацию)."""
    todo = [t for t in store["topics"].values()
            if t.get("ai") and not t.get("person_checked") and not t.get("blocked")][:40]
    if not todo:
        return 0
    lines = "\n".join(f"{i}. {t['term']} — {t['ai'].get('headline', '')}" for i, t in enumerate(todo))
    prompt = ("For each news story give the full name of the ONE well-known public figure it is mainly about "
              "(athlete, celebrity, politician), or an empty string if it is not about one specific public figure.\n\n" + lines)
    try:
        out = ai_call(prompt, key, PERSON_TOOL)
    except Exception as e:
        log(f"люди в темах не определены: {e}")
        return 0
    for it in out.get("items", []):
        i = it.get("n")
        if isinstance(i, int) and 0 <= i < len(todo):
            todo[i]["main_person"] = re.sub(r"[^\w .'\-]", "", str(it.get("person", ""))).strip()[:60]
            todo[i]["person_checked"] = True
    return len(todo)


def backfill_image_queries(store, key):
    """Старым темам без запроса для иллюстрации — одним коротким запросом к ИИ придумать 2–3 слова."""
    todo = [t for t in store["topics"].values()
            if t.get("ai") and t.get("iq_v") != 2 and not t.get("blocked")][:40]
    if not todo:
        return 0
    lines = "\n".join(f"{i}. {t['term']} — {t['ai'].get('headline', '')}" for i, t in enumerate(todo))
    prompt = ("For each news story give " + IQ_RULE + "\n\n" + lines)
    try:
        out = ai_call(prompt, key, IQ_TOOL)
    except Exception as e:
        log(f"запросы для иллюстраций не получены: {e}")
        return 0
    n = 0
    for it in out.get("items", []):
        i = it.get("n"); q = re.sub(r"[^A-Za-z0-9 \-]", "", str(it.get("q", ""))).strip()
        if isinstance(i, int) and 0 <= i < len(todo) and q:
            todo[i]["image_query"] = q[:50]; todo[i]["iq_v"] = 2; n += 1
            if (todo[i].get("img") or {}).get("generic"):      # иллюстрацию подберём заново по новому запросу
                todo[i].pop("img"); todo[i].pop("gen_tried", None)
    return n


def generic_images(store, limit=12):
    n = 0
    for t in store["topics"].values():          # иллюстрации, выбранные старым способом (без проверки ИИ), подбираем заново
        if (t.get("img") or {}).get("generic") and t["img"].get("gv") != 3:
            t.pop("img"); t.pop("gen_tried", None)
    # новость о конкретном известном человеке — сначала ищем его свободное фото
    for t in store["topics"].values():
        if n >= limit:
            break
        mp = t.get("main_person")
        if t.get("ai") and not t.get("blocked") and mp and not t.get("person_tried") \
                and (not t.get("img") or t["img"].get("generic")):
            t["person_tried"] = True
            try:
                img = wiki_image(t, mp)
                if img:
                    t["img"] = img; n += 1
            except Exception as e:
                log(f"фото '{mp}' не скачано: {e}")
            time.sleep(0.5)
    for t in store["topics"].values():
        if n >= limit:
            break
        if t.get("ai") and not t.get("blocked") and not t.get("img") and t.get("image_query") and not t.get("gen_tried"):
            t["gen_tried"] = True
            try:
                img = commons_generic(t)
                if img:
                    t["img"] = img; n += 1
            except Exception as e:
                log(f"иллюстрация '{t['term']}' не скачана: {e}")
            time.sleep(0.5)
    return n


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
    retry = [s for s, x in store["topics"].items() if x.get("ai") and not x.get("img") and x.get("img_tried") == 0][:15]
    for slug in list(dict.fromkeys(store.get("current", []) + retry)):
        t = store["topics"].get(slug)
        if not t:
            continue
        if t.get("img_tried") != 2 and not t.get("img"):   # 2 = пробовали новым способом (старые темы пробуем ещё раз)
            t["img_tried"] = 2
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
nav a{font-size:14px;margin-left:14px;text-decoration:none;white-space:nowrap}
nav{display:flex;flex-wrap:wrap;row-gap:4px}
@media (max-width:640px){nav{flex-wrap:nowrap;overflow-x:auto;max-width:100%;padding-bottom:4px}nav a:first-child{margin-left:0}}
.cat{color:var(--accent);text-decoration:none;font-weight:700;text-transform:uppercase;letter-spacing:.05em}
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
figure.hero{margin:6px 0 16px}figure.hero img{width:100%;max-height:440px;object-fit:cover;object-position:50% 20%;border-radius:4px;display:block;background:var(--chip)}
figure.hero figcaption{font:12px "Helvetica Neue",Arial,sans-serif;color:var(--muted);margin-top:5px}
.wrap{max-width:1040px}
h1.front{font-size:22px;font-family:"Helvetica Neue",Arial,sans-serif;text-transform:uppercase;letter-spacing:.06em;margin:4px 0 16px}
.lead{display:grid;gap:18px;text-decoration:none;background:var(--card);border:1px solid var(--line);border-radius:6px;padding:22px 24px;margin-bottom:18px}
.lead.has-img{grid-template-columns:minmax(0,1.1fr) minmax(0,1fr)}
.lead img{width:100%;height:100%;max-height:300px;object-fit:cover;object-position:50% 20%;border-radius:4px}
.lead-term{font:700 44px/1.05 Georgia,serif;letter-spacing:-.01em;text-transform:none;color:var(--fg);margin:10px 0 8px}
.lead-head{font-size:19px;line-height:1.4;margin:0 0 10px}
.lead:hover .lead-term,.card:hover h3{color:var(--accent)}
.badge,.chip-s{display:inline-block;font:700 12px "Helvetica Neue",Arial,sans-serif;letter-spacing:.04em;color:#fff;background:var(--accent);border-radius:3px;padding:3px 8px}
.chip-s{white-space:nowrap;background:var(--chip);color:var(--fg);font-weight:600}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:14px}
.card{display:flex;flex-direction:column;gap:6px;text-decoration:none;background:var(--card);border:1px solid var(--line);border-top:3px solid var(--accent);border-radius:6px;padding:14px 16px;min-width:0}
.card img{width:calc(100% + 32px);margin:-14px -16px 6px;height:150px;object-fit:cover;object-position:50% 20%;border-radius:3px 3px 0 0;max-width:none}
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
.answer{font-size:19px;line-height:1.5;border-left-color:var(--accent)}
a.xl{color:#0645ad;text-decoration:none;border-bottom:1px solid rgba(6,69,173,.35)}
a.xl:hover{border-bottom-color:#0645ad;background:rgba(6,69,173,.06)}
@media (prefers-color-scheme:dark){a.xl{color:#8ab4f8;border-bottom-color:rgba(138,180,248,.4)}}
.xlinks a{display:block;margin:6px 0;font-weight:700}
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


NAV_CATS = []    # разделы, в которых есть темы (заполняется при сборке сайта)
HAS_EXPLAINED = False


def page(title, desc, body, path, depth, extra_head="", og_img=""):
    up = "../" * depth
    canon = SITE_URL + "/" + path.replace("index.html", "").replace(".html", "")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="max-image-preview:large">
<title>{E(title)}</title><meta name="description" content="{E(desc)}">
<link rel="canonical" href="{E(canon)}"><link rel="alternate" type="application/rss+xml" title="{SITE_NAME}" href="{up}feed.xml">
{f'<meta property="og:image" content="{E(SITE_URL + "/" + og_img)}"><meta name="twitter:card" content="summary_large_image">' if og_img else ''}<meta property="og:title" content="{E(title)}"><meta property="og:description" content="{E(desc)}"><meta property="og:type" content="website">
<style>{CSS}</style>{ga_snippet()}{"" if path in NO_ADS else ads_head()}{extra_head}</head><body><div class="wrap">
<header class="top"><a class="brand" href="{up}index.html">Trend<span>Rundown</span></a>
<nav><a href="{up}index.html">Trending now</a>{f'<a href="{up}explained.html">Explained</a>' if HAS_EXPLAINED else ''}{"".join(f'<a href="{up}c/{c}.html">{E(CATS[c])}</a>' for c in NAV_CATS)}<a href="{up}archive.html">Archive</a></nav></header>
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


def mini_cards(items):
    out = []
    for r in items:
        img = (r.get("img") or {}).get("file")
        out.append(f'<a class="card" href="{E(r["slug"])}.html">'
                   + (f'<img src="../{E(img)}" alt="" loading="lazy">' if img else "")
                   + f'<div class="card-top"><span class="num">{E(fmt_et(r.get("last_seen", r["first_seen"])).split(",")[0])}</span>'
                   f'<span class="chip-s">{E(peak_label(r))}</span></div>'
                   f'<h3>{E(r["term"])}</h3><p class="head">{E((r.get("ai") or {}).get("headline", ""))}</p></a>')
    return '<div class="grid">' + "".join(out) + "</div>"


EXPLAINERS = {}   # заполняется при сборке сайта: объяснения, видимые на сайте


def build_topic(t, related, same=()):
    summ, srcs = topic_summary(t)
    arts = t["articles"]
    latest = sorted(arts, key=lambda a: a["time"], reverse=True)
    items = "".join(f'<li><span class="src">{E(a["source"] or "News")}</span>'
                    f'<a class="t" href="{E(a["url"])}" target="_blank" rel="noopener nofollow">{E(a["title"])}</a>'
                    f'<span class="meta">{E(fmt_et(a["time"]))}</span></li>' for a in latest[:25])
    timeline = "".join(f'<li><span class="meta">{E(fmt_et(a["time"]))}</span> — {E(a["source"] or "News")}: '
                       f'<a href="{E(a["url"])}" target="_blank" rel="noopener nofollow">{E(a["title"])}</a></li>' for a in arts[:12])
    same = list(same)
    in_cat = bool(same) and t.get("cat") in CATS and t.get("cat") != "other"
    if not same:                      # в разделе пока пусто — показываем просто то, что сейчас в трендах
        same, related = related[:6], related[6:]
    rel = "".join(f'<a class="chip" href="{E(r["slug"])}.html">{E(r["term"])}</a>' for r in related[:8])
    catname = CATS.get(t.get("cat"), "")
    xs = [x for x in EXPLAINERS.values() if t["slug"] in x.get("topics", [])]
    xblock = ('<h2 class="sec">Explained</h2><div class="xlinks">'
              + "".join(f'<a href="../x/{E(x["slug"])}.html">{E(x["title"])} →</a>' for x in xs[:4]) + "</div>") if xs else ""
    more = ""
    if same:
        title = f"More in {catname}" if in_cat else "Also trending"
        more = (f'<h2 class="sec">{E(title)}</h2>' + mini_cards(same)
                + (f'<p class="meta"><a href="../c/{t["cat"]}.html">All {E(catname)} topics →</a></p>' if in_cat else ""))
    sp = spark(t["traffic"])
    upd = t.get("last_seen", t["first_seen"])
    _h = (t.get("ai") or {}).get("headline") or f"Why is {t['term']} trending?"
    ld = {"@context": "https://schema.org", "@type": "NewsArticle", "headline": f"{t['term']}: {_h}"[:110],
          "datePublished": t["first_seen"], "dateModified": upd,
          "author": {"@type": "Organization", "name": SITE_NAME, "url": SITE_URL},
          "publisher": {"@type": "Organization", "name": SITE_NAME, "url": SITE_URL},
          "mainEntityOfPage": f"{SITE_URL}/t/{t['slug']}"}
    if t.get("cat") in CATS:
        ld["articleSection"] = CATS[t["cat"]]
    ai = t.get("ai")
    ai_html = ""
    if ai:
        pl = [f"<p>{E(p)}</p>" for p in ai.get("summary", "").split("\n\n") if p.strip()]
        # ссылка на объяснение прямо в тексте: первое упоминание термина становится ссылкой
        for x in xs:
            pat = re.compile(r"(?<![\w>])(" + re.escape(E(x["subject"])) + r")(?![\w<])", re.I)
            for i, ptxt in enumerate(pl):
                new, n = pat.subn(lambda m: f'<a class="xl" href="../x/{E(x["slug"])}.html" title="{E(x["title"])}">{m.group(1)}</a>', ptxt, count=1)
                if n:
                    pl[i] = new
                    break
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
                f'<figcaption>{"Illustration" if img.get("generic") else "Photo"}: {E(img["credit"])} / <a href="{E(img["src"])}" target="_blank" rel="noopener">{E(img["license"])}</a>, via Wikimedia Commons</figcaption></figure>')
    else:   # обложка-заглушка на странице не показывается, только в превью ссылки (og:image)
        hero = ""
    side = ad("sidebar")
    body = f"""<div class="tp{' side' if side else ''}"><article>
<p class="meta"><a href="../index.html">{SITE_NAME}</a> › {(f'<a class="cat" href="../c/{t["cat"]}.html">{E(CATS[t["cat"]])}</a> · ') if t.get("cat") in CATS else ''}updated {E(fmt_et(upd))}</p>
<h1>Why is “{E(t['term'])}” trending?</h1>
{hero}
{ai_html}
{xblock}
{more}
<h2>Trend data</h2>
<div class="box"><p style="margin:0">{summ}</p>{('<p class="meta" style="margin:10px 0 0">Search interest while it trended</p>' + sp) if sp else ''}</div>
{ad("middle")}
<h2>What the headlines say</h2><ul class="list">{items or '<li class="meta">Coverage is still coming in.</li>'}</ul>
{('<h2>How the story unfolded</h2><ul class="list">' + timeline + '</ul>') if len(arts) > 2 else ''}
{ad("multiplex") if ai else ""}
{('<h2>Other trending topics</h2><div class="chips">' + rel + '</div>') if rel else ''}
</article><aside>{side}</aside></div>"""
    desc = short_desc((ai["headline"] + ". " if ai else "") + f"Why {t['term']} is trending in the US right now: what happened, who's reporting it, and links to {len(srcs) or 'the'} sources.", 160)
    head = f'<script type="application/ld+json">{json.dumps(ld)}</script>'
    if img:
        ld["image"] = f"{SITE_URL}/{img['file']}"
    elif card:
        ld["image"] = f"{SITE_URL}/{card}"
    head = f'<script type="application/ld+json">{json.dumps(ld)}</script>'
    title = f"{t['term']}: {ai['headline']}" if ai and ai.get("headline") else f"Why is {t['term']} trending?"
    if len(title) > 70:
        title = title[:67].rsplit(" ", 1)[0] + "…"
    return page(title, desc, body, f"t/{t['slug']}.html", 1, head, card or (img or {}).get("file", ""))


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
    xs = sorted(EXPLAINERS.values(), key=lambda x: x.get("seen", x["made"]), reverse=True)[:8]
    if xs:
        parts.append('<h2 class="sec">Explained today</h2><div class="xlinks">'
                     + "".join(f'<a href="x/{E(x["slug"])}.html">{E(x["title"])} →</a>' for x in xs)
                     + '<a href="explained.html" style="font-weight:400">All explainers →</a></div>')
    if week:
        if rest:
            parts.append(ad("home"))
        parts.append('<h2 class="sec">Biggest this week</h2><div class="grid">'
                     + "".join(card(t, fmt_et(t["first_seen"]).split(",")[0], peak_label(t) + " peak") for t in week) + "</div>")
    body = (f'<p class="tag">{E(TAGLINE)} · Updated {E(fmt_et(store.get("updated", now_iso())))}</p>'
            f'<h1 class="front">Trending in the US right now</h1>{"".join(parts)}' if top else "<p>No trends yet — check back in a few minutes.</p>")
    return page(f"{SITE_NAME} — What's trending in the US right now", "What Americans are searching for right now, and why. Every trend explained in one minute with links to the sources.", body, "index.html", 0)


def build_category(cat, topics):
    items = sorted([t for t in topics.values() if t.get("cat") == cat],
                   key=lambda t: t.get("last_seen", t["first_seen"]), reverse=True)[:60]
    cards = []
    for t in items:
        ai = t.get("ai") or {}
        img = (t.get("img") or {}).get("file")
        cards.append(f'<a class="card" href="../t/{E(t["slug"])}.html">'
                     + (f'<img src="../{E(img)}" alt="" loading="lazy">' if img else "")
                     + f'<div class="card-top"><span class="num">{E(fmt_et(t["first_seen"]).split(",")[0])}</span>'
                     f'<span class="chip-s">{E(peak_label(t))} peak</span></div>'
                     f'<h3>{E(t["term"])}</h3><p class="head">{E(ai.get("headline", ""))}</p></a>')
    name = CATS[cat]
    body = (f'<p class="tag">Trending in the US</p><h1 class="front">{E(name)}</h1>'
            f'<div class="grid">{"".join(cards)}</div>' + ad("home"))
    return page(f"{name}: what's trending now | {SITE_NAME}",
                f"Trending {name.lower()} topics in the US, each explained in one minute with links to the sources.",
                body, f"c/{cat}.html", 1)


def build_explainer(x, topics):
    news = [topics[s] for s in reversed(x.get("topics", [])) if s in topics]
    paras = "".join(f"<p>{E(p)}</p>" for p in x["body"].split("\n\n") if p.strip())
    faq = []
    for f in x.get("faq", []):
        q = f.get("q", "").strip().rstrip("?")
        if q and f.get("a"):
            faq.append({"q": q[0].upper() + q[1:] + "?", "a": f["a"]})
    faq_html = "".join(f"<h3>{E(f['q'])}</h3><p>{E(f['a'])}</p>" for f in faq)
    newslist = "".join(f'<li><a href="../t/{E(n["slug"])}.html">{E(n["term"])}</a> — '
                       f'{E((n.get("ai") or {}).get("headline", ""))} <span class="meta">{E(fmt_et(n["first_seen"]).split(",")[0])}</span></li>'
                       for n in news[:12])
    src = "".join(f'<li><span class="src">{E(s)}</span><a class="t" href="{E(u)}" target="_blank" rel="noopener nofollow">{E(ti)}</a></li>'
                  for s, ti, u in x.get("links", [])[:6])
    ld = [{"@context": "https://schema.org", "@type": "Article", "headline": x["title"],
           "datePublished": x["first"], "dateModified": x["made"],
           "author": {"@type": "Organization", "name": SITE_NAME, "url": SITE_URL},
           "publisher": {"@type": "Organization", "name": SITE_NAME, "url": SITE_URL},
           "mainEntityOfPage": f"{SITE_URL}/x/{x['slug']}"}]
    if faq:
        ld.append({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": f["q"], "acceptedAnswer": {"@type": "Answer", "text": f["a"]}} for f in faq]})
    head = f'<script type="application/ld+json">{json.dumps(ld)}</script>'
    body = f"""<article>
<p class="meta"><a href="../index.html">{SITE_NAME}</a> › <a class="cat" href="../explained.html">Explained</a> · updated {E(fmt_et(x["made"]))}</p>
<h1>{E(x["title"])}</h1>
<div class="box answer"><p style="margin:0">{E(x["answer"])}</p></div>
<h2>Why it's in the news</h2><p>{E(x["in_the_news"])}</p>
{('<ul class="list">' + newslist + '</ul>') if newslist else ''}
{ad("in_article")}
<h2>Background</h2>{paras}
{('<h2>What people are asking</h2>' + faq_html) if faq_html else ''}
{ad("middle")}
{('<h2>Sources</h2><ul class="list">' + src + '</ul>') if src else ''}
<p class="meta">Written with AI assistance from reporting by the outlets above and checked against them. Updated {E(fmt_et(x["made"]))}.</p>
</article>"""
    return page(x["title"] + (f" | {SITE_NAME}" if len(x["title"]) < 50 else ""), short_desc(x["answer"]), body,
                f"x/{x['slug']}.html", 1, head)


def build_explained_index(ex):
    items = sorted(ex.values(), key=lambda x: x.get("seen", x["made"]), reverse=True)
    rows = "".join(f'<li><a class="t" href="x/{E(x["slug"])}.html">{E(x["title"])}</a>'
                   f'<span class="meta">{E(x["answer"][:140])}…</span></li>' for x in items[:300])
    body = (f'<p class="tag">Terms, people and places from the news — explained in plain words</p>'
            f'<h1 class="front">Explained</h1><ul class="list">{rows}</ul>')
    return page(f"Explained: the words and names in today's news | {SITE_NAME}",
                "Plain-English explainers for the terms, laws, places and people that show up in trending US news.",
                body, "explained.html", 0)


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
    same = [x for x in lists if x.get("cat") and x.get("cat") == t.get("cat")]
    for x in same + lists:
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
    ub0 = user_blocks()
    for s, tt in allt.items():
        if s in topics:
            continue
        really_blocked = tt.get("blocked") or bad_text(tt["term"], ub0)
        # тема без сводки — удаляем только страницу; картинки оставляем, они понадобятся, когда сводка появится
        for fn in ((f"t/{s}.html", f"img/{s}.jpg", f"img/{s}.png", f"img/card-{s}.png") if really_blocked else (f"t/{s}.html",)):
                try:
                    os.remove(os.path.join(OUT, fn))
                except FileNotFoundError:
                    pass
    # картинка записана в данных, а файла нет (был удалён раньше) — не показываем битую, скачаем заново
    for tt in topics.values():
        for k in ("img", "card"):
            f = (tt.get(k) or {}).get("file") if k == "img" else tt.get(k)
            if f and not os.path.exists(os.path.join(OUT, f)):
                tt.pop(k, None)
                if k == "img":
                    tt["img_tried"] = 0
                    tt.pop("gen_tried", None)
    orig = store
    view = dict(store); view["topics"] = topics
    view["current"] = [s for s in store.get("current", []) if s in topics]
    store = view
    live, still, week = front_lists(store)
    lists = live + still + week
    counts = {}
    for t in topics.values():
        if t.get("cat") in CATS:
            counts[t["cat"]] = counts.get(t["cat"], 0) + 1
    NAV_CATS[:] = [c for c in CATS if counts.get(c, 0) >= 2 and c != "other"][:6]
    ub = user_blocks()
    ex = {s: x for s, x in store.get("explainers", {}).items()
          if not bad_text(x["title"] + " " + x["subject"], ub)
          and (any(tt in topics for tt in x.get("topics", [])) or not any(tt in allt for tt in x.get("topics", [])))}
    EXPLAINERS.clear(); EXPLAINERS.update(ex)
    global HAS_EXPLAINED
    HAS_EXPLAINED = bool(ex)
    by_cat = {}
    for t in sorted(topics.values(), key=lambda x: x.get("last_seen", x["first_seen"]), reverse=True):
        by_cat.setdefault(t.get("cat"), []).append(t)
    def w(path, text):
        p = os.path.join(OUT, path); os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
    for t in topics.values():
        same = [x for x in by_cat.get(t.get("cat"), []) if x["slug"] != t["slug"]][:6] if t.get("cat") in CATS else []
        others = [x for x in related_for(t, lists) if x not in same and x.get("cat") != t.get("cat")]
        w(f"t/{t['slug']}.html", build_topic(t, others, same))
    for s, target in store.get("alias", {}).items():
        if target in topics and s not in topics:
            url = f"{SITE_URL}/t/{target}"
            w(f"t/{s}.html", f'<!doctype html><html><head><meta charset="utf-8"><link rel="canonical" href="{E(url)}">'
                             f'<meta http-equiv="refresh" content="0; url={E(target)}.html"><title>Moved</title></head>'
                             f'<body><a href="{E(target)}.html">Continue</a></body></html>')
    for c in counts:
        w(f"c/{c}.html", build_category(c, topics))
    for x in ex.values():
        w(f"x/{x['slug']}.html", build_explainer(x, topics))
    for s in store.get("explainers", {}):
        if s not in ex:
            try:
                os.remove(os.path.join(OUT, f"x/{s}.html"))
            except FileNotFoundError:
                pass
    if ex:
        w("explained.html", build_explained_index(ex))
    w("index.html", build_index(store))
    w("archive.html", build_archive(store))
    for fn, (title, body) in STATIC.items():
        w(fn, page(f"{title} | {SITE_NAME}", f"{title} — {SITE_NAME}", body, fn, 0))
    w("404.html", page(f"Not found | {SITE_NAME}", "Page not found", "<h1>Page not found</h1><p><a href='index.html'>See what's trending now</a></p>", "404.html", 0))
    urls = ([f"{SITE_URL}/", f"{SITE_URL}/archive"] + ([f"{SITE_URL}/explained"] if ex else [])
            + [f"{SITE_URL}/c/{c}" for c in counts]
            + [f"{SITE_URL}/x/{x['slug']}" for x in ex.values()]
            + [f"{SITE_URL}/t/{t['slug']}" for t in topics.values()])
    lm = {f"{SITE_URL}/t/{t['slug']}": t.get("last_seen", t["first_seen"]) for t in topics.values()}
    lm.update({f"{SITE_URL}/x/{x['slug']}": x["made"] for x in ex.values()})
    # новостной sitemap для Google News: статьи за последние 48 часов
    fresh = [t for t in topics.values() if hours_since(t["first_seen"]) <= 48]
    w("sitemap-news.xml", '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
      'xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">'
      + "".join(f"<url><loc>{SITE_URL}/t/{E(t['slug'])}</loc><news:news><news:publication><news:name>{SITE_NAME}</news:name>"
                f"<news:language>en</news:language></news:publication><news:publication_date>{t['first_seen']}</news:publication_date>"
                f"<news:title>{E(t['term'] + ': ' + (t.get('ai') or {}).get('headline', ''))}</news:title></news:news></url>"
                for t in fresh) + "</urlset>")
    # IndexNow: файл-ключ и список новых адресов (отправим в следующий проход, когда страницы уже будут на сайте)
    k = indexnow_key(orig)
    w(f"{k}.txt", k)
    new_urls = [f"{SITE_URL}/t/{t['slug']}" for t in topics.values() if t.get("ai", {}).get("made", "") >= store.get("_run_started", "~")]
    new_urls += [f"{SITE_URL}/x/{x['slug']}" for x in ex.values() if x.pop("new", False)]
    if new_urls:
        orig["_pending_out"] = new_urls
    w("sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
      + "".join(f"<url><loc>{E(u)}</loc>" + (f"<lastmod>{lm[u]}</lastmod>" if u in lm else "") + "</url>" for u in urls) + "</urlset>")
    if ADSENSE_CLIENT:
        w("ads.txt", f"google.com, {ADSENSE_CLIENT.replace('ca-', '')}, DIRECT, f08c47fec0942fa0\n")
    w("robots.txt", f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}/sitemap.xml\nSitemap: {SITE_URL}/sitemap-news.xml\n")
    items = sorted(topics.values(), key=lambda t: t["first_seen"], reverse=True)[:50]
    w("feed.xml", '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
      f"<title>{SITE_NAME}</title><link>{SITE_URL}</link><description>{E(TAGLINE)}</description>"
      + "".join(f"<item><title>Why is {E(t['term'])} trending?</title><link>{SITE_URL}/t/{t['slug']}</link>"
                f"<guid>{SITE_URL}/t/{t['slug']}</guid><pubDate>{datetime.fromisoformat(t['first_seen']).strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate></item>" for t in items)
      + "</channel></rss>")
    return len(topics)


def run_once():
    store = tidy(load_store())
    store["_run_started"] = now_iso()
    indexnow_ping(store)
    n = update(store)
    save_store(store)
    os.makedirs(OUT, exist_ok=True)
    ni = images(store)
    if ni:
        log(f"Найдено свободных фото: {ni}")
    if ONLY_WITH_SUMMARY and not api_key():
        log(f"ВНИМАНИЕ: нет файла {KEY_FILE} — сводки не пишутся, а без сводок темы не публикуются. Сайт будет пустым.")
    k = summarize(store)
    if api_key():
        c = classify_missing(store, api_key())
        if c:
            log(f"Проставлено разделов: {c}")
    if k:
        log(f"Написано сводок: {k}")
    if api_key():
        backfill_people(store, api_key())
        backfill_image_queries(store, api_key())
    gi = generic_images(store)
    if gi:
        log(f"Найдено иллюстраций: {gi}")
    xn = explain(store)
    if xn:
        log(f"Написано объяснений: {xn}")
    total = build_site(store)
    pend = store.pop("_pending_out", [])
    if pend:
        store["indexnow_pending"] = pend
    store.pop("_run_started", None)
    save_store(store)
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
