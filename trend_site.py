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
MAX_NEW_PER_DAY = 12       # сколько новых тем в сутки (по времени США) получают сводку и попадают на сайт — самые крупные
EXPLAIN = True             # объяснения: что люди начнут гуглить после новости (термины, законы, места, малоизвестные люди)
MAX_EXPLAINERS_PER_DAY = 25   # сколько новых объяснений в сутки
EXPLAINERS_PER_TOPIC = 3      # не больше стольких объяснений из одной новости (включая пояснение о самом запросе)
MIN_FULL_ARTICLES = 2      # писать сводку, только если хотя бы столько статей удалось прочитать целиком (не одни заголовки)
MIN_OUTLETS = 3            # и только если о теме написали хотя бы столько разных изданий — качество, а не количество
DIG = True                 # «копать»: ИИ сам ищет в интернете предысторию и скрытую причину тренда
DIG_PER_DAY = 3            # для скольких самых крупных новых тем в сутки (поиск стоит денег: ~10-15 центов за тему)
DIG_SEARCHES = 8           # сколько поисковых запросов ИИ может сделать на одну тему
DIG_MODEL = AI_MODEL       # модель для расследования
RULES_V = 9                # версия правил для текстов; старые сводки переписываются постепенно
REWRITE_PER_RUN = 8        # сколько старых сводок переписывать за запуск
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


STYLE_1930 = """WRITING STYLE — an American newspaper correspondent of the 1930s (New York Times, AP wire), but clear to a reader today:
- Inverted pyramid. The first sentence carries who, what, where and when; later paragraphs add detail in falling order of importance.
- Short paragraphs of one or two sentences, as in a newspaper column.
- Sober and exact, but NOT an official bulletin: tell it like a good reporter explaining the story to a neighbor.
  Plain everyday words, sentences under 25 words. Past tense for events. No slang, no exclamation marks, no emojis,
  no hype words ("shocking", "slams", "epic", "fans are buzzing").
- Explain jargon with a short generic definition only (e.g. "injured reserve, the list of players sidelined for at least
  four games") — never with new facts about the people involved.
- Never write about the sources themselves ("a headline says", "another outlet described", "that item is headline-only").
- Period touches used lightly: "was rushed to a hospital", "it was learned", "officials said last night", "the former champion".
  On second reference use the surname alone (no "Mr." or "Mrs.").
- Name days and dates exactly ("on Thursday", "Oct. 23"); never "recently".
- Plain modern words where an old word would confuse. Never use outdated terms for groups of people.
Example of the tone (invented, do not reuse): "Ric Flair, the wrestling champion of an earlier generation, was taken to a
hospital in Tampa on Thursday after a fall outside a restaurant. He had disclosed only days before that physicians were
treating him for blood clots in one leg." """

PROMPT = """You answer ONE question for a US website: WHY is this topic trending on Google right now? Find the cause.
Compare all the sources: what single event or development made many people search for it at this moment?

ACCURACY COMES BEFORE STYLE. An editor will check every fact against the sources and reject the page for any slip:
- Copy every name, number, score, record, date and title EXACTLY as the sources give them. Never compute, convert or
  re-order them (do not turn a date into a weekday, do not add up series results, do not call something "first-ever",
  "only", "record" or "historic" unless a source says so).
- Do not add facts about people's careers, contracts, past seasons or history from your own memory — only from the sources.
  Your own knowledge is allowed ONLY for a generic one-line definition of a common term.
- If two sources disagree or a detail is unclear, leave the detail out.
- Short and correct beats long and colorful. When in doubt, leave it out.

Topic people are searching for: "{term}"
Search interest: {traffic}

Below are reports from news outlets. Use them ONLY as sources of facts.
Rules:
- Write entirely in your own words and your own structure. Never copy sentences or distinctive phrasing; never reuse more than 5 words in a row from any source. Do not quote unless a quote is essential; then keep it under 10 words and name who said it.
- Combine facts from several outlets into ONE story told directly, like a news anchor: "Ric Flair was taken to a hospital in Tampa
  on Thursday." Never "according to...", "X reported", "reports say", "headlines say", "per posts on Reddit", "the outlet said".
- Neutral, plain American English, no hype, no speculation, no opinions. If outlets disagree, say so. If something is unclear, say it is unclear.
- Never add facts that are not in the sources.
- "why" is the heart of the page: 1-2 sentences naming the concrete trigger and when it happened, e.g.
  "Ric Flair is trending after he was taken to a hospital in Tampa on Thursday following a fall." Use only facts from the
  sources; if the sources point to several triggers, name the main one and mention the second. Never guess at feelings
  ("fans are curious") — name the event.
- "summary" is CONTEXT, not a retelling: what led up to it, what it changes, what happens next — 2 short paragraphs.
- If there is a RESEARCH MEMO [R], use it to find the DEEPER cause: "behind" = 1-2 paragraphs on the story behind the trend
  (history, earlier events, connections) that most readers do not know. Only facts backed by its EVIDENCE lines; skip
  anything listed as unconfirmed. Without a memo, or if it found nothing deeper, "behind" is an empty string.
- Do NOT name news outlets, websites or social networks in the text ("according to ESPN", "Yahoo reported", "on Reddit"). The sources are listed under the article.
  If a claim is not confirmed, say so in plain words ("this has not been confirmed") instead of naming who said it.
  Only people in the story may be quoted ("Kerr said ..."), rarely.
- Many sources are headlines only. Then write shorter (80-120 words) and state only what the headlines say; never fill gaps.
- Apart from "why", do not write about searches or guess why people search.
- Set "safe": false if the topic is mainly about sexual or pornographic content, nudity or leaked intimate images, graphic violence or gore videos, terrorist or extremist propaganda, instructions for weapons, drugs, self-harm or crime, hate speech, gambling promotion, scams, or naming/accusing a private person (not a public figure) or identifying a minor in a crime. Ordinary news coverage of crime, accidents, politics or deaths reported by mainstream outlets is safe.

Also pick ONE category for the topic: sports, entertainment, politics, business, tech, world, lifestyle or other
(sports = games, players, leagues; entertainment = celebrities, music, TV, movies, games; business = companies, stocks, money, jobs;
tech = technology, science, health research, space; world = news outside the US; lifestyle = food, travel, weather, holidays, shopping).

If the sources are NOT really about "{term}" (for example generic score pages, or a different team or person), set "on_topic": false
and do not guess what people meant. Never write about what "searches" are about.

Finally, predict FOLLOW-UP SEARCHES: after reading this news, what will ordinary Americans google next because they don't
know it or want to know more? An unfamiliar term, law or rule, place, organization, product, event, or a public figure most
people don't know well. Give 0-4 items. Rules: only things the sources explain or give facts about; never private individuals
(non-public people, victims, private suspects, minors); skip household names everyone already knows (e.g. Taylor Swift,
LeBron James, Apple, the NFL, Congress). "subject" = the thing itself as people would type it (1-5 words);
"query" = the exact search, e.g. "what is a continuing resolution", "who is sam laporta", "where is sinigaglia stadium".

{style}

Return ONLY JSON:
{{"safe": true or false, "safety_reason": "if not safe, why", "on_topic": true or false, "dateline": "CITY, State abbreviation in 1930s newspaper form where the main event happened, e.g. 'TAMPA, Fla.' or 'WASHINGTON' or 'LONDON'; empty string if unclear", "why": "1-2 sentences: TERM is trending after/because <the concrete event and when>", "next": "one sentence on what happens next (next game, hearing, release date) if the sources say, else empty", "behind": "the story behind it from the research memo, or empty", "headline": "the concrete news that explains the searches, max 12 words — a fact, e.g. 'Barcelona beat PSG 3-1 in Paris' or 'Kickoff, TV channel and lineups for tonight's match'; never vague phrases like 'draws interest', 'trends', 'searches spike', 'ahead of'", "summary": "context, 2 short paragraphs, 90-160 words total, separated by \\n\\n", "key_points": ["3-5 short facts"], "unknown": "one sentence on what is not known yet, or empty string", "category": "one of the categories above", "followups": [{{"subject": "...", "query": "...", "kind": "term|law|place|organization|product|event|person|other"}}], "main_person": "if the searched term itself is a person's name, that person's FULL name; if the term is a team, club, company, place, show or thing, empty string; otherwise the FULL name of the ONE well-known public figure the story is mainly about, or empty string", "image_query": "2-4 plain English words to find a matching free photo of WHAT PEOPLE SEARCHED (the term above). Prefer objects, venues and scenes, not people (e.g. 'MMA octagon cage' rather than 'UFC fighters'). If the story is about a specific team, club, company, place, event, show or product, NAME IT (e.g. 'Real Madrid players', 'Santiago Bernabeu stadium', 'Tesla factory', 'Lambeau Field', 'Marine Corps Marathon runners'); only if it is about nothing specific, use a generic scene (e.g. 'judge gavel', 'stock market screen'). Never a private person"}}

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
            "why": {"type": "string"},
            "next": {"type": "string"},
            "behind": {"type": "string"},
            "dateline": {"type": "string"},
            "headline": {"type": "string"},
            "summary": {"type": "string"},
            "key_points": {"type": "array", "items": {"type": "string"}},
            "unknown": {"type": "string"},
            "category": {"type": "string", "enum": list(CATS)},
            "image_query": {"type": "string"},
            "main_person": {"type": "string"},
            "on_topic": {"type": "boolean"},
            "followups": {"type": "array", "items": {"type": "object", "properties": {
                "subject": {"type": "string"}, "query": {"type": "string"},
                "kind": {"type": "string", "enum": ["term", "law", "place", "organization", "product", "event", "person", "other"]}},
                "required": ["subject", "query", "kind"]}},
        },
        "required": ["safe", "why", "headline", "summary", "key_points", "category"],
    },
}


def ai_call(prompt, key, tool=None, max_tokens=2000):
    """Запрос к Claude. Ответ приходит готовыми полями через инструмент — без разбора текста."""
    tool = tool or AI_TOOL
    body = json.dumps({"model": AI_MODEL, "max_tokens": max_tokens, "tools": [tool],
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


DIG_PROMPT = """You are an investigative researcher for a US website that explains WHY topics trend on Google.
"{term}" is trending in the US right now (about {traffic} searches). Headlines so far:
{headlines}

The obvious headline is rarely the whole story. DIG, using web search:
1. Pin down the exact trigger: what happened, when, and why it hit now.
2. Dig into the backstory: earlier events, history, old disputes, deals, rule changes, anniversaries, past controversies
   or long-running trends that set this up. Search for the history, not only today's news.
3. Find the connections an ordinary reader would miss: why this matters, who is affected, what it leads to next.
4. Check claims against more than one source. Separate confirmed facts from claims and from speculation.
Do at most {n} searches. Prefer established news outlets, official sources and encyclopedias. Ignore rumors and gossip sites.

Then write a research memo in plain English:
TRIGGER: ...
BACKSTORY: ... (the deeper cause, with dates)
CONNECTIONS: ...
WHAT'S NEXT: ...
UNCONFIRMED: ... (claims you could not confirm)
Every fact must come from a search result. If you found nothing deeper than the headline, say so plainly."""


def dig(t, key):
    """ИИ-исследователь с поиском в интернете: ищет предысторию и неочевидную причину тренда."""
    heads = "\n".join(f"- {a['source']}: {a['title']}" for a in t["articles"][-10:])
    traffic = t["traffic"][-1][2] if t["traffic"] else "unknown"
    msgs = [{"role": "user", "content": DIG_PROMPT.format(term=t["term"], traffic=traffic, headlines=heads, n=DIG_SEARCHES)}]
    tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": DIG_SEARCHES,
              "user_location": {"type": "approximate", "country": "US"}}]
    blocks = []
    for _ in range(3):                       # pause_turn — продолжаем, пока ИИ не закончит
        body = json.dumps({"model": DIG_MODEL, "max_tokens": 3000, "tools": tools, "messages": msgs}).encode()
        req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, method="POST", headers={
            "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=240, context=CTX) as r:
                data = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            log(f"расследование '{t['term']}': HTTP {e.code}: {e.read().decode(errors='replace')[:200]}")
            return None
        except Exception as e:
            log(f"расследование '{t['term']}': {e}")
            return None
        blocks += data.get("content", [])
        if data.get("stop_reason") != "pause_turn":
            break
        msgs.append({"role": "assistant", "content": data["content"]})
    memo, evidence, links, seen = [], [], [], set()
    searches = 0
    for b in blocks:
        if b.get("type") == "server_tool_use":
            searches += 1
        if b.get("type") == "text":
            memo.append(b.get("text", ""))
            for c in b.get("citations") or []:
                url = c.get("url", "")
                if c.get("cited_text"):
                    evidence.append(f"{c.get('title', '')} ({url}): {c['cited_text']}")
                if url and url not in seen:
                    seen.add(url)
                    host = urllib.parse.urlparse(url).netloc.replace("www.", "")
                    links.append((host, c.get("title", "") or host, url))
    text = "".join(memo).strip()
    if len(text) < 200 or not evidence:
        log(f"расследование '{t['term']}': ничего надёжного не нашлось")
        return None
    log(f"расследование '{t['term']}': {searches} поисков, {len(links)} источников")
    return {"memo": text[:6000], "evidence": evidence[:40], "links": links[:10], "made": now_iso(), "searches": searches}

ASK_BAD = re.compile(r"(?i)nude|naked|sexy|hot\b|porn|leak|onlyfans|feet|address|phone number|net worth|dead|death|died|"
                     r"arrest|mugshot|wife|husband|girlfriend|boyfriend|gay|religion|stream free|reddit|twitter|tiktok")


def people_ask(term):
    """Что ещё американцы набирают в Google вместе с этим запросом (подсказки поиска) — наши собственные данные."""
    got = []
    for q in (term.lower(), "why is " + term.lower(), term.lower() + " news"):
        try:
            got += suggest(q)
        except Exception:
            pass
        time.sleep(0.3)
    key = [w for w in words(term) if len(w) > 2] or words(term)
    out = []
    for s in got:
        s = s.strip()
        if s.lower() != term.lower() and all(k in words(s) for k in key) and not ASK_BAD.search(s) and s not in out:
            out.append(s)
    return out[:8]


def write_summary(t, key, feedback="", do_dig=False):
    picks, outlets = [], set()
    # сначала статьи, которые можно прочитать целиком (ссылки Google News открываются только как заголовок)
    for a in sorted(t["articles"], key=lambda a: ("news.google.com" not in a["url"], a["time"]), reverse=True):
        if a["source"] in outlets:
            continue
        outlets.add(a["source"]); picks.append(a)
        if len(picks) >= 6:
            break
    if len(picks) < MIN_OUTLETS:
        t["thin_at"] = len(t["articles"])        # мало разных источников — ждём, пока напишут другие
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
    if do_dig and not t.get("dig"):
        d = dig(t, key)
        t["dig"] = d or {"none": True, "made": now_iso()}
    d = t.get("dig") or {}
    if d.get("memo"):
        blocks.append("[R] RESEARCH MEMO from web searches (facts below are backed by the quoted evidence):\n" + d["memo"]
                      + "\n\nEVIDENCE (quoted from the sources):\n" + "\n".join(d["evidence"]))
        texts.append(" ".join(x.split(": ", 1)[-1] for x in d["evidence"]))
    traffic = t["traffic"][-1][2] if t["traffic"] else "unknown"
    prompt = PROMPT.format(term=t["term"], traffic=traffic, sources="\n\n".join(blocks), style=STYLE_1930)
    if feedback:
        prompt += ("\n\nAn editor rejected your previous draft for this reason: " + feedback
                   + "\nWrite a new draft that fixes this. When unsure about a detail, leave it out.")
    for attempt in range(3):
        try:
            out = ai_call(prompt, key)
        except Exception as e:
            log(f"ИИ не ответил по '{t['term']}': {e}")
            return None
        if out.get("on_topic") is False:
            log(f"'{t['term']}': статьи не про этот запрос (on_topic=false) — не публикую")
            t["blocked"] = "off-topic sources"
            return None
        if out.get("safe") is False:
            log(f"'{t['term']}': ИИ пометил тему как небезопасную ({out.get('safety_reason', '')}) — скрываю")
            t["blocked"] = "ai: " + str(out.get("safety_reason", ""))[:200]
            return None
        full = " ".join([out.get("why", ""), out.get("behind", ""), out.get("headline", ""), out.get("summary", ""), " ".join(out.get("key_points", [])), out.get("unknown", "")])
        hits = copied(full, texts)
        if not hits:
            for k in ("summary", "behind", "why", "next"):
                if isinstance(out.get(k), str):
                    out[k] = out[k].replace("\\n", "\n").strip()
            if re.search(r"(?i)sources? (do|does) not|not (stated|given|say|said)|no (date|details)|unclear", out.get("next", "")):
                out["next"] = ""
            meta = re.compile(r"(?i)\b(the|these|available|our) sources?\b|\bsource \[|\bheadlines? (say|says|only|alone)\b|according to coverage")
            for k in ("why", "behind", "summary"):
                v = out.get(k) or ""
                paras = []
                for para in v.split("\n\n"):
                    sents = re.split(r"(?<=[.!?])\s+", para)
                    keep = [x for x in sents if not meta.search(x)] or sents[:1]
                    paras.append(" ".join(keep))
                out[k] = "\n\n".join(p_ for p_ in paras if p_.strip())
            if out.get("category") in CATS:
                t["cat"] = out["category"]
            fu = []
            for f in out.pop("followups", None) or []:
                subj = re.sub(r"\s+", " ", str(f.get("subject", ""))).strip()
                if 2 < len(subj) <= 60 and latin(subj) and not bad_text(subj, user_blocks()):
                    fu.append({"subject": subj, "query": str(f.get("query", ""))[:90].strip() or subj, "kind": f.get("kind", "other")})
            t["followups"] = fu[:4]
            mp = re.sub(r"[^\w .'\-]", "", str(out.pop("main_person", "") or "")).strip()
            t["main_person"] = mp[:60]; t["person_checked"] = 2
            iq = re.sub(r"[^A-Za-z0-9 \-]", "", str(out.pop("image_query", "") or "")).strip()
            if iq:
                t["image_query"] = iq[:50]; t["iq_v"] = 4
            RUN_SOURCES[t["slug"]] = {"texts": texts, "blocks": blocks,
                                      "links": [(a["source"], a["title"], a["url"]) for a in picks] + list(d.get("links", []))}
            if d.get("links"):
                out["dug"] = [list(x) for x in d["links"]]
            out["sources"] = [a["source"] for a in picks]
            out["asked"] = people_ask(t["term"])
            out["rules"] = RULES_V
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


REVIEW_PROMPT = """You are the fact-checking editor of a US news explainer website. Below is a DRAFT written by another AI and
the SOURCE reports it was based on. Give one of three verdicts.

"block" — ONLY for serious problems:
- a key fact is WRONG or contradicts the sources: wrong name, wrong score or result, wrong number, wrong date, wrong
  outcome, a quote nobody said, a wrong cause;
- an important claim (accusation, death, arrest, injury, deal, firing, record) has no support in the sources;
- it presents rumor or speculation as fact, or the headline misleads about what happened;
- it identifies or accuses a private individual, a minor or a crime victim; or it is sexual, graphic, hateful, or promotes
  gambling, drugs, weapons or self-harm;
- it is empty or useless, or not clear English.

"minor" — publishable after small fixes: a detail not in the sources, slightly loose or wrong wording, an outlet named.
  For "minor" you MUST also give "edits": for each slip, "find" = the exact words copied from the draft, "replace" = the
  corrected words (or "" to delete the phrase). Fix only the slips; keep everything else as it is.

"ok" — no problems.

These are NOT problems at all (never mention them): well-known public facts (a famous athlete's team, position or
nationality; what a league, rule or term means, e.g. injured reserve sidelines a player for at least four games; where a
city is; the year a famous film came out); a weekday that matches a date in the sources; synonyms (four straight wins = a
sweep); an empty optional section; style; which outlet a fact came from.

In "reason": for "block" list every serious problem briefly so the writer can fix them all at once; for "minor" list the
slips. Max 45 words.

DRAFT ({kind}):
{draft}

SOURCES:
{sources}"""

REVIEW_TOOL = {"name": "review", "description": "Editor's verdict.",
               "input_schema": {"type": "object", "properties": {
                   "verdict": {"type": "string", "enum": ["ok", "minor", "block"]},
                   "reason": {"type": "string"},
                   "edits": {"type": "array", "description": "for 'minor': exact fixes to apply to the draft",
                             "items": {"type": "object", "properties": {
                                 "find": {"type": "string", "description": "exact text copied from the draft (a phrase or sentence)"},
                                 "replace": {"type": "string", "description": "corrected text, or empty string to delete it"}},
                                 "required": ["find", "replace"]}}},
                   "required": ["verdict", "reason"]}}
REVIEW_EDITS = []   # правки редактора из последней проверки (для «minor»)


def apply_edits(obj, edits, keys):
    """Редактор сам правит мелочи: заменяет или вычёркивает фразы прямо в тексте."""
    n = 0
    for e in edits or []:
        f, r = str(e.get("find", "")), str(e.get("replace", ""))
        if len(f) < 4 or f == r:
            continue
        for k in keys:
            v = obj.get(k)
            if isinstance(v, str) and f in v:
                obj[k] = re.sub(r"[ \t]{2,}", " ", v.replace(f, r)).replace(" .", ".").replace(" ,", ",").strip()
                n += 1
                break
            if isinstance(v, list):
                for i, x in enumerate(v):
                    if isinstance(x, str) and f in x:
                        v[i] = x.replace(f, r).strip(); n += 1; break
                    if isinstance(x, dict):
                        for kk in ("q", "a"):
                            if f in str(x.get(kk, "")):
                                x[kk] = x[kk].replace(f, r).strip(); n += 1; break
    return n


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
    REVIEW_EDITS[:] = (out.get("edits") or []) if out.get("verdict") == "minor" else []
    journal = store.setdefault("review_log", [])
    journal.append({"time": now_iso(), "kind": kind, "title": title[:120],
                    "verdict": out.get("verdict") if out.get("verdict") in ("ok", "minor", "block") else "ok",
                    "reason": str(out.get("reason", ""))[:200]})
    store["review_log"] = journal[-300:]
    if not ok:
        log(f"РЕДАКТОР СНЯЛ ({kind}) «{title}»: {out.get('reason', '')}")
    return ok


def news_draft(t, res):
    parts = [f"{t['term']}: {res.get('headline', '')}"]
    for label, k in (("Why trending", "why"), ("Behind it", "behind"), ("", "summary"), ("What happens next", "next")):
        if (res.get(k) or "").strip():
            parts.append((label + ": " if label else "") + res[k])
    if res.get("key_points"):
        parts.append("Key facts: " + "; ".join(res["key_points"]))
    if (res.get("unknown") or "").strip():
        parts.append("Unknown: " + res["unknown"])
    return "\n\n".join(parts)


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
    for x in store["topics"].values():      # темы, снятые редактором по старым правилам, — ещё один шанс по новым
        if (x.get("blocked") or "").startswith("review:") and x.get("rv_retry") != RULES_V and hours_since(x["first_seen"]) < 48:
            x.pop("blocked"); x["rv_retry"] = RULES_V
    cur = [store["topics"][s] for s in store.get("current", []) if s in store["topics"]]
    cur = mixed_order(cur)            # крупные вперемешку со средними
    # плюс опубликованные раньше по старым правилам — переписываем постепенно
    cur += [x for x in store["topics"].values() if x.get("ai") and x["ai"].get("rules") != RULES_V
            and x["ai"].get("rw_tried") != RULES_V and not x.get("blocked") and x not in cur]
    rewrites = 0
    for t in cur:
        if done >= AI_PER_RUN:
            break
        ai = t.get("ai")
        vague = ai and re.search(r"draws? interest|\btrend|search|ahead of|buzz|attention", ai.get("headline", ""), re.I)
        old_rules = ai and ai.get("rules") != RULES_V and ai.get("rw_tried") != RULES_V and rewrites < REWRITE_PER_RUN
        if ai and not vague and not old_rules and len(t["articles"]) - ai.get("n_articles", 0) < 3:
            continue
        if old_rules:
            rewrites += 1
            ai["rw_tried"] = RULES_V        # одна попытка переписать; не вышло — остаётся прежний текст
        if generic_term(t["term"]):
            continue                     # «TV», «News Today» — слишком общие запросы, страница о них бесполезна
        if not ai and t.get("thin_at") and len(t["articles"]) - t["thin_at"] < 2:
            continue                     # раньше были одни заголовки; ждём новых статей
        if not ai and new_today >= allowed:
            continue                     # лимит на это время суток исчерпан; обновлять старые можно
        dig_today = store.setdefault("dig_days", {}).get(today, 0)
        do_dig = DIG and not ai and dig_today < DIG_PER_DAY
        res = write_summary(t, key, do_dig=do_dig)
        if do_dig and (t.get("dig") or {}).get("made", "") >= store.get("_run_started", "~"):
            store["dig_days"] = {today: dig_today + 1}       # считаем только сегодняшние
        if res and re.search(r"(?i)according to|\b(reported|reports? (say|said))\b|reddit|headlines? (say|said|report)", res.get("summary", "")):
            res = write_summary(t, key, "Do not cite outlets, reports, headlines or Reddit at all. Tell the facts directly in your own words.") or res
        if res:
            draft = news_draft(t, res)
            ok = review(store, "news summary", f"{t['term']}: {res.get('headline', '')}", draft, RUN_SOURCES.get(t["slug"]), key)
            for attempt in range(2):             # до двух попыток исправить по замечаниям редактора
                if ok:
                    break
                res = write_summary(t, key, store["review_log"][-1]["reason"])
                if not res:
                    break
                draft = news_draft(t, res)
                ok = review(store, f"news summary (fix {attempt + 1})", f"{t['term']}: {res.get('headline', '')}", draft,
                            RUN_SOURCES.get(t["slug"]), key)
            if not ok:
                RUN_SOURCES.pop(t["slug"], None)
                if not ai:                       # новая тема — не публикуем; у старой оставляем прежнюю проверенную сводку
                    t["blocked"] = "review: " + store["review_log"][-1]["reason"]
                continue
            if REVIEW_EDITS:
                fixed = apply_edits(res, REVIEW_EDITS, ["headline", "why", "behind", "summary", "next", "key_points", "unknown"])
                store["review_log"][-1]["fixed"] = fixed
                if fixed:
                    log(f"редактор сам исправил {fixed} мест(а) в '{t['term']}'")
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
- Do NOT name news outlets, websites or social networks in the text, and never write "according to", "reported" or "reports say";
  just state the facts directly. The sources are listed on the page.
- Never invent or guess personal details (age, family, salary, address, health). Include them only if the sources state them.
- Answer only the people's questions that the sources (or well-established general knowledge) can answer; skip the rest.
- Answer only questions ABOUT the subject (what, who, where, when, how it works, why it matters). Skip personal advice questions:
  health, diet, training, medical, legal, money or betting advice ("when should runners eat", "how to avoid cramps").
- Own words only; never reuse more than 5 words in a row from a source. No hype, no opinions.
- Tone: a 1930s American newspaper correspondent, formal and exact but clear to a modern reader; short paragraphs.
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


def term_item(t):
    """Пояснение о самом популярном запросе: «Кто такой Яксель Лендеборг?», «Что такое Hunter's Moon?»."""
    term = t["term"]
    if generic_term(term) or re.search(r"(?i)\bvs\.?\b| - |score|tonight|today|stats|standings|schedule|news|stock|weather|"
                                       r"hints|injury|trade|rumors|\d{4}", term) or len(term.split()) > 4:
        return None                       # матчи, счёт, «сегодня» — объяснять нечего, это новость
    mp = t.get("main_person") or ""
    person = bool(mp) and _match(term, mp)
    if not person and len(term.split()) == 1:
        return None                       # одно общее слово («Coach», «Cancer») — пояснять нечего
    return {"subject": mp if person else term, "query": ("who is " if person else "what is ") + (mp if person else term).lower(),
            "kind": "person" if person else "other"}


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
        for item in [term_item(t)] + t.get("followups", []):
            if not item:
                continue
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
            if REVIEW_EDITS:
                apply_edits(res, REVIEW_EDITS, ["title", "answer", "body", "in_the_news", "faq"])
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


def same_person(t, name, pages):
    """ИИ сверяет: какая из статей Википедии — тот самый человек из новости (а не тёзка-баскетболист)."""
    key = api_key()
    if not key:
        return None
    listing = "\n".join(f"{i}. {p.get('title', '')} — {p.get('description', '') or '(no description)'}" for i, p in enumerate(pages))
    prompt = (f"News story: {t['term']} — {(t.get('ai') or {}).get('headline', '')}\n"
              f"The story is mainly about: {name}.\n"
              "Which Wikipedia article below is about THIS SAME person (same job and context as in the story)? "
              "A different person with a similar name does not count. If none, answer n = -1.\n\n" + listing)
    try:
        n = int(ai_call(prompt, key, PICK_TOOL).get("n", -1))
    except Exception as e:
        log(f"фото '{name}': проверка человека не получилась: {e}")
        return None
    return n if 0 <= n < len(pages) else None


def same_subject(t, pg):
    """ИИ сверяет: статья Википедии «Hannibal» — про древнего полководца или про то, о чём новость (город, школа)?"""
    key = api_key()
    if not key:
        return True
    heads = "; ".join(a["title"] for a in t["articles"][-6:])
    prompt = (f"People searched for \"{t['term']}\". News headlines about it: {heads}\n"
              f"Wikipedia article: {pg.get('title', '')} — {pg.get('description', '') or '(no description)'}\n"
              "Is this Wikipedia article about the SAME thing the news is about (same person, team, place, company, show)? "
              "A different thing with the same name does not count. Answer n = 0 for yes, n = -1 for no.")
    try:
        return int(ai_call(prompt, key, PICK_TOOL).get("n", -1)) == 0
    except Exception as e:
        log(f"фото '{t['term']}': проверка темы не получилась: {e}")
        return False


def wiki_image(t, name=None):
    """Фото из Википедии, только если файл на Commons под CC / Public domain. Причину отказа пишем в журнал."""
    term = name or t["term"]
    q = urllib.parse.urlencode({"action": "query", "generator": "search", "gsrsearch": term, "gsrlimit": 5,
                                "prop": "pageimages|description", "piprop": "original|name", "format": "json", "formatversion": 2})
    data = json.loads(get("https://en.wikipedia.org/w/api.php?" + q))
    if "error" in data:
        log(f"фото '{term}': Википедия вернула ошибку {data['error']}")
        return None
    pages = sorted(data.get("query", {}).get("pages", []), key=lambda p: p.get("index", 99))
    if not pages:
        log(f"фото '{term}': в Википедии ничего не найдено")
        return None
    if name:                                  # ищем конкретного человека — сверяем, что это он, а не тёзка
        hint = (t.get("image_query") or "").split()[:1]
        if hint and hint[0].lower() not in name.lower():   # «Ann Li» → ещё «Ann Li tennis», чтобы нашёлся нужный человек
            q2 = urllib.parse.urlencode({"action": "query", "generator": "search", "gsrsearch": f"{name} {hint[0]}",
                                         "gsrlimit": 5, "prop": "pageimages|description", "piprop": "original|name",
                                         "format": "json", "formatversion": 2})
            try:
                more = json.loads(get("https://en.wikipedia.org/w/api.php?" + q2)).get("query", {}).get("pages", [])
                seen = {p.get("title") for p in pages}
                pages += [p for p in sorted(more, key=lambda p: p.get("index", 99)) if p.get("title") not in seen]
            except Exception:
                pass
        pick = same_person(t, name, pages)
        if pick is None:
            log(f"фото '{name}': среди статей ({', '.join(p.get('title', '') for p in pages)}) нет именно этого человека")
            return None
        pages = [pages[pick]]
    for pg in pages:
        title = pg.get("title", "")
        if not name and not _match(term, title):
            continue
        if not name and not same_subject(t, pg):
            log(f"фото '{term}': статья «{title}» про другое (тёзка) — не берём")
            continue
        fname = pg.get("pageimage")
        if fname and re.search(r"(?i)logo|seal|crest|emblem|wordmark|coat.of.arms|\.svg$|flag.of", fname):
            log(f"фото '{term}': «{fname}» — это логотип/герб, не фото — не берём")
            fname = None
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
        return {"file": fn, "credit": (re.sub(r"(?i)unknown author", "", _plain(md.get("Artist", {}).get("value", ""))).strip()[:80] or "Wikimedia Commons"),
                "license": lic, "src": ii.get("descriptionurl", ""), "pv": 2 if name else 1, "sv": 1,
                "wiki": "https://en.wikipedia.org/wiki/" + urllib.parse.quote(title.replace(" ", "_"))}
    log(f"фото '{term}': нет статьи с подходящим названием (нашлось: {', '.join(p.get('title', '') for p in pages)})")
    return None


PICK_TOOL = {"name": "pick_image", "description": "Choose the best illustration or none.",
             "input_schema": {"type": "object", "properties": {"n": {"type": "integer"}, "why": {"type": "string"}},
                              "required": ["n"]}}


BAD_FILES = (r"KeyArena_\(2890740573\)|Ocean_Explorer_Docked|Rajiv_Gandhi_International_Cricket_Stadium|"
             r"Sonoma_Ranch_Road_Trail_Clean_Up|Pauley_Pavilion,_exterior")


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
        blob = (desc + " " + pg.get("title", "")).lower()
        if re.search(r"\b(air base|troops|soldiers?|military|army|navy|marines|airmen|visit(s|ed)?|ceremony|funeral|memorial|reception|gala|banquet|dinner|award(s)?|meeting)\b", blob) \
                and not re.search(r"(?i)military|army|navy|war|troops|base|memorial|funeral|award|gala|dinner|meeting", query + " " + t.get("term", "")):
            continue                     # «бойцы UFC посещают авиабазу» к новости про бой не подходит
        if re.search(BAD_FILES, pg.get("title", "")):
            continue                              # фото, уже признанные неверными
        if re.search(r"(?i)abuse|assault|sex|traffick|murder|killed|shooting|lawsuit|sues|charged|epstein|attack", 
                     (t.get("ai") or {}).get("headline", "") + " " + t.get("term", "")) and \
                re.search(r"(?i)\b(people|volunteers?|crowd|team|staff|clean[ -]?up|students|workers|family|group|men|women)\b", blob):
            continue                              # к статьям о преступлениях — без фото с людьми
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
              "logos, or anything odd or misleading. ALSO reject any image whose file name or description names particular "
              "people or a specific past occasion (e.g. 'UFC fighters X, Y visit Bagram Air Base 2007', 'Senator X at rally') — "
              "readers would think the story is about them. Prefer objects, venues and scenes without identifiable people. "
              "If the story is about a crime, abuse, a death, an attack or a lawsuit, NEVER pick an image with people in it. "
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
    # проверка без ИИ: если в запросе названо конкретное место/компания (State Farm Arena, Royal Caribbean),
    # то это название должно быть и в названии файла — иначе это другой стадион или другой корабль
    names = [w.lower() for w in re.findall(r"\b[A-Z][\w'&.-]+", query)
             if w.lower() not in {"the", "a", "an", "us", "usa", "nfl", "nba", "nhl", "mlb", "wnba", "ncaa", "pga", "ufc",
                                  "new", "old", "game", "match", "players", "stadium", "arena", "team", "fans"}]
    blob = (pg.get("title", "") + " " + desc).lower().replace("_", " ")
    if names and not any(nm in blob for nm in names):
        log(f"иллюстрация '{t['term']}': «{pg.get('title', '')}» не про {', '.join(names)} — не беру")
        return None
    url = ii.get("thumburl") or ii.get("url")
    os.makedirs(os.path.join(OUT, "img"), exist_ok=True)
    fn = f"img/{t['slug']}.jpg"
    with open(os.path.join(OUT, fn), "wb") as f:
        f.write(get(url))
    log(f"иллюстрация '{t['term']}': «{pg.get('title', '')}» по запросу «{query}» ({lic})")
    return {"file": fn, "credit": (re.sub(r"(?i)unknown author", "", _plain(md.get("Artist", {}).get("value", ""))).strip()[:80] or "Wikimedia Commons"),
            "license": lic, "src": ii.get("descriptionurl", ""), "generic": True, "gv": 4}


IQ_RULE = "2-4 plain English words to find a matching free photo of WHAT PEOPLE SEARCHED (the searched term). Prefer objects, venues and scenes, not people (e.g. 'MMA octagon cage' rather than 'UFC fighters'). If the story is about a specific team, club, company, place, event, show or product, NAME IT (e.g. 'Real Madrid players', 'Santiago Bernabeu stadium', 'Tesla factory', 'Lambeau Field', 'Marine Corps Marathon runners'); only if it is about nothing specific, use a generic scene (e.g. 'judge gavel', 'stock market screen'). Never a private person."

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
            if t.get("ai") and t.get("person_checked") != 2 and not t.get("blocked")][:40]
    if not todo:
        return 0
    lines = "\n".join(f"{i}. {t['term']} — {t['ai'].get('headline', '')}" for i, t in enumerate(todo))
    prompt = ("For each news story (searched term — headline) give a FULL NAME (first and last, e.g. 'Dan Sullivan', "
              "never just 'Sullivan'): if the searched term itself is a person's name, that person; if the term is a team, "
              "club, company, place, show or thing, an empty string; otherwise the ONE well-known public figure the story "
              "is mainly about, or an empty string.\n\n" + lines)
    try:
        out = ai_call(prompt, key, PERSON_TOOL)
    except Exception as e:
        log(f"люди в темах не определены: {e}")
        return 0
    for it in out.get("items", []):
        i = it.get("n")
        if isinstance(i, int) and 0 <= i < len(todo):
            tt = todo[i]
            newp = re.sub(r"[^\w .'\-]", "", str(it.get("person", ""))).strip()[:60]
            if newp != tt.get("main_person") and (tt.get("img") or {}).get("wiki"):
                tt.pop("img"); tt.pop("person_tried", None); tt.pop("gen_tried", None)   # было фото другого человека
            tt["main_person"] = newp
            tt["person_checked"] = 2
    return len(todo)


def backfill_image_queries(store, key):
    """Старым темам без запроса для иллюстрации — одним коротким запросом к ИИ придумать 2–3 слова."""
    todo = [t for t in store["topics"].values()
            if t.get("ai") and t.get("iq_v") != 4 and not t.get("blocked")][:40]
    if not todo:
        return 0
    lines = "\n".join(f"{i}. searched: {t['term']} — {t['ai'].get('headline', '')}" for i, t in enumerate(todo))
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
            todo[i]["image_query"] = q[:50]; todo[i]["iq_v"] = 4; n += 1
            if (todo[i].get("img") or {}).get("generic"):      # иллюстрацию подберём заново по новому запросу
                todo[i].pop("img"); todo[i].pop("gen_tried", None)
    return n


def person_in_text(t, name):
    """Фото человека ставим, только если он назван в нашем тексте — иначе читатель не поймёт, кто на снимке."""
    ai = t.get("ai") or {}
    text = " ".join([t.get("term", ""), ai.get("headline", ""), ai.get("summary", "")]).lower()
    last = name.split()[-1].lower()
    return len(last) > 2 and last in text


def generic_images(store, limit=12):
    n = 0
    for t in store["topics"].values():          # фото, признанные неверными при проверке (не то место / не тот корабль / посторонние люди)
        if re.search(BAD_FILES, (t.get("img") or {}).get("src", "")):
            t.pop("img"); t.pop("gen_tried", None); t["img_tried"] = 2
    checked = 0                                  # фото по названию темы, взятые без проверки «про то ли это» (Ганнибал-полководец)
    for t in sorted(store["topics"].values(), key=lambda x: x.get("last_seen", x["first_seen"]), reverse=True):
        im = t.get("img") or {}
        if checked < 12 and t.get("ai") and im.get("wiki") and im.get("pv") == 1 and not im.get("sv"):
            checked += 1
            title = urllib.parse.unquote(im["wiki"].rsplit("/", 1)[-1]).replace("_", " ")
            if same_subject(t, {"title": title}):
                im["sv"] = 1
            else:
                log(f"фото '{t['term']}': «{title}» — про другое, убираю")
                t.pop("img"); t["img_tried"] = 2; t.pop("gen_tried", None)
    for t in store["topics"].values():          # фото человека, которого нет в тексте, — убрать
        im = t.get("img") or {}
        if im.get("wiki") and t.get("main_person") and not person_in_text(t, t["main_person"]):
            t.pop("img"); t.pop("gen_tried", None); t["person_tried"] = 2
    for t in store["topics"].values():          # иллюстрации, выбранные старым способом (без проверки ИИ), подбираем заново
        im = t.get("img") or {}
        if im.get("generic") and (im.get("gv") != 4 or (
                re.search(r"(?i)reception|gala|banquet|dinner|award|ceremony|visit", im.get("src", "") + im.get("credit", ""))
                and not re.search(r"(?i)award|gala|dinner|ceremony|visit", t.get("term", "")))):
            t.pop("img"); t.pop("gen_tried", None)
    for t in store["topics"].values():          # людей без фото пробуем ещё раз — уже с уточняющим поиском
        if t.get("main_person") and t.get("person_tried") is True and (not t.get("img") or t["img"].get("generic")):
            t["person_tried"] = None             # одна повторная попытка; после неё person_tried = 2
    # фото людей, найденные без проверки «тот ли это человек», перепроверяем
    for t in store["topics"].values():
        im = t.get("img") or {}
        if re.search(r"(?i)logo|seal|crest|emblem|wordmark|coat_of_arms|flag_of", im.get("src", "")):
            t.pop("img"); t.pop("gen_tried", None)               # старая «картинка» оказалась логотипом
            im = {}
        if t.get("main_person") and im.get("wiki") and im.get("pv") != 2:
            t.pop("img"); t.pop("person_tried", None); t.pop("gen_tried", None)
        if t.get("main_person") and len(t["main_person"].split()) < 2:
            t.pop("person_checked", None)          # была только фамилия — спросим ИИ полное имя ещё раз
    # новость о конкретном известном человеке — сначала ищем его свободное фото
    for t in store["topics"].values():
        if n >= limit:
            break
        mp = t.get("main_person")
        if mp and len(mp.split()) < 2:
            mp = None                                  # одна фамилия («Sullivan») — слишком много тёзок, не ищем
        if mp and not person_in_text(t, mp):
            mp = None                                  # человек не упомянут в тексте — лучше иллюстрация
        if t.get("ai") and not t.get("blocked") and mp and not t.get("person_tried") \
                and (not t.get("img") or t["img"].get("generic")):
            t["person_tried"] = 2
            try:
                img = wiki_image(t, mp)
                if img:
                    img["who"] = mp
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
    im = Image.new("RGB", (W, H), (243, 239, 228)); d = ImageDraw.Draw(im)
    d.rectangle([40, 40, W - 40, 46], fill=(17, 17, 17)); d.rectangle([40, H - 140, W - 40, H - 137], fill=(17, 17, 17))
    d.text((70, 60), "WHY IT'S TRENDING", font=_font(30, False), fill=(74, 74, 74))
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
        d.text((70, y), ln, font=f, fill=(17, 17, 17)); y += int(size * 1.15)
    tr = t["traffic"][-1][2] if t["traffic"] else ""
    sub = (f"{tr} US searches · " if tr else "") + fmt_et(t["first_seen"])
    d.text((70, H - 120), sub, font=_font(32, False), fill=(74, 74, 74))
    d.text((70, H - 75), "The Trend Rundown", font=_font(40), fill=(17, 17, 17))
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
:root{--bg:#f6f1e6;--fg:#2b2723;--muted:#5d564c;--line:#2b2723;--soft:#c9c0ae;--chip:#ebe4d4}
@media (prefers-color-scheme:dark){:root{--bg:#1d1a16;--fg:#ddd5c4;--muted:#a59d8d;--line:#ddd5c4;--soft:#4a453c;--chip:#2a2620}}
*{box-sizing:border-box}html,body{background:var(--bg);color:var(--fg)}
body{margin:0;font:18px/1.7 "Literata",Georgia,"Times New Roman",serif;-webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
a{color:inherit;text-decoration:none}a:hover{text-decoration:underline}
.wrap{max-width:1120px;margin:0 auto;padding:12px max(14px,env(safe-area-inset-left)) 48px max(14px,env(safe-area-inset-right))}
/* ---------- шапка газеты ---------- */
header.top{text-align:center;margin-bottom:14px}
.mast{display:grid;grid-template-columns:150px 1fr 150px;align-items:center;gap:14px;border-bottom:1px solid var(--line);padding-bottom:4px}
.ear{border:3px double var(--line);padding:5px 6px;font:700 10px/1.35 "Old Standard TT",serif;text-transform:uppercase;letter-spacing:.06em}
.ear b{display:block;font:400 22px/1 "League Gothic","Oswald",Impact,sans-serif;letter-spacing:.02em;margin:2px 0}
.brand{display:block;white-space:nowrap;font:400 clamp(34px,7.4vw,80px)/1.02 "UnifrakturMaguntia","UnifrakturCook","Old English Text MT",serif;letter-spacing:.005em}
.brand:hover{text-decoration:none}
.motto{font:italic 12px "Old Standard TT",serif;margin-top:-2px}
.dateline{display:flex;justify-content:space-between;gap:10px;flex-wrap:wrap;border-top:3px solid var(--line);border-bottom:1px solid var(--line);
  margin-top:3px;padding:3px 2px;font:700 11px/1.4 "Old Standard TT",serif;text-transform:uppercase;letter-spacing:.1em}
nav{display:flex;justify-content:center;flex-wrap:wrap;padding:4px 0;border-bottom:3px solid var(--line);font:700 11px "Old Standard TT",serif;text-transform:uppercase;letter-spacing:.12em}
nav a{padding:0 11px;border-left:1px solid var(--line);white-space:nowrap}nav a:first-child{border-left:0}
@media (max-width:700px){.mast{grid-template-columns:1fr}.ear{display:none}.dateline{justify-content:center}
  .dateline span:first-child,.dateline span:last-child{display:none}nav{flex-wrap:nowrap;overflow-x:auto;justify-content:flex-start}}
/* ---------- заголовки ---------- */
.tag{font:italic 13px "Old Standard TT",serif;text-align:center;margin:6px 0}
.meta,.small{font:italic 12.5px "Old Standard TT",serif;color:var(--muted)}
.cat{font-style:normal;font-weight:700;text-transform:uppercase;letter-spacing:.12em}
h1{font:400 clamp(40px,6.4vw,74px)/.95 "League Gothic","Oswald",Impact,sans-serif;text-transform:uppercase;letter-spacing:.01em;
  margin:10px 0 6px;text-align:center;text-wrap:balance}
.deck{font:700 15px/1.35 "Old Standard TT",serif;text-transform:uppercase;letter-spacing:.06em;text-align:center;margin:6px auto;max-width:620px}
.deck2{font:italic 17px/1.4 "Old Standard TT",serif;text-align:center;margin:4px auto 10px;max-width:640px}
.dash{width:70px;border:0;border-top:2px solid var(--line);margin:10px auto}
.byline{font:700 11px "Old Standard TT",serif;text-transform:uppercase;letter-spacing:.14em;text-align:center;margin:8px 0 14px}
h2{font:700 12px "Old Standard TT",serif;text-transform:uppercase;letter-spacing:.18em;text-align:center;margin:26px 0 10px;padding:4px 0;
  border-top:3px solid var(--line);border-bottom:1px solid var(--line);column-span:all}
h3{font:400 24px/1.05 "League Gothic","Oswald",Impact,sans-serif;text-transform:uppercase;letter-spacing:.02em;margin:18px 0 4px}
h2.sec{font:400 26px/1 "League Gothic","Oswald",Impact,sans-serif;letter-spacing:.06em;margin:30px 0 0;padding:6px 0 4px;
  border-top:5px double var(--line);border-bottom:1px solid var(--line)}
h1.front{font:700 13px "Old Standard TT",serif;letter-spacing:.24em;margin:0 0 12px;padding:4px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
/* ---------- статья: колонки, буквица ---------- */
article{max-width:700px;margin:0 auto}
article p{text-align:left;margin:0 0 1.1em}
.cols{max-width:680px;margin:0 auto}
.cols h2,.cols .box,.cols figure,.cols ul{break-inside:avoid}
@media (max-width:760px){body{font-size:17.5px}}
b.dl{font-weight:700;letter-spacing:.04em}
p.dc::first-letter{float:left;font:400 64px/.82 "League Gothic","Oswald",Impact,sans-serif;padding:4px 6px 0 0}
.box{border:1px solid var(--line);outline:1px solid var(--line);outline-offset:3px;padding:12px 16px;margin:8px 4px 14px}
.answer{font:italic 20px/1.6 "Literata",Georgia,serif}
.answer p{text-align:center!important;margin:0}
.list{list-style:none;padding:0;margin:0}
.list li{padding:8px 0;border-bottom:1px solid var(--soft);break-inside:avoid}
.list .src{font:700 10.5px "Old Standard TT",serif;text-transform:uppercase;letter-spacing:.14em}
.list .t{display:block;font:600 17px/1.4 "Literata",Georgia,serif;margin:2px 0}
ul{padding-left:20px}
.chips{display:flex;flex-wrap:wrap;gap:6px}
.chip{border:1px solid var(--line);padding:1px 9px;font:12px "Old Standard TT",serif;text-transform:uppercase;letter-spacing:.06em}
footer{margin-top:40px;padding-top:10px;border-top:5px double var(--line);font:12px "Old Standard TT",serif;text-align:center}
footer a{margin:0 10px;text-transform:uppercase;letter-spacing:.1em;font-weight:700}
svg.spark{display:block;max-width:100%}
img{filter:none}
figure.hero{margin:8px 0 14px;break-inside:avoid}figure.hero img{width:100%;max-height:440px;object-fit:cover;object-position:50% 20%;display:block;border:1px solid var(--line)}
figure.hero figcaption{font:italic 11.5px "Old Standard TT",serif;margin-top:4px;padding-bottom:4px;border-bottom:1px solid var(--line);text-align:center}
/* ---------- первая полоса ---------- */
.lead{display:grid;gap:20px;padding:4px 0 16px;margin-bottom:0;border-bottom:5px double var(--line)}
.lead.has-img{grid-template-columns:minmax(0,1.05fr) minmax(0,1fr)}
.lead img{width:100%;height:100%;max-height:360px;object-fit:cover;object-position:50% 20%;border:1px solid var(--line)}
.lead-term{font:400 clamp(48px,7.5vw,96px)/.9 "League Gothic","Oswald",Impact,sans-serif;text-transform:uppercase;margin:6px 0 8px;letter-spacing:.005em;
  border:0;padding:0;text-align:left;column-span:none}
.lead-head{font:700 17px/1.35 "Old Standard TT",serif;text-transform:uppercase;letter-spacing:.04em;margin:0 0 8px}
.lead-txt p.snip{font-size:17px;line-height:1.65}
.lead:hover .lead-term,.card:hover h3{text-decoration:underline;text-decoration-thickness:2px}
.badge{display:inline-block;font:700 10.5px "Old Standard TT",serif;text-transform:uppercase;letter-spacing:.16em;border-top:2px solid var(--line);border-bottom:1px solid var(--line);padding:2px 0}
.chip-s{white-space:nowrap;font:italic 11.5px "Old Standard TT",serif}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:0;border-left:1px solid var(--line)}
.card{display:flex;flex-direction:column;gap:5px;padding:12px 14px 14px;min-width:0;border-right:1px solid var(--line);border-bottom:1px solid var(--soft)}
.card img{width:100%;height:auto;aspect-ratio:4/3;object-fit:cover;object-position:50% 20%;border:1px solid var(--line);margin-bottom:2px}
.card-top{display:flex;justify-content:space-between;align-items:baseline;border-bottom:1px solid var(--line);padding-bottom:2px}
.num{font:700 10.5px "Old Standard TT",serif;letter-spacing:.14em;text-transform:uppercase}
.card h3{font:400 30px/.95 "League Gothic","Oswald",Impact,sans-serif;margin:4px 0 0;overflow-wrap:anywhere}
.card .head{margin:0;font:700 12.5px/1.35 "Old Standard TT",serif;text-transform:uppercase;letter-spacing:.03em;
  display:-webkit-box;-webkit-line-clamp:4;-webkit-box-orient:vertical;overflow:hidden;border-top:1px solid var(--soft);padding-top:5px}
.card .snip{margin:0;font:15px/1.6 "Literata",Georgia,serif;display:-webkit-box;-webkit-line-clamp:6;-webkit-box-orient:vertical;overflow:hidden}
.card .meta{margin-top:auto;padding-top:4px}
.ad{margin:26px 0;padding:8px 0;border-top:1px solid var(--line);border-bottom:1px solid var(--line);text-align:center;min-height:120px}
.ad-l{font:10.5px "Old Standard TT",serif;letter-spacing:.16em;text-transform:uppercase;margin-bottom:6px}
.tp{display:block}.tp aside{display:none}
@media (min-width:1080px){.tp.side{display:grid;grid-template-columns:minmax(0,1fr) 300px;gap:30px}.tp.side aside{display:block;border-left:1px solid var(--line);padding-left:18px}
.tp aside .ad{position:sticky;top:16px;margin:0;border:0;padding:0}}
a.xl{text-decoration:underline;text-decoration-style:dotted;text-underline-offset:3px;font-weight:700}
.xlinks a{display:block;margin:5px 0;font:400 22px/1.1 "League Gothic","Oswald",Impact,sans-serif;text-transform:uppercase;letter-spacing:.02em}
.rx{margin:22px 0 6px;text-align:center;column-span:all}
.rx-row{display:flex;flex-wrap:wrap;gap:6px;justify-content:center}
.rx-b{display:inline-flex;align-items:center;gap:4px;min-width:44px;height:36px;padding:0 9px;border:1px solid var(--line);border-radius:0;
  background:transparent;cursor:pointer;font:700 13px "Old Standard TT",serif;color:var(--fg)}
.rx-b:hover{background:var(--chip)}.rx-b.on{background:var(--fg);color:var(--bg)}
.rx-e{font-size:18px;line-height:1;filter:grayscale(1)}
.ct{overflow-x:auto;margin:8px 0 16px}.ct table{border-collapse:collapse;width:100%;font:15px/1.5 "Literata",Georgia,serif}
.ct th,.ct td{text-align:left;padding:6px 9px;border-bottom:1px solid var(--soft);vertical-align:top}
.ct th{font-size:10.5px;text-transform:uppercase;letter-spacing:.14em;border-top:2px solid var(--line);border-bottom:1px solid var(--line)}
.ct td:last-child{font-style:italic;font-size:13.5px}
.ls{text-align:center;margin:4px 0 16px}
.ls button{font:700 12px "Old Standard TT",serif;text-transform:uppercase;letter-spacing:.14em;color:var(--fg);background:transparent;
  border:1px solid var(--line);outline:1px solid var(--line);outline-offset:2px;padding:8px 16px;margin:0 6px;cursor:pointer}
.ls button:hover{background:var(--chip)}
::highlight(ls-s){background-color:rgba(214,170,60,.28)}
::highlight(ls-w){background-color:#e0b23c;color:#1a1714}
.ls-cur{background:rgba(214,170,60,.28)}
img.whole{object-fit:contain!important;background:var(--chip)}
.card img,.lead img,figure.hero img{object-position:50% 22%}
@media (max-width:700px){.lead.has-img{grid-template-columns:1fr}}
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


def today_line():
    d = to_et(datetime.now(timezone.utc))[0]
    return f"{d.strftime('%A')}, {d.strftime('%B')} {d.day}, {d.year}"


def issue_no():
    return (to_et(datetime.now(timezone.utc))[0].date() - datetime(2026, 10, 20).date()).days + 1


def clean_links(html_, path):
    """Ссылки сразу на конечный адрес (/t/name, а не t/name.html → переадресация): Google не видит лишних переадресаций."""
    base = path.rsplit("/", 1)[0] + "/" if "/" in path else ""
    def fix(m):
        up, link, anchor = m.group(1), m.group(2), m.group(3) or ""
        if up:                                    # ../x/name.html — от корня сайта
            full = link
        else:                                     # name.html или t/name.html — относительно текущей папки
            full = base + link
        full = "" if full in ("index", "") else full
        return f'href="/{full}{anchor}"'
    html_ = re.sub(r'href="(?:\.\./)*index\.html"', 'href="/"', html_)
    return re.sub(r'href="((?:\.\./)*)([\w/-]+?)\.html(#[^"]*)?"', fix, html_)


def page(title, desc, body, path, depth, extra_head="", og_img=""):
    return clean_links(_page(title, desc, body, path, depth, extra_head, og_img), path)


def _page(title, desc, body, path, depth, extra_head="", og_img=""):
    up = "../" * depth
    canon = SITE_URL + "/" + path.replace("index.html", "").replace(".html", "")
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="max-image-preview:large">
<title>{E(title)}</title><meta name="description" content="{E(desc)}">
<link rel="canonical" href="{E(canon)}"><link rel="alternate" type="application/rss+xml" title="{SITE_NAME}" href="{up}feed.xml">
{f'<meta property="og:image" content="{E(SITE_URL + "/" + og_img)}"><meta name="twitter:card" content="summary_large_image">' if og_img else ''}<meta property="og:title" content="{E(title)}"><meta property="og:description" content="{E(desc)}"><meta property="og:type" content="website">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=League+Gothic&family=Literata:ital,opsz,wght@0,7..72,400;0,7..72,600;1,7..72,400&family=Old+Standard+TT:ital,wght@0,400;0,700;1,400&family=UnifrakturMaguntia&display=swap" rel="stylesheet">
<style>{CSS}</style>{ga_snippet()}{"" if path in NO_ADS else ads_head()}{extra_head}</head><body><div class="wrap">
<header class="top"><div class="mast"><div class="ear">Late Edition<b>Every Trend</b>Explained around the clock</div>
<div><a class="brand" href="{up}index.html">The Trend Rundown</a><div class="motto">“{E(TAGLINE)}”</div></div>
<div class="ear">Price<b>Free</b>All the news America searches</div></div>
<div class="dateline"><span>Vol. I · No. {issue_no()}</span><span>{E(today_line())}</span><span>United States Edition · Price: Free</span></div>
<nav><a href="{up}index.html">Trending now</a>{f'<a href="{up}cast.html">Cast guides</a>' if HAS_CAST else ''}{f'<a href="{up}explained.html">Explained</a>' if HAS_EXPLAINED else ''}{"".join(f'<a href="{up}c/{c}.html">{E(CATS[c])}</a>' for c in NAV_CATS)}<a href="{up}archive.html">Archive</a></nav></header>
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


_SHAPE = {}


def shape(f):
    """ Вертикальное фото (портрет) показываем целиком, а не обрезаем — чтобы не резать лица. """
    if f in _SHAPE:
        return _SHAPE[f]
    cls = ""
    try:
        from PIL import Image
        with Image.open(os.path.join(OUT, f)) as im:
            w, h = im.size
        cls = ' class="whole"' if h > w * 0.8 else ""
    except Exception:
        pass
    _SHAPE[f] = cls
    return cls


LISTEN = True    # кнопка «Послушать статью»: читает текст голосом, встроенным в телефон/компьютер (бесплатно)


def listen_html():
    if not LISTEN:
        return ""
    return r"""<div class="ls"><button type="button" id="ls-b" hidden>&#9654; Listen to this article</button><button type="button" id="ls-s" hidden>&#9632; Stop</button></div>
<script>(function(){var S=window.speechSynthesis,b=document.getElementById('ls-b'),s=document.getElementById('ls-s');
if(!S||!b)return;b.hidden=false;var items=[],k=0,on=false,paused=false,HL=!!(window.CSS&&CSS.highlights&&window.Highlight),cur=null;
function voice(){var v=S.getVoices().filter(function(x){return /^en[-_]US/i.test(x.lang)});
var male=/andrew|christopher|guy|davis|eric|brian|roger|steffan|aaron|evan|tom\b|alex\b|fred|daniel|james|ryan/i,good=/natural|neural|premium|enhanced|online/i;
var c=v.filter(function(x){return male.test(x.name)&&good.test(x.name)});if(c.length)return c[0];
c=v.filter(function(x){return male.test(x.name)});if(c.length)return c[0];
c=v.filter(function(x){return good.test(x.name)});return c[0]||v[0]||null;}
function collect(){var a=document.querySelector('article'),out=[];if(!a)return out;
var els=a.querySelectorAll('h1,.deck2,.answer p,p,h2,h3,li');
for(var i=0;i<els.length;i++){var e=els[i];
if(e.closest('.meta,figure,.ls,.rx,.ad,.list,.ct,.byline,.grid,.card,.chips,.xlinks,aside')||e.classList.contains('meta')||e.classList.contains('byline'))continue;
if(e.tagName=='H2'&&/sources|trend data|explained|more in|also trending/i.test(e.textContent))break;
if(e.querySelector('p,li'))continue;
var tx=e.textContent,re=/[^.!?]+[.!?]*["'”]?\s*/g,m;
while((m=re.exec(tx))){var st=m.index,en=m.index+m[0].length,piece=m[0].trim();if(!piece||!/[a-z0-9]/i.test(piece))continue;
st+=m[0].length-m[0].replace(/^\s+/,'').length;out.push({el:e,start:st,end:st+piece.length,text:piece});}}
return out;}
function range(el,a,z){var w=document.createTreeWalker(el,NodeFilter.SHOW_TEXT),n,pos=0,r=document.createRange(),sa=false;
while((n=w.nextNode())){var L=n.nodeValue.length;
if(!sa&&a<=pos+L){r.setStart(n,Math.max(0,a-pos));sa=true;}
if(sa&&z<=pos+L){r.setEnd(n,Math.max(0,z-pos));return r;}pos+=L;}return sa?r:null;}
function mark(it,ws,we){if(HL){var r=range(it.el,it.start,it.end);if(r)CSS.highlights.set('ls-s',new Highlight(r));
if(ws!=null){var r2=range(it.el,it.start+ws,it.start+we);if(r2)CSS.highlights.set('ls-w',new Highlight(r2));}else CSS.highlights.delete('ls-w');}
else{if(cur&&cur!==it.el)cur.classList.remove('ls-cur');it.el.classList.add('ls-cur');}cur=it.el;}
function clear(){if(HL){CSS.highlights.delete('ls-s');CSS.highlights.delete('ls-w');}if(cur)cur.classList.remove('ls-cur');cur=null;}
function view(el){var r=el.getBoundingClientRect();if(r.top<70||r.bottom>window.innerHeight-70)el.scrollIntoView({block:'center',behavior:'smooth'});}
function next(){if(!on)return;if(k>=items.length){stop();return;}var it=items[k++];
var u=new SpeechSynthesisUtterance(it.text),v=voice();if(v)u.voice=v;u.lang='en-US';u.rate=0.93;u.pitch=0.85;
u.onstart=function(){mark(it);view(it.el);};
u.onboundary=function(e){if(e.name&&e.name!='word')return;var i0=e.charIndex,L=e.charLength||((it.text.slice(i0).match(/^\S+/)||[''])[0].length);mark(it,i0,i0+L);};
u.onend=next;u.onerror=next;S.speak(u);}
function stop(){on=false;paused=false;S.cancel();k=0;clear();b.innerHTML='&#9654; Listen to this article';s.hidden=true;}
b.onclick=function(){if(!on){on=true;items=collect();k=0;s.hidden=false;b.innerHTML='&#10074;&#10074; Pause';next();}
else if(!paused){S.pause();paused=true;b.innerHTML='&#9654; Continue';}else{S.resume();paused=false;b.innerHTML='&#10074;&#10074; Pause';}};
s.onclick=stop;window.addEventListener('pagehide',stop);if(S.onvoiceschanged!==undefined)S.onvoiceschanged=function(){};})();</script>"""


def mini_cards(items):
    out = []
    for r in items:
        img = (r.get("img") or {}).get("file")
        out.append(f'<a class="card" href="{E(r["slug"])}.html">'
                   + (f'<img{shape(img)} src="../{E(img)}" alt="" loading="lazy">' if img else "")
                   + f'<div class="card-top"><span class="num">{E(fmt_et(r.get("last_seen", r["first_seen"])).split(",")[0])}</span>'
                   f'<span class="chip-s">{E(peak_label(r))}</span></div>'
                   f'<h3>{E(r["term"])}</h3><p class="head">{E((r.get("ai") or {}).get("headline", ""))}</p></a>')
    return '<div class="grid">' + "".join(out) + "</div>"


EXPLAINERS = {}   # заполняется при сборке сайта: объяснения, видимые на сайте


_GENERIC = {"event", "events", "the", "a", "an", "of", "in", "on", "and", "rule", "law", "act", "bill", "game", "match",
            "tournament", "stadium", "bridge", "company", "show", "series", "season", "team", "club", "new", "us", "u.s."}


def anchor_phrases(x):
    """Каким словом из текста ссылаться на объяснение: само название, слова в кавычках из заголовка,
    затем самые длинные куски названия («Pro and tell Apple event» → «Pro and tell»)."""
    out = []
    for q in re.findall(r'["“]([^"”]{3,60})["”]', x.get("title", "")):
        out.append(q.strip())
    subj = x.get("subject", "").strip()
    out.append(subj)
    w = subj.split()
    for size in range(len(w) - 1, 1, -1):         # куски не короче двух слов: одно слово («Apple») слишком общее
        for i in range(0, len(w) - size + 1):
            part = w[i:i + size]
            core = [p for p in part if p.lower() not in _GENERIC]
            if not core or part[0].lower() in _GENERIC or part[-1].lower() in _GENERIC:
                continue
            out.append(" ".join(part))
    seen, res = set(), []
    for p in out:
        if p and p.lower() not in seen:
            seen.add(p.lower()); res.append(p)
    return res


SHOW_REACTIONS = False     # True — снова показать смайлики-реакции под статьями
REACTIONS = ["👍", "👎", "😂", "😮", "😢", "😡", "❤️", "🤔", "🔥", "👏"]


def reactions_html(page_key):
    if not SHOW_REACTIONS:
        return ""                       # смайлики под статьями выключены
    """Ряд смайликов под статьёй со счётчиками (счёт хранится в Cloudflare, см. worker.js)."""
    btns = "".join(f'<button type="button" class="rx-b" data-e="{i}" aria-label="{e}"><span class="rx-e">{e}</span>'
                   f'<span class="rx-n" data-n="{i}"></span></button>' for i, e in enumerate(REACTIONS))
    return (f'<div class="rx" data-p="{E(page_key)}"><div class="rx-row">{btns}</div></div>'
            "<script>(function(){var b=document.querySelector('.rx');if(!b)return;var p=b.dataset.p,k='rx:'+p,mine=null;"
            "try{mine=localStorage.getItem(k)}catch(e){}"
            "function show(d){if(!d||!d.counts)return;d.counts.forEach(function(n,i){var s=b.querySelector('[data-n=\"'+i+'\"]');"
            "if(s)s.textContent=n>0?n:''});b.querySelectorAll('.rx-b').forEach(function(x){x.classList.toggle('on',x.dataset.e===String(mine))})}"
            "fetch('/api/react?p='+encodeURIComponent(p)).then(function(r){return r.json()}).then(show).catch(function(){});"
            "b.addEventListener('click',function(ev){var x=ev.target.closest('.rx-b');if(!x)return;mine=x.dataset.e;"
            "try{localStorage.setItem(k,mine)}catch(e){}"
            "fetch('/api/react',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({p:p,e:+mine})})"
            ".then(function(r){return r.json()}).then(show).catch(function(){})})})();</script>")


OUTLET = (r"(?:The )?(?:Associated Press|AP|Reuters|CNN|CNBC|NBC(?: News| Sports)?|CBS(?: News| Sports)?|ABC(?: News)?|Fox(?: News| Sports| News Digital)?|"
          r"NPR|PBS|ESPN|Yahoo(?: Sports| Finance| News)?|USA Today|The New York Times|New York Times|NYT|Washington Post|"
          r"Wall Street Journal|WSJ|Bloomberg(?: News)?|BBC(?: Sport| News)?|The Guardian|Guardian|The Athletic|Athletic|Sports Illustrated|"
          r"Variety|People(?:\.com)?|TMZ(?: Sports)?|E! News|Entertainment Weekly|Billboard|Forbes|The Verge|TechCrunch|CNET|"
          r"MarketWatch|Axios|Politico|The Hill|Newsweek|RotoWire|OneFootball|HoopsHype|MLB\.com|NFL\.com|NBA\.com|Deadline|"
          r"Hollywood Reporter|The Independent|Daily Mail|[KW](?!NBA)[A-Z]{3}(?:-TV)?)")


META_RE = re.compile(r"(?i)\b(the|these|available|our) sources?\b|\bsources? reviewed\b|\bheadlines?\b|according to the (match )?report|"
                     r"\b(those|the|these|other) reports? (point|say|said|suggest)|covered only by|not available from|"
                     r"\boutlets? (say|said|report|described|published)|\bheadlined\b|\bin our feed\b|\bfull (article|text|stories)\b")


def drop_meta(para):
    """Убираем фразы о самих источниках («в заголовке сказано», «источники не сообщают»)."""
    sents = re.split(r"(?<=[.!?])\s+", para)
    own = re.compile(OUTLET + r"(?:'s|’s) (?:live |latest |match )?(?:coverage|report|preview|story|headline|article|guide|piece|analysis)")
    keep = [x for x in sents if not META_RE.search(x) and not own.search(x)]
    return " ".join(keep)


def scrub_outlets(s):
    """Убираем из текста упоминания изданий: «по данным CNN», «как сообщает ESPN»."""
    if not s:
        return s
    o = OUTLET
    pats = [
        (rf",? (?:according to|per|citing|as reported by) (?:a |an |the )?(?:report(?:s|ing)? (?:from|by) )?{o}(?:'s [\w ]{{1,30}}?)?(?:, which [^,.;]*)?(?=[,.;])", ""),
        (rf"(?:^|(?<=[.!?] ))(?:According to|Per) (?:a |an |the )?(?:report(?:s|ing)? (?:from|by) )?{o}(?:'s [\w ]{{1,30}}?)?, (\w)", r"\1"),
        (rf"(?:^|(?<=[.!?] )){o}(?: and {o})?,?(?: citing [^,]+,)? (?:reported|reports|said|says|wrote|noted|described|published)(?: that)? (\w)", r"\1"),
        (rf",? {o} (?:reported|reports|said|says|wrote|noted)(?=[,.])", ""),
        (r"(?i),? according to (?:the |one |a |an )?(?:[\w-]+ ){0,3}(?:reports?|sources?|news|coverage|headlines?)(?: (?:from|on) [^,.]+)?(?=[,.])", ""),
        (rf"(?:^|(?<=[.!?] ))According to (?:a |an |the )?(?:{o} )?(?:[\w-]+ )?(?:report|reports|story|coverage)(?: (?:from|on) [^,]+(?:, \d{{4}})?)?, (\w)", r"\1"),
    ]
    for a, b in pats:
        s = re.sub(a, b, s)
    s = re.sub(r"(^|[.!?]\s+)([a-z])", lambda m: m.group(1) + m.group(2).upper(), s)
    return re.sub(r"\s{2,}", " ", s).replace(" ,", ",").strip()


def photo_who(t, img):
    """Кто на фото: если фото взято со страницы Википедии другого человека (Том Скеррит в статье «Julia Roberts») — подписываем."""
    if img.get("who"):
        return img["who"]
    if img.get("generic") or not img.get("wiki"):
        return ""
    title = re.sub(r"\s*\(.*?\)", "", urllib.parse.unquote(img["wiki"].rsplit("/", 1)[-1]).replace("_", " ")).strip()
    return "" if _match(t["term"], title) else title


def source_line(t, ai):
    """Короткая строка источников: только названия изданий со ссылками, без их заголовков."""
    seen, links = set(), []
    for a in sorted(t["articles"], key=lambda a: a["time"], reverse=True):
        if a.get("source") and a["source"] not in seen and "news.google.com" not in a["url"]:
            seen.add(a["source"]); links.append((a["source"], a["url"]))
    for a in sorted(t["articles"], key=lambda a: a["time"], reverse=True):
        if a.get("source") and a["source"] not in seen:
            seen.add(a["source"]); links.append((a["source"], a["url"]))
    if ai and ai.get("dug") and ai.get("behind"):
        for h, ti, u in ai["dug"]:
            if h not in seen:
                seen.add(h); links.append((h, u))
    if not links:
        return ""
    return ('<p class="meta" style="margin-top:26px">Sources: ' + " · ".join(
        f'<a href="{E(u)}" target="_blank" rel="noopener nofollow">{E(n)}</a>' for n, u in links[:12]) + "</p>")


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
    if ai:
        ai = dict(ai)
        for k in ("why", "behind", "summary", "next", "unknown", "headline"):
            if isinstance(ai.get(k), str):
                ai[k] = "\n\n".join(drop_meta(scrub_outlets(x)) for x in ai[k].replace("\\n", "\n").split("\n\n"))
        ai["key_points"] = [k for k in (drop_meta(scrub_outlets(x)) for x in ai.get("key_points", [])) if k]
    ai_html = ""
    if ai:
        dl = re.sub(r"[^\w .,'-]", "", ai.get("dateline", "") or "").strip(" ,")[:40]
        if dl:
            d0 = to_et(datetime.fromisoformat(t["first_seen"]))[0]
            mon = ["Jan.", "Feb.", "March", "April", "May", "June", "July", "Aug.", "Sept.", "Oct.", "Nov.", "Dec."][d0.month - 1]
            dl = f'<b class="dl">{E(dl.upper() if "," not in dl else dl.split(",")[0].upper() + "," + dl.split(",", 1)[1])}, {mon} {d0.day}</b> — '
        pl = [f'<p{" class=dc" if i == 0 and not dl else ""}>{dl if i == 0 else ""}{E(p)}</p>'
              for i, p in enumerate(x for x in ai.get("summary", "").replace("\\n", "\n").split("\n\n") if x.strip())]
        # ссылка на объяснение прямо в тексте: первое упоминание термина становится ссылкой
        for x in xs:
            done_x = False
            for phrase in anchor_phrases(x):
                pat = re.compile(r"(?<![\w>])(" + re.escape(E(phrase)) + r")(?![\w<])", re.I)
                for i, ptxt in enumerate(pl):
                    new, n = pat.subn(lambda m: f'<a class="xl" href="../x/{E(x["slug"])}.html" title="{E(x["title"])}">{m.group(1)}</a>', ptxt, count=1)
                    if n:
                        pl[i] = new; done_x = True
                        break
                if done_x:
                    break
        paras = "".join(pl[:1]) + ad("in_article") + "".join(pl[1:])
        kp = "".join(f"<li>{E(k)}</li>" for k in ai.get("key_points", []))
        unk = ai.get("unknown", "")
        why = ai.get("why", "")
        asked = "".join(f"<li>{E(q)}</li>" for q in ai.get("asked", []))
        peak_ = max(t["traffic"], key=lambda x: x[1]) if t["traffic"] else None
        facts_line = (f'Trending in the US since {E(fmt_et(t["first_seen"]))}'
                      + (f' · about {E(peak_[2])} searches' if peak_ and peak_[2] else "")
                      + (f' · covered by {len(srcs)} news outlets' if len(srcs) > 1 else ""))
        if why:
            ai_html = (f'<div class="box answer"><p style="margin:0">{E(why)}</p></div>'
                       f'<p class="meta" style="margin:8px 0 18px">{facts_line}</p>'
                       + (f'<h2>The story behind it</h2>' + "".join(f"<p>{E(p)}</p>" for p in ai["behind"].split("\n\n") if p.strip())
                          if ai.get("behind") else "")
                       + f'<h2>The background</h2>{paras}'
                       + (f"<h2>What happens next</h2><p>{E(ai['next'])}</p>" if ai.get("next") and not re.search(
                          r"(?i)sources? (do|does) not|not (stated|given|say|said)|no (date|details)|unclear", ai["next"]) else "")
                       + (f"<h2>What else people are searching</h2><ul>{asked}</ul>" if asked else ""))
        else:
            ai_html = paras
        ai_html = (ai_html
                   + (f"<h2>Key facts</h2><ul>{kp}</ul>" if kp else "")
                   + (f"<h2>What we don't know yet</h2><p>{E(unk)}</p>" if unk else "")
                   + f'<p class="meta">Updated {E(fmt_et(ai["made"]))}.</p>')
    img = t.get("img"); card = t.get("card")
    if img:
        hero = (f'<figure class="hero"><img{shape(img["file"])} src="../{E(img["file"])}" alt="{E(t["term"])}" loading="eager">'
                f'<figcaption>{(E(photo_who(t, img)) + ". ") if photo_who(t, img) else ""}{"Illustration" if img.get("generic") else "Photo"}: {E(img["credit"])} / <a href="{E(img["src"])}" target="_blank" rel="noopener">{E(img["license"])}</a>, via Wikimedia Commons</figcaption></figure>')
    else:   # обложка-заглушка на странице не показывается, только в превью ссылки (og:image)
        hero = ""
    side = ad("sidebar")
    body = f"""<div class="tp{' side' if side else ''}"><article>
<p class="meta"><a href="../index.html">{SITE_NAME}</a> › {(f'<a class="cat" href="../c/{t["cat"]}.html">{E(CATS[t["cat"]])}</a> · ') if t.get("cat") in CATS else ''}updated {E(fmt_et(upd))}</p>
<h1>{E(t['term'])}</h1>
<p class="deck">Why it is trending in America today</p>
{('<p class="deck2">' + E(ai.get("headline", "")) + '</p>') if ai and ai.get("headline") else ''}
<hr class="dash"><p class="byline">The Trend Rundown</p>
{listen_html() if ai else ""}
{hero}
<div class="cols">{ai_html}</div>
{reactions_html("t/" + t["slug"]) if ai else ""}
{xblock}
{more}
<h2>Trend data</h2>
<div class="box"><p style="margin:0">{summ}</p>{('<p class="meta" style="margin:10px 0 0">Search interest while it trended</p>' + sp) if sp else ''}</div>
{ad("middle")}
{source_line(t, ai)}
{ad("multiplex") if ai else ""}
{('<h2>Other trending topics</h2><div class="chips">' + rel + '</div>') if rel else ''}
</article><aside>{side}</aside></div>"""
    desc = short_desc(ai["why"], 160) if ai and ai.get("why") else short_desc((ai["headline"] + ". " if ai else "") + f"Why {t['term']} is trending in the US right now: what happened, who's reporting it, and links to {len(srcs) or 'the'} sources.", 160)
    head = f'<script type="application/ld+json">{json.dumps(ld)}</script>'
    if img:
        ld["image"] = f"{SITE_URL}/{img['file']}"
    elif card:
        ld["image"] = f"{SITE_URL}/{card}"
    head = f'<script type="application/ld+json">{json.dumps(ld)}</script>'
    title = (f"Why is {t['term']} trending? {ai['headline']}" if ai and ai.get("why") and ai.get("headline")
             else f"{t['term']}: {ai['headline']}" if ai and ai.get("headline") else f"Why is {t['term']} trending?")
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


def snip(t, n=220):
    """Начало заметки для первой полосы: причина тренда или первые фразы текста."""
    ai = t.get("ai") or {}
    s = ai.get("why") or (ai.get("summary", "").split("\n\n")[0] if ai.get("summary") else "")
    return short_desc(s, n) if s else ""


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
                + (f'<img{shape(img)} src="{E(img)}" alt="" loading="lazy">' if img else "")
                + f'<div class="card-top"><span class="num">{E(label)}</span><span class="chip-s">{E(chip)}</span></div>'
                f'<h3>{E(t["term"])}</h3><p class="head">{E(head)}</p>'
                + (f'<p class="snip">{E(snip(t))}</p>' if snip(t) else "")
                + f'<p class="meta">{E(", ".join(srcs[:2]))}</p></a>')

    top = live or still
    parts = []
    if top:
        t = top[0]; srcs, head = info(t)
        img = (t.get("img") or {}).get("file")
        tr = (t["traffic"][-1][2] if live else peak_label(t)) if t["traffic"] else ""
        parts.append(f'<a class="lead{" has-img" if img else ""}" href="t/{E(t["slug"])}.html">'
                     + (f'<img{shape(img)} src="{E(img)}" alt="">' if img else "")
                     + f'<div class="lead-txt"><span class="badge">#1 · {E(tr)} searches</span>'
                     f'<h2 class="lead-term">{E(t["term"])}</h2><p class="lead-head">{E(head)}</p>'
                     + (f'<hr class="dash" style="margin:8px 0"><p class="snip">{E(snip(t, 420))}</p>' if snip(t) else "")
                     + f'<p class="meta">Since {E(fmt_et(t["first_seen"]))} · {E(", ".join(srcs[:3]))}</p></div></a>')
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
                     + (f'<img{shape(img)} src="../{E(img)}" alt="" loading="lazy">' if img else "")
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
    x = dict(x)
    for k in ("answer", "body", "in_the_news"):
        x[k] = "\n\n".join(scrub_outlets(p) for p in (x.get(k) or "").split("\n\n"))
    paras = "".join(f"<p>{E(p)}</p>" for p in x["body"].split("\n\n") if p.strip())
    faq = []
    for f in x.get("faq", []):
        q = f.get("q", "").strip().rstrip("?")
        if q and f.get("a"):
            faq.append({"q": q[0].upper() + q[1:] + "?", "a": f["a"]})
    faq = [f for f in faq if not re.search(r"(?i)\b(should (i|you|runners|people)|eat|diet|cramp|injur|bet|odds|invest|"
                                           r"lawyer|sue\b|medic|dose|avoid)", f["q"])]
    faq_html = "".join(f"<h3>{E(f['q'])}</h3><p>{E(f['a'])}</p>" for f in faq)
    newslist = "".join(f'<li><a href="../t/{E(n["slug"])}.html">{E(n["term"])}</a> — '
                       f'{E((n.get("ai") or {}).get("headline", ""))} <span class="meta">{E(fmt_et(n["first_seen"]).split(",")[0])}</span></li>'
                       for n in news[:12])
    seen_s = []
    for s_, ti, u in x.get("links", []):
        if s_ and s_ not in [a for a, _ in seen_s]:
            seen_s.append((s_, u))
    src = " · ".join(f'<a href="{E(u)}" target="_blank" rel="noopener nofollow">{E(s_)}</a>' for s_, u in seen_s[:8])
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
{listen_html()}
<div class="box answer"><p style="margin:0">{E(x["answer"])}</p></div>
<h2>Why it's in the news</h2><p>{E(x["in_the_news"])}</p>
{('<ul class="list">' + newslist + '</ul>') if newslist else ''}
{ad("in_article")}
<h2>Background</h2>{paras}
{('<h2>What people are asking</h2>' + faq_html) if faq_html else ''}
{reactions_html("x/" + x["slug"])}
{ad("middle")}
{('<p class="meta" style="margin-top:26px">Sources: ' + src + '</p>') if src else ''}
<p class="meta">Updated {E(fmt_et(x["made"]))}.</p>
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
    "about.html": ("About", f"<h1>About {SITE_NAME}</h1>"
        f"<p>{SITE_NAME} is an independent news explainer for readers in the United States. Every day we follow what Americans are searching for on Google and, for each trending topic, publish a short, plain-English rundown of what actually happened, plus explainers that answer the questions people ask next (who is this person, what is this law, where is this place).</p>"
        "<h2>How we work</h2><p>Every rundown is built only from reporting by established news organizations, which are linked at the bottom of each page so you can check the original. Drafts are written with the help of AI and then checked by a separate review step against those sources; anything that cannot be backed by a source is removed or the page is not published. We do not publish rumors, private individuals' personal details or sexual, violent or extremist content.</p>"
        "<h2>Corrections</h2><p>If something on a page is wrong, email us and we will fix or remove it, usually within 24 hours. Pages are updated automatically as new reporting appears.</p>"
        f"<h2>Contact</h2><p>{CONTACT_EMAIL}</p>"),
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


GENERIC_TERMS = {"news", "news today", "today news", "tv", "weather", "sports", "sport", "crime", "jobs", "job", "flights",
                 "fitness", "schools", "school", "music", "movies", "games", "politics", "world", "business", "us",
                 "usa", "money", "health", "food", "travel", "shopping", "stocks", "election", "elections", "breaking news",
                 "internet", "google", "facebook", "youtube", "weather today", "score", "scores", "game tonight", "live"}


def generic_term(term):
    return term.strip().lower() in GENERIC_TERMS


def visible(store):
    ub = user_blocks()
    out = {}
    for s, t in store["topics"].items():
        if t.get("blocked") or bad_text(t["term"], ub) or not t["articles"] or generic_term(t["term"]):
            continue
        if ONLY_WITH_SUMMARY and not t.get("ai"):
            continue
        ai = t.get("ai") or {}
        old_txt = ai.get("summary", "") + " " + ai.get("headline", "")
        if len(ai.get("summary", "")) < 150 or ai.get("key_points") == ["x"]:
            continue                     # битый текст
        if (ai.get("rules") or 0) < 6 and ai.get("rw_tried") == RULES_V and re.search(
                r"(?i)appears? to be tied|searches for .{0,40}(appear|seem)|may be why|is drawing search|several (separate|unrelated) headlines"
                r"|only (the )?headlines? (were|was) available|based (only )?on the headline|headline alone|headlines? only"
                r"|readers (looking|who want)|check the full (articles?|reports?)", old_txt):
            continue                     # старый текст-догадка, переписать по новым правилам не вышло — не показываем
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
    global HAS_EXPLAINED, HAS_CAST
    HAS_EXPLAINED = bool(ex)
    pv = {k: x for k, x in store.get("previews", {}).items() if x.get("slug") and not bad_text(x["title"], ub)}
    HAS_CAST = bool(pv)
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
    for x in pv.values():
        w(f"w/{x['slug']}.html", build_cast(x))
    if pv:
        w("cast.html", build_cast_index(pv))
    w("index.html", build_index(store))
    w("archive.html", build_archive(store))
    for fn, (title, body) in STATIC.items():
        w(fn, page(f"{title} | {SITE_NAME}", f"{title} — {SITE_NAME}", body, fn, 0))
    w("404.html", page(f"Not found | {SITE_NAME}", "Page not found", "<h1>Page not found</h1><p><a href='index.html'>See what's trending now</a></p>", "404.html", 0))
    urls = ([f"{SITE_URL}/", f"{SITE_URL}/archive"] + ([f"{SITE_URL}/explained"] if ex else [])
            + [f"{SITE_URL}/c/{c}" for c in counts]
            + [f"{SITE_URL}/x/{x['slug']}" for x in ex.values()]
            + ([f"{SITE_URL}/cast"] if pv else []) + [f"{SITE_URL}/w/{x['slug']}" for x in pv.values()]
            + [f"{SITE_URL}/t/{t['slug']}" for t in topics.values()])
    lm = {f"{SITE_URL}/t/{t['slug']}": t.get("last_seen", t["first_seen"]) for t in topics.values()}
    lm.update({f"{SITE_URL}/x/{x['slug']}": x["made"] for x in ex.values()})
    lm.update({f"{SITE_URL}/w/{x['slug']}": x["made"] for x in pv.values()})
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
    new_urls += [f"{SITE_URL}/w/{x['slug']}" for x in pv.values() if x.pop("new", False)]
    if new_urls:
        orig["_pending_out"] = new_urls
    w("sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
      + "".join(f"<url><loc>{E(u)}</loc>" + (f"<lastmod>{lm[u]}</lastmod>" if u in lm else "") + "</url>" for u in urls) + "</urlset>")
    if ADSENSE_CLIENT:
        w("ads.txt", f"google.com, {ADSENSE_CLIENT.replace('ca-', '')}, DIRECT, f08c47fec0942fa0\n")
    w("robots.txt", f"User-agent: *\nAllow: /\nDisallow: /api/\nSitemap: {SITE_URL}/sitemap.xml\nSitemap: {SITE_URL}/sitemap-news.xml\n")
    items = sorted(topics.values(), key=lambda t: t["first_seen"], reverse=True)[:50]
    w("feed.xml", '<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
      f"<title>{SITE_NAME}</title><link>{SITE_URL}</link><description>{E(TAGLINE)}</description>"
      + "".join(f"<item><title>Why is {E(t['term'])} trending?</title><link>{SITE_URL}/t/{t['slug']}</link>"
                f"<guid>{SITE_URL}/t/{t['slug']}</guid><pubDate>{datetime.fromisoformat(t['first_seen']).strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate></item>" for t in items)
      + "</channel></rss>")
    return len(topics)



# ---------- На опережение: «кто играет» в фильмах и сериалах, которые выходят в ближайшие дни ----------
# Сериалы — TVmaze (CC BY-SA 4.0, можно для любых целей со ссылкой), фильмы и факты об актёрах — Wikidata (CC0). Ключи не нужны.
PREVIEW = True                 # страницы «актёры нового фильма/сериала» до премьеры
MAX_PREVIEWS_PER_DAY = 4       # сколько таких страниц в сутки
PREVIEW_DAYS_AHEAD = 10        # смотрим премьеры на столько дней вперёд
PREVIEW_CAST = 8               # сколько актёров описывать подробно
SKIP_BIGGEST = 2               # пропускать столько самых громких премьер (фильмов и сериалов) — там не пробиться
PREVIEW_ROLES = 60             # для скольких ролей сделать вопрос «кто играет …» (включая эпизодические)
PREVIEW_ROLES_KNOWN = 30       # для скольких второстепенных актёров узнать «где ещё снимался»
PREVIEW_PHOTOS = 4             # для скольких первых актёров искать свободное фото
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December"]
HAS_CAST = False
BAD_Q = re.compile(r"(?i)net worth|salary|nude|naked|hot\b|sexy|feet|shirtless|bikini|gay|lesbian|trans\b|religion|"
                   r"jewish|muslim|christian|ethnic|race|nationality|politic|trump|biden|dead|death|died|sick|ill\b|"
                   r"cancer|disease|surgery|weight|arrest|jail|dui|scandal|instagram|tiktok|twitter|address|house|phone|"
                   r"young|before and after|pregnan")
STREAMERS = re.compile(r"(?i)netflix|amazon|prime video|apple|hulu|disney\+|max\b|hbo max|peacock|paramount\+")


def nice_date(d):
    d = datetime.strptime(d[:10], "%Y-%m-%d")
    return f"{MONTHS[d.month - 1]} {d.day}, {d.year}"


def age_on(born, day):
    b = datetime.strptime(born[:10], "%Y-%m-%d"); d = datetime.strptime(day[:10], "%Y-%m-%d")
    return d.year - b.year - ((d.month, d.day) < (b.month, b.day))


def tvmaze(path, **params):
    url = "https://api.tvmaze.com" + path + ("?" + urllib.parse.urlencode(params, doseq=True) if params else "")
    for attempt in range(3):
        try:
            return json.loads(get(url, timeout=30).decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code == 429:                     # просят не спешить
                time.sleep(3)
                continue
            if e.code == 404:
                return None
            raise
    return None


def sparql(q):
    url = "https://query.wikidata.org/sparql?" + urllib.parse.urlencode({"query": q, "format": "json"})
    data = json.loads(get(url, timeout=60).decode("utf-8", "replace"))
    return [{k: v.get("value", "") for k, v in row.items()} for row in data.get("results", {}).get("bindings", [])]


def qid(uri):
    return (uri or "").rsplit("/", 1)[-1]


def strip_html(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def clean_role(s):
    s = re.sub(r"(?i)\s*\((uncredited|credit only|archive footage)\)", "", s or "").strip(" /,")
    return "" if re.fullmatch(r"(?i)(self|himself|herself|themselves|additional voices?|extra|various)?", s) else s


# ----- сериалы (TVmaze) -----
def tv_cast(show_id, season=None):
    """Основной состав сериала и (если серии уже вышли) приглашённые актёры этого сезона."""
    main, seen = [], set()
    for c in tvmaze(f"/shows/{show_id}/cast") or []:
        p, ch = c.get("person") or {}, c.get("character") or {}
        name = clean_role(ch.get("name", ""))
        if c.get("self") or not p.get("id") or p["id"] in seen:
            continue
        seen.add(p["id"])
        main.append({"id": f"tvm{p['id']}", "pid": p["id"], "name": p.get("name", ""), "character": name,
                     "born": p.get("birthday") or "", "died": p.get("deathday") or "",
                     "country": ((p.get("country") or {}).get("name") or ""), "url": p.get("url", ""),
                     "voice": bool(c.get("voice"))})
    guests = []
    if season:
        try:
            eps = [e for e in (tvmaze(f"/shows/{show_id}/episodes") or []) if e.get("season") == season and e.get("airdate")
                   and e["airdate"] <= to_et(datetime.now(timezone.utc))[0].strftime("%Y-%m-%d")]
        except Exception:
            eps = []
        for e in eps[:12]:
            for c in tvmaze(f"/episodes/{e['id']}/guestcast") or []:
                p, ch = c.get("person") or {}, c.get("character") or {}
                name = clean_role(ch.get("name", ""))
                if c.get("self") or not p.get("id") or p["id"] in seen or not name:
                    continue
                seen.add(p["id"])
                guests.append({"id": f"tvm{p['id']}", "pid": p["id"], "name": p.get("name", ""), "character": name,
                               "born": p.get("birthday") or "", "died": p.get("deathday") or "",
                               "country": ((p.get("country") or {}).get("name") or ""), "url": p.get("url", ""),
                               "episode": f"S{e['season']}E{e.get('number') or '?'}", "voice": bool(c.get("voice"))})
            time.sleep(0.3)
    return main, guests


def tv_item(show, season, date):
    main, guests = tv_cast(show["id"], season if date <= to_et(datetime.now(timezone.utc))[0].strftime("%Y-%m-%d") else None)
    where = [x for x in [(show.get("webChannel") or {}).get("name"), (show.get("network") or {}).get("name")] if x]
    living = [c for c in main if not c["died"]]
    return {"key": f"tv-{show['id']}-s{season}", "type": "tv", "id": f"tvm{show['id']}", "show_id": show["id"],
            "season": season, "title": show.get("name", ""), "date": date, "release": "tv",
            "overview": strip_html(show.get("summary")), "genres": show.get("genres", []), "where": where[:2],
            "year": date[:4], "popularity": show.get("weight") or 0,
            "cast": [c for c in living if c["character"]][:PREVIEW_CAST] or living[:PREVIEW_CAST],
            "roles": [c for c in main + guests if c["character"] and not c["died"]][:PREVIEW_ROLES],
            "link": show.get("url", ""), "link_name": "TVmaze"}


def upcoming_tv(today, end):
    found = {}
    day = datetime.strptime(today, "%Y-%m-%d")
    while day.strftime("%Y-%m-%d") <= end:
        d = day.strftime("%Y-%m-%d")
        for path, params in (("/schedule", {"country": "US", "date": d}), ("/schedule/web", {"date": d})):
            try:
                eps = tvmaze(path, **params) or []
            except Exception as e:
                log(f"TVmaze {path} {d}: {e}")
                eps = []
            for e in eps:
                show = e.get("show") or (e.get("_embedded") or {}).get("show") or {}
                if e.get("number") != 1 or not show.get("id") or show.get("language") != "English":
                    continue                                   # нужна первая серия сезона
                ch = show.get("webChannel") or show.get("network") or {}
                country = ((ch.get("country") or {}).get("code")) or "US"   # Netflix и др. — без страны, они для всех
                if country != "US" or re.search(r"(?i)talk show|news|sports|game show", show.get("type", "")):
                    continue
                k = (show["id"], e.get("season", 1))
                if k not in found:
                    found[k] = (show, e.get("season", 1), d)
            time.sleep(0.3)
        day += timedelta(days=1)
    out = []
    for show, season, d in sorted(found.values(), key=lambda x: -(x[0].get("weight") or 0))[:15]:
        try:
            out.append(tv_item(show, season, d))
        except Exception as e:
            log(f"TVmaze {show.get('name')}: {e}")
    return out


# ----- фильмы (Wikidata) -----
def movie_item(fq, title="", date="", popularity=0, where=None):
    rows = sparql(f"""SELECT ?actor ?actorLabel ?charLabel ?charName ?ord ?links ?born ?died ?article WHERE {{
  wd:{fq} p:P161 ?st . ?st ps:P161 ?actor .
  OPTIONAL {{ ?st pq:P453 ?char }} OPTIONAL {{ ?st pq:P4633 ?charName }} OPTIONAL {{ ?st pq:P1545 ?ord }}
  OPTIONAL {{ ?actor wikibase:sitelinks ?links }} OPTIONAL {{ ?actor wdt:P569 ?born }} OPTIONAL {{ ?actor wdt:P570 ?died }}
  OPTIONAL {{ ?article schema:about ?actor ; schema:isPartOf <https://en.wikipedia.org/> }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }} }}""")
    people = {}
    for r in rows:
        a = qid(r.get("actor"))
        if not a or re.fullmatch(r"Q\d+", r.get("actorLabel", "")):
            continue                                            # у актёра нет английского имени
        ch = clean_role(r.get("charName") or ("" if re.fullmatch(r"Q\d+", r.get("charLabel", "")) else r.get("charLabel", "")))
        p = people.setdefault(a, {"id": a, "qid": a, "name": r["actorLabel"], "character": ch, "born": (r.get("born") or "")[:10],
                                  "died": r.get("died", ""), "ord": int(r["ord"]) if (r.get("ord") or "").isdigit() else 999,
                                  "links": int(r.get("links") or 0), "wiki_title": urllib.parse.unquote(qid(r.get("article", ""))).replace("_", " ")})
        if ch and not p["character"]:
            p["character"] = ch
    cast = sorted([p for p in people.values() if not p["died"]], key=lambda p: (p["ord"], -p["links"]))
    ov, link = "", f"https://www.wikidata.org/wiki/{fq}"
    try:
        art = sparql(f"SELECT ?a WHERE {{ ?a schema:about wd:{fq} ; schema:isPartOf <https://en.wikipedia.org/> }}")
        if art:
            t = urllib.parse.unquote(qid(art[0]["a"])).replace("_", " ")
            q = urllib.parse.urlencode({"action": "query", "prop": "extracts", "exintro": 1, "explaintext": 1, "titles": t,
                                        "format": "json", "formatversion": 2})
            ov = ((json.loads(get("https://en.wikipedia.org/w/api.php?" + q)).get("query", {}).get("pages") or [{}])[0]
                  .get("extract", ""))[:1500]
            link = "https://en.wikipedia.org/wiki/" + urllib.parse.quote(t.replace(" ", "_"))
    except Exception:
        pass
    where = where or []
    return {"key": f"movie-{fq}", "type": "movie", "id": fq, "title": title, "date": date,
            "release": "digital" if any(STREAMERS.search(w) for w in where) else "theaters", "where": where,
            "overview": ov, "genres": [], "year": date[:4], "popularity": popularity,
            "cast": cast[:PREVIEW_CAST], "roles": [p for p in cast if p["character"]][:PREVIEW_ROLES],
            "link": link, "link_name": "Wikipedia" if "wikipedia" in link else "Wikidata"}


def upcoming_movies(today, end):
    rows = sparql(f"""SELECT ?film ?filmLabel ?date ?links (GROUP_CONCAT(DISTINCT ?distLabel; separator="|") AS ?dist) WHERE {{
  VALUES ?type {{ wd:Q11424 wd:Q24869 wd:Q506240 }}
  ?film wdt:P31 ?type ; wikibase:sitelinks ?links ; p:P577 ?s . ?s ps:P577 ?date .
  OPTIONAL {{ ?s pq:P291 ?place }}
  FILTER(?date >= "{today}T00:00:00Z"^^xsd:dateTime && ?date <= "{end}T23:59:59Z"^^xsd:dateTime)
  FILTER(!BOUND(?place) || ?place = wd:Q30)
  FILTER NOT EXISTS {{ ?film p:P577 ?s2 . ?s2 ps:P577 ?d2 . ?s2 pq:P291 wd:Q30 . FILTER(?d2 < "{today}T00:00:00Z"^^xsd:dateTime) }}
  OPTIONAL {{ ?film wdt:P750 ?d . ?d rdfs:label ?distLabel . FILTER(LANG(?distLabel) = "en") }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}} GROUP BY ?film ?filmLabel ?date ?links ORDER BY DESC(?links) LIMIT 15""")
    out, seen = [], set()
    for r in rows:
        fq = qid(r["film"])
        if fq in seen or re.fullmatch(r"Q\d+", r.get("filmLabel", "")):
            continue
        seen.add(fq)
        try:
            out.append(movie_item(fq, r["filmLabel"], r["date"][:10], int(r.get("links") or 0),
                                  [d for d in (r.get("dist") or "").split("|") if d][:2]))
        except Exception as e:
            log(f"Wikidata фильм {r.get('filmLabel')}: {e}")
        time.sleep(0.5)
    return out


def upcoming_titles(today, end):
    """Фильмы и сериалы (новые и новые сезоны), которые выходят в США с today по end."""
    movies, tv = [], []
    try:
        movies = upcoming_movies(today, end)
    except Exception as e:
        log(f"Wikidata фильмы: {e}")
    try:
        tv = upcoming_tv(today, end)
    except Exception as e:
        log(f"TVmaze сериалы: {e}")
    movies.sort(key=lambda x: -x["popularity"]); tv.sort(key=lambda x: -x["popularity"])
    out = movies[SKIP_BIGGEST:] + tv[SKIP_BIGGEST:]     # самые громкие премьеры пропускаем: там нас обгонят крупные сайты
    return sorted(out, key=lambda x: x["date"])         # ближайшие премьеры — первыми


def refresh_item(x):
    """Свежие данные о вышедшем фильме/сериале (после премьеры добавляются роли и приглашённые актёры)."""
    it = x["item"]
    if it["type"] == "movie":
        return movie_item(it["id"], it["title"], it["date"], it.get("popularity", 0), it.get("where"))
    show = tvmaze(f"/shows/{it['show_id']}")
    return tv_item(show, it["season"], it["date"]) if show else None


# ----- факты об актёре -----
def wiki_person(name, title=""):
    """Статья Википедии об актёре: вступление (для ИИ) и номер в Wikidata."""
    params = {"action": "query", "prop": "extracts|pageprops", "exintro": 1, "explaintext": 1, "ppprop": "wikibase_item",
              "format": "json", "formatversion": 2, "redirects": 1}
    if title:
        params["titles"] = title
    else:
        params.update({"generator": "search", "gsrsearch": f"{name} actor", "gsrlimit": 3})
    try:
        pages = json.loads(get("https://en.wikipedia.org/w/api.php?" + urllib.parse.urlencode(params))).get("query", {}).get("pages", [])
    except Exception:
        return "", "", ""
    last = name.split()[-1].lower()
    for p in sorted(pages, key=lambda p: p.get("index", 0)):
        ex = p.get("extract", "")
        if last in p.get("title", "").lower() and re.search(r"(?i)\b(actor|actress|comedian|singer|performer|rapper|model|host|voice)\b", ex[:500]):
            return (ex[:2500], "https://en.wikipedia.org/wiki/" + urllib.parse.quote(p["title"].replace(" ", "_")),
                    (p.get("pageprops") or {}).get("wikibase_item", ""))
    return "", "", ""


def wd_person(q):
    """Из Wikidata: дата рождения, место рождения, супруги (действующие), смерть."""
    rows = sparql(f"""SELECT ?born ?died ?placeLabel ?spouseLabel ?end WHERE {{
  OPTIONAL {{ wd:{q} wdt:P569 ?born }} OPTIONAL {{ wd:{q} wdt:P570 ?died }} OPTIONAL {{ wd:{q} wdt:P19 ?place }}
  OPTIONAL {{ wd:{q} p:P26 ?ss . ?ss ps:P26 ?spouse . OPTIONAL {{ ?ss pq:P582 ?end }} }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }} }}""")
    f = {"born": "", "died": "", "place": "", "spouses": [], "former": []}
    for r in rows:
        f["born"] = f["born"] or (r.get("born") or "")[:10]
        f["died"] = f["died"] or r.get("died", "")
        if r.get("placeLabel") and not re.fullmatch(r"Q\d+", r["placeLabel"]):
            f["place"] = f["place"] or r["placeLabel"]
        s = r.get("spouseLabel", "")
        if s and not re.fullmatch(r"Q\d+", s):
            (f["former"] if r.get("end") else f["spouses"]).append(s)
    f["spouses"] = list(dict.fromkeys(f["spouses"])); f["former"] = list(dict.fromkeys(x for x in f["former"] if x not in f["spouses"]))
    return f


def wd_works(q, skip=""):
    rows = sparql(f"""SELECT ?work ?workLabel ?links ?date WHERE {{
  ?work wdt:P161 wd:{q} ; wikibase:sitelinks ?links . OPTIONAL {{ ?work wdt:P577 ?date }} OPTIONAL {{ ?work wdt:P580 ?date }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }} }} ORDER BY DESC(?links) LIMIT 30""")
    best = {}
    for r in rows:
        w = qid(r["work"])
        if w == skip or re.fullmatch(r"Q\d+", r.get("workLabel", "")):
            continue
        yr = (r.get("date") or "")[:4]
        b = best.setdefault(w, {"title": r["workLabel"], "year": yr, "character": "", "links": int(r.get("links") or 0)})
        if yr and (not b["year"] or yr < b["year"]):
            b["year"] = yr
    return sorted(best.values(), key=lambda b: -b["links"])[:5]


def tvm_works(pid, skip_show=None):
    rows = tvmaze(f"/people/{pid}/castcredits", embed="show") or []
    out, seen = [], set()
    for r in rows:
        s = (r.get("_embedded") or {}).get("show") or {}
        if not s.get("name") or s.get("id") == skip_show or s["name"] in seen or r.get("self"):
            continue
        seen.add(s["name"])
        out.append({"title": s["name"], "year": (s.get("premiered") or "")[:4],
                    "character": ((r.get("_links") or {}).get("character") or {}).get("name", ""), "w": s.get("weight") or 0})
    return sorted(out, key=lambda x: -x["w"])[:5]


def known_for(r, item):
    """Где ещё снимался актёр — для «где я его видел»."""
    if r.get("qid"):
        return wd_works(r["qid"], item["id"])
    if r.get("pid"):
        return tvm_works(r["pid"], item.get("show_id"))
    return []


def merge_known(a, b):
    out, seen = [], set()
    for k in a + b:
        key = re.sub(r"\W", "", k["title"].lower())
        if key not in seen:
            seen.add(key); out.append(k)
    return out[:5]


def person_facts(c, item, today):
    wiki, wiki_url, q = wiki_person(c["name"], c.get("wiki_title", ""))
    q = c.get("qid") or q
    wd = {"born": "", "died": "", "place": "", "spouses": [], "former": []}
    if q:
        try:
            wd = wd_person(q)
        except Exception as e:
            log(f"Wikidata {c['name']}: {e}")
    if c.get("died") or wd["died"]:
        return None                                        # архивные кадры умерших актёров — не описываем
    known = []
    try:
        if q:
            known = wd_works(q, item["id"] if item["type"] == "movie" else "")
        if c.get("pid"):
            known = merge_known(known, tvm_works(c["pid"], item.get("show_id")))
    except Exception as e:
        log(f"работы {c['name']}: {e}")
    known = [k for k in known if re.sub(r"\W", "", k["title"].lower()) != re.sub(r"\W", "", item["title"].lower())]
    born = c.get("born") or wd["born"]
    f = {"id": c["id"], "name": c["name"], "character": c.get("character", ""), "born": born,
         "place": wd["place"] or c.get("country", ""), "known": known, "bio": "", "wiki": wiki, "wiki_url": wiki_url,
         "spouses": wd["spouses"], "former": wd["former"], "url": wiki_url or c.get("url", ""), "voice": bool(c.get("voice"))}
    f["age"] = age_on(born, today) if born else None
    f["minor"] = f["age"] is not None and f["age"] < 18
    return f


def people_questions(name):
    """Что люди в США набирают в Google про этого актёра (подсказки поиска)."""
    got = []
    for q in (name.lower(), name.lower() + " wife", name.lower() + " husband"):
        try:
            got += suggest(q)
        except Exception:
            pass
        time.sleep(0.3)
    last = name.split()[-1].lower()
    qs = []
    for s in got:
        if last in s and s.lower() != name.lower() and not BAD_Q.search(s) and s not in qs:
            qs.append(s)
    return qs[:8]


PREVIEW_PROMPT = """You write a "who's in it" cast guide for a US website, published a few days BEFORE the release, for people
who will google the actors. Title: {title} ({what}). Release in the US: {when}.
Plot (from the database, rewrite in your own words): {overview}

Below are FACTS about each cast member and the exact searches Americans type into Google about them.
Rules:
- Use ONLY the facts below. Never guess. Own words only; never reuse more than 5 words in a row from the facts.
- Tone of a 1930s American newspaper's entertainment column: formal, exact, short paragraphs, but clear to a modern reader.
  No hype. Do not name websites or databases in the text.
- "intro": 2 short paragraphs (80-140 words): what the {kind} is about, when and where it comes out, who leads the cast.
- For every person: "bio" = 1-2 sentences on who they are and their best-known work.
- For every person: "qa" = answers to the searches listed for them, written as real questions with the same key words
  people typed ("Who is {{name}} married to?", "Where is {{name}} from?", "Does {{name}} have kids?").
  Each answer must repeat the key words of the question and stay 1-2 sentences.
  If the facts do not mention a spouse and people ask about a wife/husband/marriage, answer exactly in this style:
  "Public sources do not list a spouse for NAME." For other questions the facts cannot answer, skip the question.
  Do NOT write questions about age, birthplace, the role or other films — those are added automatically.
  Skip anything about health, money, religion, politics, sexuality, dating rumors or appearance.
- People marked MINOR: only "bio" about their acting work, "qa" must be empty.
- Set "ok": false if the facts are too thin to write anything useful.

{people}"""

PREVIEW_TOOL = {
    "name": "cast_guide", "description": "Return the cast guide.",
    "input_schema": {"type": "object", "properties": {
        "ok": {"type": "boolean"},
        "intro": {"type": "string"},
        "people": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "bio": {"type": "string"},
            "qa": {"type": "array", "items": {"type": "object", "properties": {
                "q": {"type": "string"}, "a": {"type": "string"}}, "required": ["q", "a"]}}},
            "required": ["name", "bio"]}},
    }, "required": ["ok", "intro", "people"]},
}


def what_line(item):
    if item["type"] == "movie":
        return "movie", ("on " + ", ".join(item["where"])) if item["release"] == "digital" and item.get("where") else "in theaters"
    where = item.get("where") or item.get("networks") or []
    what = "series" if item.get("season", 1) == 1 else f"series, season {item['season']}"
    return what, ("on " + ", ".join(where)) if where else "on TV"


def facts_block(f):
    lines = [f"PERSON: {f['name']}" + (" (MINOR)" if f["minor"] else ""), f"Role in this title: {f['character'] or 'not listed'}"]
    if f["born"] and not f["minor"]:
        lines.append(f"Born: {f['born']}" + (f" in {f['place']}" if f["place"] else ""))
    if f["known"]:
        lines.append("Known for: " + "; ".join(f"{k['title']} ({k['year']})" + (f" as {k['character']}" if k['character'] else "") for k in f["known"]))
    if not f["minor"]:
        if f["spouses"]:
            lines.append("Spouse (current): " + ", ".join(f["spouses"]))
        if f["former"]:
            lines.append("Former spouse(s): " + ", ".join(f["former"]))
    if f["wiki"] and not f["minor"]:
        lines.append("Encyclopedia intro: " + f["wiki"])
    if f.get("questions") and not f["minor"]:
        lines.append("Searches people type: " + "; ".join(f["questions"]))
    return "\n".join(lines)


def write_preview(item, people, key, feedback="", store=None):
    what, where = what_line(item)
    prompt = PREVIEW_PROMPT.format(title=item["title"], what=what, kind="series" if item["type"] == "tv" else "movie",
                                   when=f"{nice_date(item['date'])}, {where}", overview=item["overview"] or "(none)",
                                   people="\n\n".join(facts_block(f) for f in people))
    if feedback:
        prompt += "\n\nAn editor rejected your previous draft: " + feedback + "\nFix it; drop anything the facts do not support."
    texts = [item["overview"]] + [f["bio"] for f in people] + [f["wiki"] for f in people]
    for _ in range(2):
        try:
            out = ai_call(prompt, key, PREVIEW_TOOL, max_tokens=8000)
        except Exception as e:
            store is not None and plog(store, f"{item['title']}: ИИ не ответил: {str(e)[:120]}")
            return None
        if not out.get("ok"):
            store is not None and plog(store, f"{item['title']}: ИИ счёл данные слишком бедными")
            return None
        full = " ".join([out.get("intro", "")] + [p.get("bio", "") + " " + " ".join(q.get("a", "") for q in p.get("qa", []))
                                                  for p in out.get("people", [])])
        names = sorted({x for f in people for x in [f["name"]] + [k["title"] for k in f.get("known", [])]}
                       | {r["name"] for r in item.get("roles", [])} | {item["title"]}, key=len, reverse=True)
        def strip_names(s):                 # имена актёров и названия фильмов совпадают неизбежно — их не считаем
            for nm in names:
                if len(nm) > 2:
                    s = re.sub(re.escape(nm), " ", s, flags=re.I)
            return s
        hits = copied(strip_names(full), [strip_names(t) for t in texts if t], n=10)
        if not hits:
            return out
        prompt += "\n\nYour draft repeated these word sequences from the facts: " + "; ".join(f'"{h}"' for h in hits[:5]) + ". Rewrite them."
    store is not None and plog(store, f"{item['title']}: текст дважды повторял источник: {hits[:2]}")
    return None


def auto_qa(f, item):
    """Ответы, которые считает программа (возраст точно по дате рождения), а не ИИ."""
    qa = []
    t = item["title"]
    if f["born"] and not f["minor"]:
        qa.append({"q": f"How old is {f['name']}?",
                   "a": f"{f['name']} was born on {nice_date(f['born'])} and is {f['age']} years old."})
        if f["place"]:
            qa.append({"q": f"Where is {f['name']} from?", "a": f"{f['name']} was born in {f['place']}."})
    if f["known"]:
        ks = [f"{k['title']} ({k['year']})" if k["year"] else k["title"] for k in f["known"][:4]]
        qa.append({"q": f"What else has {f['name']} been in?",
                   "a": f"{f['name']} is known for " + (", ".join(ks[:-1]) + " and " + ks[-1] if len(ks) > 1 else ks[0]) + "."})
    return qa


def plog(store, msg):
    """Журнал гидов по актёрам в data/topics.json — чтобы видеть, почему страница не вышла."""
    log(msg)
    j = store.setdefault("preview_log", [])
    j.append(now_iso()[:16] + " " + msg)
    store["preview_log"] = j[-60:]


def make_preview(store, item, key, today, old=None):
    """Собирает факты об актёрах, пишет текст, проверяет редактором. old — прежняя версия страницы (обновление после премьеры)."""
    people = []
    for c in item["cast"]:
        try:
            f = person_facts(c, item, today)
        except Exception as e:
            log(f"актёр {c['name']}: {e}")
            continue
        if f:
            f["questions"] = [] if f["minor"] else people_questions(f["name"])
            people.append(f)
        time.sleep(0.3)
    if len(people) < 3:
        plog(store, f"{item['title']}: мало данных об актёрах ({len(people)})")
        return None
    res = write_preview(item, people, key, store=store)
    src = {"blocks": [f"TITLE: {item['title']} — US release {item['date']} — {item['overview']}"]
           + [facts_block(f) for f in people]
           + ["NOTE: computed answers (age, role, other titles) are added by the site; saying 'public sources do not list "
              "a spouse' is correct when no spouse appears in the facts."]}
    if res:
        draft = res["intro"] + "\n\n" + "\n\n".join(p.get("name", "") + ": " + p.get("bio", "") + "\n"
                                                    + "\n".join(f"Q: {q['q']} A: {q['a']}" for q in p.get("qa", []))
                                                    for p in res.get("people", []))
        if not review(store, "cast guide", item["title"], draft, src, key):
            res = write_preview(item, people, key, store["review_log"][-1]["reason"], store=store)
            if res:
                draft = res["intro"] + "\n\n" + "\n\n".join(p.get("name", "") + ": " + p.get("bio", "") + "\n"
                                                            + "\n".join(f"Q: {q['q']} A: {q['a']}" for q in p.get("qa", []))
                                                            for p in res.get("people", []))
                if not review(store, "cast guide (fixed)", item["title"], draft, src, key):
                    res = None
    if not res:
        return None
    def nk(s):
        import unicodedata
        s = unicodedata.normalize("NFKD", re.sub(r"\(.*?\)", "", s or "")).encode("ascii", "ignore").decode().lower()
        return re.sub(r"[^a-z]", "", s)
    by_name = {nk(p.get("name", "")): p for p in res.get("people", [])}
    if len(by_name) < len([p for p in res.get("people", []) if p.get("bio")]) or not any(nk(f["name"]) in by_name for f in people):
        by_name = {nk(f["name"]): p for f, p in zip(people, res.get("people", []))}   # ИИ переписал имена — сопоставляем по порядку
    got = sum(1 for f in people if by_name.get(nk(f["name"]), {}).get("bio"))
    if got < len(people):
        plog(store, f"{item['title']}: описания есть только у {got} из {len(people)} актёров")
    slug = (old or {}).get("slug") or slugify(item["title"] + ("" if item.get("season", 1) == 1 else f" season {item['season']}") + " cast")
    old_img = {c["name"]: c.get("img") for c in (old or {}).get("cast", [])}
    cast = []
    for i, f in enumerate(people):
        w = by_name.get(nk(f["name"]), {})
        qa = auto_qa(f, item) + ([] if f["minor"] else [q for q in w.get("qa", []) if q.get("q") and q.get("a")
                                                        and not BAD_Q.search(q["q"])][:2])
        entry = {"name": f["name"], "character": f["character"], "bio": w.get("bio", ""), "qa": qa,
                 "born": "" if f["minor"] else f["born"],
                 "wiki_url": f["wiki_url"], "url": f["url"], "voice": f["voice"]}
        if old_img.get(f["name"]):
            entry["img"] = old_img[f["name"]]          # фото уже есть — не ищем заново
        elif i < PREVIEW_PHOTOS and not f["minor"] and not old:
            fake = {"term": item["title"], "slug": f"cast-{slug}-{i}", "image_query": "actor",
                    "ai": {"headline": f"{f['name']} plays {f['character'] or 'a role'} in {item['title']}"}}
            try:
                im = wiki_image(fake, f["name"])
                if im:
                    entry["img"] = im
            except Exception as e:
                log(f"фото актёра {f['name']}: {e}")
        cast.append(entry)
    main_ids = {f["id"] for f in people}
    roles = []
    for r in item.get("roles", []):
        er = {"name": r["name"], "character": r["character"], "known": [], "episode": r.get("episode", ""),
              "voice": bool(r.get("voice"))}
        if r["id"] in main_ids:
            er["main"] = True
        elif sum(1 for x in roles if not x.get("main")) < PREVIEW_ROLES_KNOWN:
            try:
                er["known"] = [k for k in known_for(r, item) if re.sub(r"\W", "", k["title"].lower())
                               != re.sub(r"\W", "", item["title"].lower())][:3]
            except Exception:
                pass
            time.sleep(0.25)
        roles.append(er)
    return {"roles": roles, "slug": slug, "title": item["title"], "type": item["type"], "season": item.get("season", 1),
                       "date": item["date"], "release": item["release"], "where": item.get("where", []),
                       "networks": item.get("networks", []), "genres": item["genres"], "intro": res["intro"],
                       "cast": cast, "link": item["link"], "link_name": item["link_name"], "made": now_iso(), "day": (old or {}).get("day", today), "new": True,
            "first": (old or {}).get("first", now_iso()), "item": item, "refreshed": bool(old)}


def previews(store):
    if not (PREVIEW and api_key()):
        return 0
    key = api_key()
    pv = store.setdefault("previews", {})
    now = datetime.now(timezone.utc)
    today = to_et(now)[0].strftime("%Y-%m-%d")
    if hours_since(store.get("preview_checked", "2000-01-01T00:00:00+00:00")) < 3:
        return 0                                   # базу премьер смотрим раз в 3 часа
    store["preview_checked"] = now_iso()
    done = 0
    # через 3+ дня после премьеры — один раз обновляем: люди уже посмотрели и спрашивают новое
    for k, x in list(pv.items()):
        if x.get("slug") and x.get("item") and not x.get("refreshed") and done < 1 \
                and (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(x["date"], "%Y-%m-%d")).days >= 3:
            x["refreshed"] = True
            try:
                fresh = refresh_item(x)
            except Exception as e:
                log(f"обновление {x['title']}: {e}")
                fresh = None
            entry = make_preview(store, fresh or x["item"], key, today, old=x)
            if entry:
                pv[k] = entry; done += 1
                log(f"гид по актёрам обновлён после премьеры: {x['title']}")
    for k, x in list(pv.items()):                 # страницы без описаний актёров (сбой ИИ) — переписываем один раз
        if x.get("slug") and x.get("item") and not x.get("redo") and not any(c.get("bio") for c in x.get("cast", [])):
            x["redo"] = True
            entry = make_preview(store, x["item"], key, today, old=x)
            if entry:
                entry["redo"] = True; entry["refreshed"] = x.get("refreshed", False)
                pv[k] = entry; done += 1
                plog(store, f"{x['title']}: переписан (были пустые описания)")
    made_today = sum(1 for x in pv.values() if x.get("day") == today)
    if made_today >= MAX_PREVIEWS_PER_DAY:
        return done
    end = (to_et(now)[0] + timedelta(days=PREVIEW_DAYS_AHEAD)).strftime("%Y-%m-%d")
    ub = user_blocks()
    for item in upcoming_titles(today, end):
        if made_today >= MAX_PREVIEWS_PER_DAY:
            break
        if item["key"] in pv or (pv.get(item["key"] + "-x") or {}).get("tries", 0) >= 2:
            continue
        if bad_text(item["title"], ub) or len(item["cast"]) < 3:
            continue
        try:
            sug = suggest(item["title"].lower() + " cast")
        except Exception:
            sug = []
        if not any(all(w in words(s) for w in words(item["title"])[:3]) for s in sug):
            log(f"'{item['title']}': пока не ищут в Google («… cast» нет в подсказках) — подожду")
            continue
        fail = pv.setdefault(item["key"] + "-x", {"tries": 0})
        fail["tries"] += 1
        entry = make_preview(store, item, key, today)
        if not entry:
            continue
        pv.pop(item["key"] + "-x", None)
        pv[item["key"]] = entry
        made_today += 1; done += 1
        log(f"гид по актёрам: {item['title']} ({item['date']})")
    return done


def animated(x):
    return sum(1 for c in x["cast"] if c.get("voice")) * 2 >= max(1, len(x["cast"]))


def cast_title(x):
    s = x["title"] + (f" Season {x['season']}" if x.get("season", 1) > 1 else "")
    if animated(x):
        return f"{s} Voice Cast: Who Voices Who and Where You've Heard Them"
    return f"{s} Cast: Who Plays Who, Ages and Where You've Seen Them"


def build_cast(x):
    what = "movie" if x["type"] == "movie" else "series"
    when = nice_date(x["date"])
    future = x["date"] >= to_et(datetime.now(timezone.utc))[0].strftime("%Y-%m-%d")
    if x["type"] == "movie":
        where = ("on " + ", ".join(x["where"])) if x["release"] == "digital" and x.get("where") else "in theaters"
    else:
        w = x.get("where") or x.get("networks") or []
        where = ("on " + ", ".join(w)) if w else "on TV"
    name = x["title"] + (f" season {x['season']}" if x.get("season", 1) > 1 else "")
    lead = ", ".join(c["name"] for c in x["cast"][:3])
    answer = (f"{name} {'arrives' if future else 'came out'} {where} on {when}. The cast is led by {lead}. "
              + ("Here is who voices each character and where you have heard the actors before." if animated(x) else
                 "Here is who plays who, how old the actors are and where you have seen them before."))
    hero = next((c["img"] for c in x["cast"] if c.get("img")), None)
    quick = "".join(f'<li><a class="t" href="#{slugify(c["name"])}">{E(c["name"])}</a>'
                    f'<span class="meta">{E(c["character"] or "")}</span></li>' for c in x["cast"])
    parts, faq = [], []
    for c in x["cast"]:
        img = ""
        if c.get("img"):
            im = c["img"]
            img = (f'<figure class="hero" style="max-width:320px"><img src="../{E(im["file"])}" alt="{E(c["name"])}" loading="lazy">'
                   f'<figcaption>{E(c["name"])}. Photo: {E(im.get("credit", ""))} / {E(im.get("license", ""))}, '
                   f'<a href="{E(im.get("src", ""))}" rel="nofollow">via Wikimedia Commons</a></figcaption></figure>')
        if c.get("born"):                       # возраст пересчитываем при каждой сборке — он меняется
            c["qa"] = [dict(q, a=f"{c['name']} was born on {nice_date(c['born'])} and is "
                               f"{age_on(c['born'], to_et(datetime.now(timezone.utc))[0].strftime('%Y-%m-%d'))} years old.")
                       if q["q"].startswith("How old is") else q for q in c["qa"]]
        qa = "".join(f"<h3>{E(q['q'])}</h3><p>{E(q['a'])}</p>" for q in c["qa"])
        faq += c["qa"]
        role = ((" voices " if c.get("voice") else " as ") + c["character"]) if c["character"] else ""
        parts.append(f'<h2 class="sec" id="{slugify(c["name"])}">{E(c["name"])}{E(role)}</h2>{img}<p>{E(c["bio"])}</p>{qa}')
    paras = "".join(f"<p>{E(p)}</p>" for p in x["intro"].split("\n\n") if p.strip())
    rows = []
    for r in x.get("roles", []):
        ks = [f"{k['title']} ({k['year']})" if k.get("year") else k["title"] for k in r.get("known", [])]
        who = f'<a class="xl" href="#{slugify(r["name"])}">{E(r["name"])}</a>' if r.get("main") else E(r["name"])
        note = " (voice)" if r.get("voice") else ""
        ep = f' <span class="meta">{E(r["episode"])}</span>' if r.get("episode") else ""
        rows.append(f"<tr><td>{E(r['character'])}{ep}</td><td>{who}{note}</td><td>{E(', '.join(ks))}</td></tr>")
    roles_html = ('<div class="ct"><table><thead><tr><th>Character</th><th>Actor</th><th>Also seen in</th></tr></thead><tbody>'
                  + "".join(rows) + "</tbody></table></div>") if rows else ""
    src = "".join(f'<li><a class="t" href="{E(c["wiki_url"])}" rel="nofollow" target="_blank">{E(c["name"])} — Wikipedia</a></li>'
                  for c in x["cast"] if c.get("wiki_url"))
    work = {"@context": "https://schema.org", "@type": "Movie" if x["type"] == "movie" else "TVSeries", "name": x["title"],
            ("datePublished" if x["type"] == "movie" else "startDate"): x["date"],
            "actor": [{"@type": "Person", "name": c["name"]} for c in x["cast"]]}
    ld = [{"@context": "https://schema.org", "@type": "Article", "headline": cast_title(x)[:110], "datePublished": x["made"],
           "dateModified": x["made"], "author": {"@type": "Organization", "name": SITE_NAME, "url": SITE_URL},
           "publisher": {"@type": "Organization", "name": SITE_NAME, "url": SITE_URL},
           "mainEntityOfPage": f"{SITE_URL}/w/{x['slug']}", "about": work}]
    if hero:
        ld[0]["image"] = SITE_URL + "/" + hero["file"]
    if faq:
        ld.append({"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": q["q"], "acceptedAnswer": {"@type": "Answer", "text": q["a"]}} for q in faq[:80]]})
    head = f'<script type="application/ld+json">{json.dumps(ld)}</script>'
    body = f"""<article>
<p class="meta"><a href="../index.html">{SITE_NAME}</a> › <a class="cat" href="../cast.html">Cast guides</a> · {E(what)} · updated {E(fmt_et(x["made"]))}</p>
<h1>{E(cast_title(x))}</h1>
{listen_html()}
<div class="box answer"><p style="margin:0">{E(answer)}</p></div>
{paras}
<h2>The cast at a glance</h2><ul class="list">{quick}</ul>
{ad("in_article")}
{"".join(parts)}
{('<h2 class="sec" id="full-cast">Full cast of ' + E(x["title"]) + ': every character and actor</h2>' + roles_html) if roles_html else ''}
{reactions_html("w/" + x["slug"])}
{ad("middle")}
<h2>Sources</h2><ul class="list"><li><a class="t" href="{E(x["link"])}" rel="nofollow" target="_blank">{E(x["title"])} — {E(x["link_name"])}</a></li>{src}</ul>
<p class="meta">Ages are calculated from listed birth dates.
{'Cast and schedule data: <a href="https://www.tvmaze.com/" rel="nofollow">TVmaze</a> (CC BY-SA 4.0). ' if x["type"] == "tv" else ''}Film and people data: <a href="https://www.wikidata.org/" rel="nofollow">Wikidata</a>.</p>
</article>"""
    return page(cast_title(x), short_desc(answer), body, f"w/{x['slug']}.html", 1, head, og_img=hero["file"] if hero else "")


def build_cast_index(pv):
    items = sorted([x for x in pv.values() if x.get("slug")], key=lambda x: x["date"], reverse=True)
    rows = "".join(f'<li><a class="t" href="w/{E(x["slug"])}.html">{E(cast_title(x))}</a>'
                   f'<span class="meta">{"Movie" if x["type"] == "movie" else "Series"} · {E(nice_date(x["date"]))} · '
                   f'{E(", ".join(c["name"] for c in x["cast"][:3]))}</span></li>' for x in items[:300])
    body = (f'<p class="tag">New movies and series coming out this week — who is in them</p>'
            f'<h1 class="front">Cast guides</h1><ul class="list">{rows}</ul>')
    return page(f"Cast guides: who's in this week's new movies and shows | {SITE_NAME}",
                "Who plays who in new movies and TV series: actors, their ages and where you have seen them before.",
                body, "cast.html", 0)



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
    try:
        pn = previews(store)
        if pn:
            log(f"Новых гидов по актёрам: {pn}")
    except Exception as e:
        log(f"гиды по актёрам: ошибка {e}")
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
