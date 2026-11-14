# -*- coding: utf-8 -*-
"""
Радар интернет-трендов для trendrundown.com  (программа для ноутбука, отдельная от остальных).

ЧТО ДЕЛАЕТ. Ищет то, о чём сейчас «говорит весь интернет»: новые словечки, мемы, челленджи, тренды TikTok —
то, что люди потом гуглят как «what does X mean» / «what is the X trend». Смотрит сразу в несколько мест
(«этажи») и считает трендом то, что всплыло в нескольких:

  1. Подсказки Google  — каждый день спрашивает ~1000 начал фраз («what does ab…», «what is the a…», «why is everyone
                         saying…») и запоминает все подсказки. Фраза, которой вчера не было, = люди начали это искать.
  2. Подсказки YouTube — то же для видео-трендов и челленджей.
  3. Reddit            — разделы и поиск, где люди просят объяснить тренд, слово, шутку (только открытые RSS-ленты).
  4. Urban Dictionary  — подтверждение, что это сленг, и насколько он свежий.
  5. Know Your Meme    — новые и растущие мемы.
  6. Google Trends     — что сегодня ищут в США (общая лента).
  7. Bluesky           — темы, которые сейчас обсуждают.
  8. Википедия и поиск — есть ли уже хорошее объяснение (конкуренция).

Потом оценивает каждого кандидата (сколько этажей подтвердили, насколько он новый, растёт ли, есть ли уже
сильные объяснения), собирает по лучшим контекст (что пишут на Reddit) и отправляет на сайт: laptop/radar.json.
Страницы по ним пишет Claude в ежедневной задаче.

Нужно: Python 3.8+, файл token (тот же ключ GitHub, что у сборщика) в этой папке. Ничего нигде не публикует,
паролей не нужно. Запуск: start_radar.bat. Окно не закрывать.
"""
import base64, gzip, html, io, json, os, random, re, sys, time, traceback
import urllib.error, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

VERSION = "1.0"
HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "radar_state.json")
LOG = os.path.join(HERE, "radar_log.txt")
TOP_TXT = os.path.join(HERE, "radar_top.txt")
OUT_JSON = os.path.join(HERE, "radar.json")
REPO = "feanorkurufinve1-coder/trendrundown"
REPO_PATH = "laptop/radar.json"

CYCLE_HOURS = 8            # как часто просыпаться (Reddit и быстрые источники — каждый раз)
SWEEP_HOURS = 20           # полный обход подсказок Google — не чаще раза в 20 часов
FRESH_DAYS = 7             # сколько дней фраза считается «новой»
KEEP_PHRASE_DAYS = 60
MAX_CANDIDATES = 70        # сколько кандидатов отправлять на сайт
ENRICH_TOP = 40            # по скольким лучшим собирать подтверждения (Urban Dictionary, Википедия)
SERP_TOP = 25              # по скольким проверять конкурентов в поиске
COMMENTS_TOP = 8           # по скольким читать обсуждение на Reddit

QUICK = "--quick" in sys.argv          # короткий проверочный прогон
ONCE = "--once" in sys.argv or QUICK
NO_UPLOAD = "--no-upload" in sys.argv

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0.0.0 Safari/537.36")
UA_BOT = "windows:trendrundown.trendradar:v%s (personal research script)" % VERSION

LETTERS = "abcdefghijklmnopqrstuvwxyz"
DIGITS = "0123456789"

# ---------- что спрашиваем у подсказок: (начало фразы, чем продолжать, семейство) ----------
def build_prefixes():
    p = []
    for a in LETTERS:                                   # what does ab… mean  — главный источник сленга
        for b in LETTERS:
            p.append(("what does " + a + b, "slang"))
    for c in DIGITS:
        p.append(("what does " + c, "slang"))
    for c in LETTERS:
        p.append(("what does the " + c, "slang"))
        p.append(("what is the " + c, "trend"))         # what is the … trend / challenge / meme
        p.append(("what is " + c, "trend"))
        p.append(("why is everyone saying " + c, "saying"))
        p.append(("why is everyone " + c, "saying"))
        p.append(("why are people saying " + c, "saying"))
        p.append(("why are people " + c, "saying"))
        p.append(("tiktok " + c, "tiktok"))
        p.append(("new tiktok trend " + c, "tiktok"))
        p.append(("viral " + c, "tiktok"))
        p.append(("what does it mean when someone says " + c, "saying"))
    for s in ("what does", "what is the", "why is everyone saying", "why is everyone", "why are people saying",
              "tiktok trend", "new trend", "new slang", "gen z slang", "gen alpha slang", "brainrot words",
              "what does the", "meaning of the", "viral trend", "new meme", "what is the new"):
        p.append((s + " ", "seed"))
    return p


YT_PREFIXES = ([("tiktok trend " + c, "yt") for c in LETTERS] + [("new trend " + c, "yt") for c in LETTERS]
               + [("what is the " + c, "yt") for c in LETTERS])

# ---------- Reddit: разделы и поиск, где просят объяснить ----------
REDDIT_FEEDS = [
    ("search", 'title:"what does" mean'), ("search", 'title:"why is everyone"'), ("search", "tiktok trend explain"),
    ("search", 'title:"what is the" trend'), ("search", 'title:"what does" slang'),
    ("r", "OutOfTheLoop"), ("r", "PeterExplainsTheJoke"), ("r", "ExplainTheJoke"), ("r", "GenZ"), ("r", "GenAlpha"),
    ("r", "teenagers"), ("r", "Teachers"), ("r", "TikTokCringe"), ("r", "tiktok"), ("r", "slang"),
    ("r", "KnowYourMeme"), ("r", "NoStupidQuestions"), ("r", "youngpeopleyoutube"), ("r", "internetculture"),
]

# слова в подсказке, по которым «what is the X …» считаем трендом
TREND_WORDS = ("trend", "challenge", "meme", "tiktok", "filter", "dance", "sound", "song on tiktok", "theory", "test",
               "method", "rule", "core", "aesthetic", "era", "brainrot", "slang", "emoji", "prank", "hack", "game on tiktok")

# ---------- что пропускаем (запреты владельца сайта: пошлое, религия, незаконное, опасное) ----------
BLOCK = re.compile(r"(?i)\b(sex|sexual|sexy|porn|nsfw|nude|naked|onlyfans|fetish|kink|boob|dick|cock|pussy|cum|horny|"
                   r"fuck|shit|bitch|slut|whore|hentai|milf|dildo|anal|blowjob|goon|gooning|thot|orgasm|penis|vagina|"
                   r"god|jesus|bible|biblical|christ|christian|church|islam|muslim|allah|quran|hindu|buddh\w*|jewish|judaism|"
                   r"torah|prayer|pray|amen|hallelujah|pastor|pope|catholic|satan|demon|spiritually|spiritual|angel number|"
                   r"weed|cocaine|meth|fentanyl|heroin|xanax|percs?|lean drink|cartel|glock|suicide|kys|self harm|rape|"
                   r"nazi|hitler|kkk)\b")
GENERIC = set("it this that he she they you i we a an the my your his her their its mean means meaning word slang "
              "someone something everyone people text mean in when if and or to of on".split())
BIG_EXPLAINERS = ("knowyourmeme.", "dictionary.com", "urbandictionary.", "merriam-webster.", "wikipedia.org", "today.com",
                  "parents.com", "usatoday.", "nytimes.", "forbes.", "yahoo.", "distractify.", "dexerto.", "cnn.",
                  "people.com", "buzzfeed.", "mashable.", "theguardian.", "bbc.", "nbcnews.", "cbsnews.", "newsweek.",
                  "businessinsider.", "wired.", "vox.com", "indy100.", "hitc.com", "later.com", "cosmopolitan.")


# =====================================================================================================
#  служебное
# =====================================================================================================
def log(msg):
    line = "%s  %s" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), msg)
    try:
        print(line, flush=True)
    except Exception:
        print(line.encode("ascii", "replace").decode(), flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def now_utc():
    return datetime.now(timezone.utc)


def now_iso():
    return now_utc().isoformat(timespec="seconds")


def today():
    return now_utc().strftime("%Y-%m-%d")


def days_ago(day):
    try:
        return (now_utc().date() - datetime.strptime(day[:10], "%Y-%m-%d").date()).days
    except Exception:
        return 9999


def load_state():
    try:
        st = json.load(open(STATE, encoding="utf-8"))
    except Exception:
        st = {}
    st.setdefault("phrases", {})        # фраза -> [первый день, последний день, сколько дней видели, оценка, начало-источник]
    st.setdefault("prefix_first", {})   # начало фразы -> день, когда его впервые обошли (чтобы не считать старое новым)
    st.setdefault("posts", {})          # адрес поста Reddit -> запись
    st.setdefault("terms", {})          # ключ термина -> {first, last, days}
    st.setdefault("last_sweep", "")
    st.setdefault("sweeps", 0)
    st.setdefault("cursor", 0)          # с какого начала продолжать обход, если прервали
    return st


def save_state(st):
    tmp = STATE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False)
    os.replace(tmp, STATE)


CTX = [None]


def opener():
    """Свежие сертификаты (на старых Windows свои устарели). Пакет certifi ставится один раз сам."""
    if CTX[0] is None:
        import ssl
        try:
            import certifi
        except ImportError:
            import subprocess
            log("Ставлю свежие сертификаты (один раз)...")
            try:
                subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "certifi"], check=False)
                import certifi
            except Exception:
                certifi = None
        CTX[0] = ssl.create_default_context(cafile=certifi.where()) if certifi else False
    if CTX[0]:
        return urllib.request.build_opener(urllib.request.HTTPSHandler(context=CTX[0]))
    return urllib.request.build_opener()


class Blocked(Exception):
    """Источник просит подождать (429/403) — на этот раз его пропускаем."""


def fetch(url, data=None, ua=UA, tries=3, limit=3000000, accept=None, timeout=35):
    """Скачать как текст. Обрывы интернета пережидаем; 429/403 — Blocked; прочие ошибки сайта — наружу."""
    last = None
    for attempt in range(tries):
        req = urllib.request.Request(url, data=data, headers={
            "User-Agent": ua, "Accept-Language": "en-US,en;q=0.9", "Accept-Encoding": "gzip",
            "Accept": accept or "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.9,*/*;q=0.5"})
        try:
            with opener().open(req, timeout=timeout) as r:
                raw = r.read(limit)
                if r.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read(limit)
                m = re.search(r"charset=([\w-]+)", r.headers.get("Content-Type", ""))
                try:
                    return raw.decode(m.group(1) if m else "utf-8", "replace")
                except LookupError:
                    return raw.decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (429, 403, 202):
                raise Blocked("ошибка %s" % e.code)
            raise
        except Exception as e:
            last = e
            if attempt == tries - 1:
                raise
            time.sleep([8, 25, 60][attempt])
    raise last


def strip_tags(s):
    s = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", s or "")
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


class Health(dict):
    """Отчёт о каждом источнике — уходит на сайт, чтобы было видно, что работает, а что нет."""

    def ok(self, name, n, note=""):
        self[name] = {"ok": True, "n": n, "note": note[:200]}
        log("  %-16s получено: %s %s" % (name, n, note[:90]))

    def fail(self, name, err, n=0):
        self[name] = {"ok": False, "n": n, "err": str(err)[:240]}
        log("  %-16s НЕ ПОЛУЧЕНО: %s" % (name, str(err)[:140]))


# =====================================================================================================
#  разбор фраз: что именно люди хотят понять
# =====================================================================================================
def clean_term(t):
    t = html.unescape(t or "").strip().strip("\"'“”‘’`*.,!?:;()[]{}").strip()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"(?i)^(the |a |an )?(term|word|phrase|slang|expression|saying|emoji|acronym|abbreviation|meme|joke) ", "", t)
    return t.strip().strip("\"'“”‘’`").strip()


def term_key(t):
    return re.sub(r"[^a-z0-9]+", "", t.lower())


def good_term(t):
    if not t or len(t) > 42 or len(t.split()) > 5:
        return False
    k = term_key(t)
    if len(k) < 2 or k.isdigit() and len(k) > 4:
        return False
    words = re.findall(r"[a-z0-9']+", t.lower())
    if not words or all(w in GENERIC for w in words):
        return False
    if words[0] in ("it", "this", "that", "he", "she", "they", "you", "i", "we", "my", "your", "if", "when", "someone"):
        return False
    return True


P_MEAN = re.compile(r"(?i)^what does (?:the )?(.+?) (?:mean|stand for)\b(?: .+)?$")
P_MEAN_ANY = re.compile(r"(?i)what does (?:the )?[\"“']?(.+?)[\"”']? (?:even |actually |really )?(?:mean|stand for)\b")
P_TREND = re.compile(r"(?i)^what(?: is|'s|s) (?:the |this |that |a |an )?(.+?) (trend|challenge|meme|filter|dance|sound|theory|"
                     r"test|method|rule|aesthetic|prank|hack)\b")
P_TREND_ANY = re.compile(r"(?i)what(?: is|'s|s) (?!up with|going on|the deal|happening)(?:the |this |that |a |an )?[\"“']?(.+?)[\"”']? (trend|challenge|meme|filter|"
                         r"dance|thing|joke|sound|theory)\b")
P_SAYING = re.compile(r"(?i)why (?:is|are) (?:everyone|everybody|people|kids|teens|students|gen ?z|gen ?alpha|my students|my kids)"
                      r" (?:saying|talking about|posting|doing|obsessed with|calling|using|commenting|spamming) (.+?)\??$")
P_DEAL = re.compile(r"(?i)what(?:'s| is|s) (?:the deal|up|going on|happening) with (?:the |this |that |all the |all these |these )?"
                    r"(.+?)(?: (?:trend|trends|meme|memes|thing|joke|jokes|videos|posts|craze|stuff|sound|challenge)\b.*)?\??$")
P_QUOTED = re.compile(r"[\"“]([^\"“”]{2,40})[\"”]")
P_TIKTOK = re.compile(r"(?i)^(?:new )?tiktok (?:trend )?(.+) (trend|challenge|meaning|filter|dance|sound)(?: (?:explained|meaning|tiktok|20\d\d))?$")


def parse_suggest(phrase):
    """Подсказка -> (термин, вид) или None."""
    q = phrase.strip().lower()
    if "it mean when" in q and "someone says" not in q:
        return None
    m = re.match(r"(?i)^what does it mean when someone says (.+)$", q)
    if m:
        return clean_term(m.group(1)), "slang"
    m = P_MEAN.match(q)
    if m:
        return clean_term(m.group(1)), "slang"
    m = P_TREND.match(q)
    if m:
        return clean_term(m.group(1)), m.group(2).lower()
    m = P_SAYING.match(q)
    if m:
        return clean_term(m.group(1)), "saying"
    m = P_TIKTOK.match(q)
    if m:
        return clean_term(m.group(1)), m.group(2).lower()
    m = re.match(r"(?i)^(?:viral|new) (.+?) (trend|challenge|meme|dance)\b", q)
    if m:
        return clean_term(m.group(1)), m.group(2).lower()
    return None


def parse_title(title):
    """Заголовок поста Reddit -> [(термин, вид)]. Пусто, если не про «объясните»."""
    t = html.unescape(title or "").strip()
    out = []
    for rx, kind in ((P_MEAN_ANY, "slang"), (P_SAYING, "saying"), (P_DEAL, "deal")):
        m = rx.search(t)
        if m:
            out.append((clean_term(m.group(1)), kind))
    m = P_TREND_ANY.search(t)
    if m:
        out.append((clean_term(m.group(1)), m.group(2).lower()))
    if re.search(r"(?i)\b(mean|means|meaning|trend|meme|slang|saying|joke|explain|reference)\b", t):
        for m in P_QUOTED.finditer(t):
            out.append((clean_term(m.group(1)), "quoted"))
    seen, res = set(), []
    for term, kind in out:
        k = term_key(term)
        if k and k not in seen and good_term(term):
            seen.add(k)
            res.append((term, kind))
    return res


EXPLAIN_TITLE = re.compile(r"(?i)\b(what does|what'?s (up|the deal|going on) with|what is (the|this|that)|why (is|are) (everyone|everybody|people)|"
                           r"explain|meaning|mean\?|trend|meme|slang|reference|out of the loop)\b")


# =====================================================================================================
#  ЭТАЖ 1–2: подсказки Google и YouTube
# =====================================================================================================
def suggest(prefix, yt=False):
    url = ("https://suggestqueries.google.com/complete/search?client=%s%s&hl=en&gl=us&q=%s"
           % ("firefox" if yt else "chrome", "&ds=yt" if yt else "", urllib.parse.quote(prefix)))
    d = json.loads(fetch(url, tries=2, timeout=20))
    sugs = d[1] if isinstance(d, list) and len(d) > 1 else []
    rel = []
    if isinstance(d, list) and len(d) > 4 and isinstance(d[4], dict):
        rel = d[4].get("google:suggestrelevance", []) or []
    out = []
    for i, s in enumerate(sugs):
        if isinstance(s, list):          # в некоторых форматах — [фраза, ...]
            s = s[0] if s else ""
        s = strip_tags(str(s)).lower()
        if 6 <= len(s) <= 90 and not re.search(r"[^\x20-\x7e]", s):
            out.append((s, rel[i] if i < len(rel) and isinstance(rel[i], int) else 0))
    return out


def sweep_suggest(st, health):
    """Полный обход начал фраз. Можно прервать: продолжит с того же места."""
    prefixes = build_prefixes()
    plan = [(p, f, False) for p, f in prefixes] + [(p, f, True) for p, f in YT_PREFIXES]
    if QUICK:
        plan = plan[::37][:30] + [("what does 6", "slang", False), ("what is the ", "seed", False)]
    start = st["cursor"] if 0 < st.get("cursor", 0) < len(plan) else 0
    day, got, new, fails, blocked = today(), 0, 0, 0, 0
    log("Подсказки Google/YouTube: начал фраз %d%s" % (len(plan), (", продолжаю с %d" % start) if start else ""))
    i = start
    while i < len(plan):
        prefix, fam, yt = plan[i]
        try:
            res = suggest(prefix, yt)
            blocked = 0
        except Blocked as e:
            blocked += 1
            if blocked >= 4:
                st["cursor"] = i
                health.fail("google_suggest", "Google просит подождать (%s) на %d из %d; продолжу в следующий раз" % (e, i, len(plan)), got)
                return False
            time.sleep(60 * blocked)
            continue
        except Exception as e:
            fails += 1
            res = []
            if fails >= 25 and got == 0:
                health.fail("google_suggest", "не отвечает: %s" % str(e)[:120])
                return False
        pkey = ("yt:" if yt else "") + prefix
        first_cover = st["prefix_first"].setdefault(pkey, day)
        for s, rel in res:
            rec = st["phrases"].get(s)
            if rec is None:
                st["phrases"][s] = [day, day, 1, rel, pkey]
                if first_cover < day:
                    new += 1
            else:
                if rec[1] != day:
                    rec[2] += 1
                rec[1] = day
                rec[3] = max(rec[3], rel)
            got += 1
        i += 1
        if i % 100 == 0:
            st["cursor"] = i
            save_state(st)
            log("  ...обошёл %d из %d начал, фраз собрано %d, новых %d" % (i, len(plan), got, new))
        time.sleep(random.uniform(0.25, 0.5) if QUICK else random.uniform(0.8, 1.6))
    st["cursor"] = 0
    st["last_sweep"] = now_iso()
    st["sweeps"] += 1
    if not st.get("baseline_day"):
        st["baseline_day"] = day            # всё, что увидели в первый обход, — «уже было», новым не считаем
    health.ok("google_suggest", got, "новых фраз %d, обход №%d" % (new, st["sweeps"]))
    return True


def phrase_is_fresh(rec):
    """Новая фраза: появилась недавно И её начало мы обходили раньше (иначе это просто первый обход)."""
    first, _last, _days, _rel, pkey = rec
    return days_ago(first) <= FRESH_DAYS and STATE_REF["prefix_first"].get(pkey, first) < first


STATE_REF = {"prefix_first": {}}


# =====================================================================================================
#  ЭТАЖ 3: Reddit (только открытые RSS-ленты)
# =====================================================================================================
ATOM = "{http://www.w3.org/2005/Atom}"


def reddit_rss(url):
    last = None
    for u, ua in ((url, UA), (url.replace("www.reddit.com", "old.reddit.com"), UA), (url, UA_BOT)):
        try:
            text = fetch(u, ua=ua, tries=2, accept="application/atom+xml,application/xml;q=0.9,*/*;q=0.8")
            if "<entry" in text:
                return text
            last = Blocked("пустой ответ")
        except Blocked as e:
            last = e
        time.sleep(random.uniform(5, 9))
    raise last or Blocked("нет ответа")


def parse_atom(text, sub=""):
    out = []
    try:
        root = ET.fromstring(text.encode("utf-8"))
    except Exception:
        return out
    for e in root.iter(ATOM + "entry"):
        link = e.find(ATOM + "link")
        cat = e.find(ATOM + "category")
        content = e.findtext(ATOM + "content") or ""
        snip = strip_tags(content)
        snip = re.sub(r"\s*submitted by\s+/u/\S+.*$", "", snip).strip()
        out.append({"t": strip_tags(e.findtext(ATOM + "title") or ""),
                    "sub": (cat.get("term") if cat is not None and cat.get("term") else sub),
                    "url": (link.get("href") if link is not None else "").split("?")[0],
                    "at": (e.findtext(ATOM + "published") or e.findtext(ATOM + "updated") or "")[:19],
                    "snip": snip[:420]})
    return out


def collect_reddit(st, health):
    got, new, errs, blocked = 0, 0, [], 0
    feeds = REDDIT_FEEDS[:5] if QUICK else REDDIT_FEEDS
    for kind, name in feeds:
        if kind == "search":
            url = "https://www.reddit.com/search.rss?q=%s&sort=new&t=week&limit=50" % urllib.parse.quote(name)
        else:
            url = "https://www.reddit.com/r/%s/new/.rss?limit=50" % name
        try:
            posts = parse_atom(reddit_rss(url), name if kind == "r" else "")
            blocked = 0
        except Exception as e:
            errs.append("%s: %s" % (name, str(e)[:60]))
            blocked += 1
            if blocked >= 3:
                break                        # Reddit сейчас не пускает — в следующий раз
            time.sleep(random.uniform(40, 70))
            continue
        for p in posts:
            if not p["url"] or not p["t"]:
                continue
            got += 1
            if p["url"] not in st["posts"]:
                p["got"] = now_iso()
                p["src"] = name
                st["posts"][p["url"]] = p
                new += 1
        time.sleep(random.uniform(4, 7) if QUICK else random.uniform(18, 30))
    cut = (now_utc() - timedelta(days=14)).isoformat()
    st["posts"] = {u: p for u, p in st["posts"].items() if p.get("got", "") >= cut}
    if got:
        health.ok("reddit", got, "новых постов %d%s" % (new, ("; не открылись: " + "; ".join(errs[:4])) if errs else ""))
    else:
        health.fail("reddit", "; ".join(errs[:5]) or "нет данных")


def reddit_comments(post_url):
    """Верхние ответы в обсуждении — чтобы понять, как люди сами объясняют тренд."""
    text = reddit_rss(post_url.rstrip("/") + "/.rss?limit=12&sort=top")
    out = []
    for e in parse_atom(text)[1:]:
        s = e["snip"]
        if len(s) >= 40 and not s.lower().startswith(("i am a bot", "thank you for your submission", "friendly reminder", "welcome to")):
            out.append(s[:380])
        if len(out) >= 4:
            break
    return out


# =====================================================================================================
#  ЭТАЖИ 4–7: Urban Dictionary, Know Your Meme, Google Trends, Bluesky
# =====================================================================================================
def ud_wotd(health):
    try:
        d = json.loads(fetch("https://api.urbandictionary.com/v0/words_of_the_day", tries=2))
        items = d.get("list", []) if isinstance(d, dict) else []
        out = [{"word": clean_term(x.get("word", "")), "date": (x.get("written_on") or "")[:10]} for x in items if x.get("word")]
        health.ok("urban_wotd", len(out))
        return out
    except Exception as e:
        health.fail("urban_wotd", e)
        return []


def ud_define(term):
    """Есть ли такой сленг и насколько он свежий. Сами определения не берём — только суть в 160 знаков для отбора."""
    d = json.loads(fetch("https://api.urbandictionary.com/v0/define?term=" + urllib.parse.quote(term), tries=2))
    items = [x for x in (d.get("list", []) if isinstance(d, dict) else [])
             if term_key(x.get("word", "")) == term_key(term)]
    if not items:
        return None
    top = max(items, key=lambda x: x.get("thumbs_up", 0))
    gist = re.sub(r"[\[\]]", "", strip_tags(top.get("definition", "")))[:160]
    return {"n": len(items), "newest": max((x.get("written_on") or "")[:10] for x in items),
            "oldest": min((x.get("written_on") or "9999")[:10] for x in items),
            "up": top.get("thumbs_up", 0), "gist": "" if BLOCK.search(gist) else gist}


def kym(health):
    """Новые и растущие мемы. Сайт иногда закрыт от программ — тогда просто без него."""
    out, err = {}, ""
    for url in ("https://knowyourmeme.com/memes.rss", "https://knowyourmeme.com/newsfeed.rss",
                "https://knowyourmeme.com/memes/trending", "https://knowyourmeme.com/memes"):
        try:
            text = fetch(url, tries=1, timeout=25)
        except Exception as e:
            err = str(e)[:80]
            continue
        if "<item" in text:
            for m in re.finditer(r"(?is)<item>(.*?)</item>", text):
                t = re.search(r"(?is)<title>(.*?)</title>", m.group(1))
                l = re.search(r"(?is)<link>(.*?)</link>", m.group(1))
                if t and l:
                    title = strip_tags(re.sub(r"(?s)<!\[CDATA\[(.*?)\]\]>", r"\1", t.group(1)))
                    out[strip_tags(l.group(1))] = title
        else:
            for m in re.finditer(r'href="(/memes/[a-z0-9-]+)"[^>]*>\s*(?:<[^>]+>\s*)*([^<]{3,70})<', text):
                if not re.search(r"/memes/(trending|popular|all|submissions|researching|newsworthy|deadpool|search|new)$", m.group(1)):
                    out["https://knowyourmeme.com" + m.group(1)] = strip_tags(m.group(2))
        time.sleep(random.uniform(2, 4))
    if out:
        health.ok("knowyourmeme", len(out))
    else:
        health.fail("knowyourmeme", err or "не найдено ни одной записи")
    return out


def google_trends(health):
    try:
        text = fetch("https://trends.google.com/trending/rss?geo=US", tries=2)
        out = []
        for m in re.finditer(r"(?is)<item>(.*?)</item>", text):
            t = re.search(r"(?is)<title>(.*?)</title>", m.group(1))
            tr = re.search(r"(?is)<ht:approx_traffic>(.*?)</ht:approx_traffic>", m.group(1))
            news = re.findall(r"(?is)<ht:news_item_title>(.*?)</ht:news_item_title>", m.group(1))
            if t:
                out.append({"q": strip_tags(t.group(1)).lower(), "traffic": strip_tags(tr.group(1)) if tr else "",
                            "news": [strip_tags(n)[:120] for n in news[:2]]})
        if not out:
            raise ValueError("лента пустая")
        health.ok("google_trends", len(out))
        return out
    except Exception as e:
        health.fail("google_trends", e)
        return []


def bluesky(health):
    try:
        d = json.loads(fetch("https://public.api.bsky.app/xrpc/app.bsky.unspecced.getTrendingTopics?limit=25", tries=2))
        out = []
        for key in ("topics", "suggested"):
            for x in (d.get(key) or []):
                name = x.get("topic") or x.get("displayName") or ""
                if name:
                    out.append(name.strip())
        if not out:
            raise ValueError("нет тем")
        health.ok("bluesky", len(out))
        return out
    except Exception as e:
        health.fail("bluesky", e)
        return []


# =====================================================================================================
#  ЭТАЖ 8: есть ли уже объяснение (Википедия, поиск)
# =====================================================================================================
def wiki_title(term):
    d = json.loads(fetch("https://en.wikipedia.org/w/api.php?action=query&list=search&srlimit=3&format=json&srsearch="
                         + urllib.parse.quote(term), ua=UA_BOT, tries=2))
    for x in d.get("query", {}).get("search", []):
        if term_key(x.get("title", "")).startswith(term_key(term)) or term_key(term) in term_key(x.get("title", "")):
            return x["title"]
    return ""


def serp(q):
    """Кто сейчас отвечает на вопрос в поиске (DuckDuckGo, обычная страница). None — поиск просит подождать."""
    try:
        page = fetch("https://html.duckduckgo.com/html/", data=urllib.parse.urlencode({"q": q, "kl": "us-en"}).encode(), tries=2)
    except Blocked:
        return None
    if "result__a" not in page:
        return None if ("anomaly" in page or "challenge" in page) else []
    out = []
    for m in re.finditer(r'class="result__a"[^>]*href="([^"]+)"', page):
        u = html.unescape(m.group(1))
        if "uddg=" in u:
            u = urllib.parse.unquote(re.search(r"uddg=([^&]+)", u).group(1))
        host = urllib.parse.urlparse(u).netloc.lower().replace("www.", "")
        if host and host not in out:
            out.append(host)
    return out[:10]


# =====================================================================================================
#  сведение этажей и оценка
# =====================================================================================================
def build_candidates(st, extra):
    """Собирает всех кандидатов из всех этажей. extra: {'ud': [...], 'kym': {...}, 'trends': [...], 'bsky': [...]}"""
    STATE_REF["prefix_first"] = st["prefix_first"]
    C = {}

    def cand(term, kind):
        k = term_key(term)
        c = C.get(k)
        if c is None:
            c = C[k] = {"key": k, "forms": {}, "kinds": {}, "suggest": [], "reddit": [], "layers": set(),
                        "fresh": 0, "fresh2": 0, "rel": 0, "blocked": False}
        c["forms"][term] = c["forms"].get(term, 0) + 1
        c["kinds"][kind] = c["kinds"].get(kind, 0) + 1
        return c

    # --- подсказки ---
    for phrase, rec in st["phrases"].items():
        if days_ago(rec[1]) > 3:                       # сейчас этой подсказки уже нет
            continue
        parsed = parse_suggest(phrase)
        if not parsed:
            continue
        term, kind = parsed
        if kind in ("trend",) and not any(w in phrase for w in TREND_WORDS):
            continue
        if not good_term(term):
            continue
        c = cand(term, kind)
        yt = str(rec[4]).startswith("yt:")
        c["layers"].add("youtube" if yt else "google")
        fresh = phrase_is_fresh(rec)
        c["suggest"].append({"q": phrase, "first": rec[0], "days": rec[2], "new": fresh, "yt": yt})
        c["rel"] = max(c["rel"], rec[3] or 0)
        if fresh:
            c["fresh"] += 1
            if rec[2] >= 2:
                c["fresh2"] += 1
        if BLOCK.search(phrase):
            c["blocked"] = True

    # --- Reddit ---
    week = (now_utc() - timedelta(days=7)).isoformat()
    for p in st["posts"].values():
        if p.get("got", "") < week:
            continue
        for term, kind in parse_title(p["t"]):
            c = cand(term, kind)
            c["layers"].add("reddit")
            c["reddit"].append({"t": p["t"][:200], "sub": p.get("sub", ""), "url": p["url"], "at": p.get("at", ""),
                                "snip": p.get("snip", "")[:300]})
            if BLOCK.search(p["t"]):
                c["blocked"] = True

    # --- Urban Dictionary: слово дня ---
    for w in extra.get("ud", []):
        if good_term(w["word"]):
            c = cand(w["word"], "slang")
            c["layers"].add("urban")
            c["ud_wotd"] = w["date"]

    # --- Know Your Meme ---
    for url, title in extra.get("kym", {}).items():
        k = term_key(title)
        if k in C:
            C[k]["layers"].add("kym")
            C[k]["kym"] = url
        elif good_term(title) and len(extra.get("kym", {})) <= 80:
            c = cand(title, "meme")
            c["layers"].add("kym")
            c["kym"] = url

    # --- Google Trends и Bluesky: только подтверждают уже найденное ---
    tr = extra.get("trends", [])
    for c in C.values():
        k = c["key"]
        if len(k) < 4:
            continue
        for t in tr:
            if k == term_key(t["q"]) or (len(k) >= 6 and k in term_key(t["q"])):
                c["layers"].add("trends")
                c["trends"] = t["q"] + (" (" + t["traffic"] + ")" if t["traffic"] else "")
                break
        for b in extra.get("bsky", []):
            if k == term_key(b) or (len(k) >= 6 and k in term_key(b)):
                c["layers"].add("bluesky")
                c["bluesky"] = b
                break

    # --- история термина ---
    day = today()
    out = []
    for k, c in C.items():
        term = max(c["forms"].items(), key=lambda z: (z[1], -len(z[0])))[0]
        if BLOCK.search(term):
            c["blocked"] = True
        h = st["terms"].get(k)
        if h is None:
            h = st["terms"][k] = {"first": day, "last": day, "days": 1}
        elif h["last"] != day:
            h["last"] = day
            h["days"] += 1
        c["term"] = term
        c["kind"] = max(c["kinds"].items(), key=lambda z: z[1])[0]
        c["first_seen"] = h["first"]
        c["days_seen"] = h["days"]
        out.append(c)
    return out


def score(c, sweeps, baseline=""):
    """Оценка: чем выше, тем вероятнее, что это свежий тренд без хорошего объяснения."""
    layers = len(c["layers"])
    s = 3.0 * layers
    why = ["этажей: %d (%s)" % (layers, ", ".join(sorted(c["layers"])))]
    if c["fresh"]:
        add = 2.0 * min(c["fresh2"], 3) + 1.0 * min(c["fresh"] - c["fresh2"], 3)
        s += add
        why.append("новых подсказок: %d (из них держатся 2+ дня: %d)" % (c["fresh"], c["fresh2"]))
    rd = len(c["reddit"])
    if rd:
        subs = len(set(p["sub"] for p in c["reddit"]))
        s += min(rd, 4) + (1 if subs >= 2 else 0)
        why.append("постов на Reddit за неделю: %d в %d разделах" % (rd, subs))
    ud = c.get("ud")
    if ud:
        if days_ago(ud["oldest"]) <= 120:
            s += 3
            why.append("сленг новый: первое определение %s" % ud["oldest"])
        elif days_ago(ud["newest"]) <= 45:
            s += 1.5
            why.append("сленг снова пишут: свежее определение %s" % ud["newest"])
        else:
            s -= 1
            why.append("сленг старый (с %s)" % ud["oldest"])
    if c.get("ud_wotd"):
        s += 1
    if sweeps >= 2 and baseline and c["first_seen"] > baseline and days_ago(c["first_seen"]) <= FRESH_DAYS:
        s += 2
        why.append("впервые замечен %s" % c["first_seen"])
    if c["rel"] >= 900:
        s += 1
    if c.get("wiki"):
        s -= 1
        why.append("есть статья Википедии: " + c["wiki"])
    big = c.get("big")
    if big is not None:
        s -= min(len(big), 6) * 0.5
        why.append("сильных объяснений в поиске: %d" % len(big) if big else "сильных объяснений в поиске нет")
        if not big:
            s += 2
    if layers == 1 and not c["fresh"] and rd <= 1:
        s -= 3                                           # один слабый сигнал — почти наверняка шум или старое
    c["score"] = round(s, 1)
    c["why"] = why
    return c["score"]


def enrich(cands, st, health):
    """Подтверждения для лучших: Urban Dictionary, Википедия, поиск, обсуждение на Reddit."""
    top = cands[:6 if QUICK else ENRICH_TOP]
    n_ud = n_wiki = 0
    err_ud = err_wiki = ""
    for c in top:
        try:
            c["ud"] = ud_define(c["term"])
            n_ud += 1
        except Exception as e:
            err_ud = str(e)[:100]
        time.sleep(random.uniform(0.8, 1.5))
        try:
            c["wiki"] = wiki_title(c["term"])
            n_wiki += 1
        except Exception as e:
            err_wiki = str(e)[:100]
        time.sleep(random.uniform(0.6, 1.2))
    (health.ok("urban_define", n_ud) if n_ud else health.fail("urban_define", err_ud or "не запрашивал"))
    (health.ok("wikipedia", n_wiki) if n_wiki else health.fail("wikipedia", err_wiki or "не запрашивал"))
    for c in top:
        score(c, st["sweeps"], st.get("baseline_day", ""))
    top.sort(key=lambda c: -c["score"])

    n = 0
    for c in top[:3 if QUICK else SERP_TOP]:
        q = ("what does %s mean" % c["term"]) if c["kind"] in ("slang", "saying", "quoted") else ("what is the %s %s" % (
            c["term"], c["kind"] if c["kind"] in ("trend", "challenge", "meme", "filter", "dance", "sound") else "trend"))
        res = serp(q)
        if res is None:
            health.fail("search", "поиск просит подождать после %d запросов" % n, n)
            break
        c["serp"] = res
        c["big"] = [h for h in res if any(b in h for b in BIG_EXPLAINERS)]
        n += 1
        time.sleep(random.uniform(3, 5) if QUICK else random.uniform(9, 16))
    else:
        health.ok("search", n)

    n, err = 0, ""
    for c in [c for c in top if c["reddit"]][:2 if QUICK else COMMENTS_TOP]:
        try:
            c["comments"] = reddit_comments(c["reddit"][0]["url"])
            n += 1
        except Exception as e:
            err = str(e)[:80]
            break
        time.sleep(random.uniform(5, 8) if QUICK else random.uniform(20, 32))
    (health.ok("reddit_comments", n) if n or not err else health.fail("reddit_comments", err))


def make_pack(st, health, started):
    extra = {"ud": ud_wotd(health), "kym": kym(health), "trends": google_trends(health), "bsky": bluesky(health)}
    cands = build_candidates(st, extra)
    skipped = sum(1 for c in cands if c["blocked"])
    cands = [c for c in cands if not c["blocked"]]
    for c in cands:
        score(c, st["sweeps"], st.get("baseline_day", ""))
    cands.sort(key=lambda c: -c["score"])
    enrich(cands, st, health)
    for c in cands:
        score(c, st["sweeps"], st.get("baseline_day", ""))
    cands.sort(key=lambda c: -c["score"])

    def slim(c):
        sg = sorted(c["suggest"], key=lambda x: (not x["new"], x["first"]), reverse=False)
        d = {"term": c["term"], "kind": c["kind"], "score": c["score"], "layers": sorted(c["layers"]), "why": c["why"],
             "first_seen": c["first_seen"], "days_seen": c["days_seen"],
             "suggest": [{"q": x["q"], "first": x["first"], "new": x["new"]} for x in sg[:8]],
             "reddit": sorted(c["reddit"], key=lambda p: p.get("at", ""), reverse=True)[:5]}
        for k in ("ud", "ud_wotd", "kym", "trends", "bluesky", "wiki", "serp", "big", "comments"):
            if c.get(k):
                d[k] = c[k]
        return d

    used = set(p["url"] for c in cands[:MAX_CANDIDATES] for p in c["reddit"])
    loose = [p for p in st["posts"].values() if p["url"] not in used and EXPLAIN_TITLE.search(p["t"]) and not BLOCK.search(p["t"])]
    loose.sort(key=lambda p: p.get("at", ""), reverse=True)
    newp = [(q, r) for q, r in st["phrases"].items() if phrase_is_fresh(r) and days_ago(r[1]) <= 2 and not BLOCK.search(q)]
    newp.sort(key=lambda z: (z[1][0], z[1][2]), reverse=True)
    return {"made": now_iso(), "version": VERSION,
            "run": {"started": started, "minutes": round((time.time() - T0[0]) / 60, 1), "sweeps": st["sweeps"],
                    "last_sweep": st["last_sweep"], "phrases_known": len(st["phrases"]), "posts_known": len(st["posts"]),
                    "candidates_total": len(cands), "skipped_by_rules": skipped,
                    "note": ("Первый обход: «новые подсказки» появятся со второго дня, пока оценка по остальным этажам."
                             if st["sweeps"] < 2 else "")},
            "health": dict(health),
            "candidates": [slim(c) for c in cands[:MAX_CANDIDATES]],
            "reddit_questions": [{"t": p["t"][:200], "sub": p.get("sub", ""), "url": p["url"], "at": p.get("at", "")} for p in loose[:120]],
            "new_phrases": [{"q": q, "first": r[0], "days": r[2]} for q, r in newp[:250]]}


T0 = [time.time()]


def write_top(pack):
    try:
        with open(TOP_TXT, "w", encoding="utf-8") as f:
            f.write("Радар трендов %s — лучшие кандидаты (%s)\n\n" % (VERSION, pack["made"][:16].replace("T", " ")))
            for i, c in enumerate(pack["candidates"][:40], 1):
                f.write("%2d. %-28s оценка %5.1f  [%s]\n      %s\n" % (i, c["term"], c["score"], c["kind"], "; ".join(c["why"])))
            f.write("\nИсточники:\n")
            for k, v in pack["health"].items():
                f.write("  %-16s %s\n" % (k, ("да, %s" % v["n"]) if v["ok"] else ("НЕТ: " + v.get("err", ""))))
    except Exception:
        pass


def upload(pack):
    names = [n for n in os.listdir(HERE) if n.lower().startswith("token")]
    if not names:
        log("Отправка на сайт: не нашёл файл token в этой папке — скопируй его сюда из папки сборщика трендов.")
        return False
    tok = re.sub(r"\s+", "", open(os.path.join(HERE, names[0]), encoding="utf-8-sig").read())
    if not tok.startswith(("github_pat_", "ghp_")):
        log("Отправка на сайт: в файле %s нет ключа GitHub." % names[0])
        return False
    url = "https://api.github.com/repos/%s/contents/%s" % (REPO, REPO_PATH)
    hdr = {"Authorization": "Bearer " + tok, "Accept": "application/vnd.github+json", "User-Agent": "trendrundown-radar"}
    body = json.dumps(pack, ensure_ascii=False).encode("utf-8")
    for attempt in range(4):
        try:
            sha = None
            try:
                with opener().open(urllib.request.Request(url + "?ref=main", headers=hdr), timeout=60) as r:
                    sha = json.loads(r.read().decode("utf-8")).get("sha")
            except urllib.error.HTTPError as e:
                if e.code != 404:
                    raise
            payload = {"message": "trend radar %s" % datetime.now().strftime("%Y%m%d_%H%M"),
                       "content": base64.b64encode(body).decode(), "branch": "main",
                       "committer": {"name": "trendrundown-laptop", "email": "laptop@trendrundown.com"}}
            if sha:
                payload["sha"] = sha
            req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="PUT",
                                         headers=dict(hdr, **{"Content-Type": "application/json"}))
            with opener().open(req, timeout=90) as r:
                r.read()
            log("Отправлено на сайт (laptop/radar.json, %d КБ)." % (len(body) // 1024))
            return True
        except urllib.error.HTTPError as e:
            if e.code in (401, 403, 404):
                log("Отправка на сайт: ключ не подходит (ошибка %s) — проверь файл token." % e.code)
                return False
            time.sleep(15)                   # 409 — сайт в эту секунду сам обновлялся, пробуем ещё
        except Exception as e:
            log("Отправка на сайт: %s" % str(e)[:120])
            time.sleep(20)
    return False


def cycle(st):
    T0[0] = time.time()
    started = now_iso()
    health = Health()
    log("Начинаю проход. Смотрю Reddit...")
    collect_reddit(st, health)
    save_state(st)
    need_sweep = QUICK or not st["last_sweep"] or st.get("cursor") or \
        (now_utc() - datetime.fromisoformat(st["last_sweep"])).total_seconds() >= SWEEP_HOURS * 3600
    if need_sweep:
        sweep_suggest(st, health)
        save_state(st)
    else:
        health["google_suggest"] = {"ok": True, "n": 0, "note": "сегодня уже обходил (%s)" % st["last_sweep"][:16]}
    log("Свожу этажи вместе и проверяю лучших...")
    pack = make_pack(st, health, started)
    cut = (now_utc() - timedelta(days=KEEP_PHRASE_DAYS)).strftime("%Y-%m-%d")
    st["phrases"] = {q: r for q, r in st["phrases"].items() if r[1] >= cut}
    st["terms"] = {k: h for k, h in st["terms"].items() if h["last"] >= cut}
    save_state(st)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump(pack, f, ensure_ascii=False, indent=1)
    write_top(pack)
    top = pack["candidates"][:8]
    log("Готово за %.0f мин. Кандидатов %d. Лучшие: %s" % (pack["run"]["minutes"], pack["run"]["candidates_total"],
                                                         " | ".join("%s (%.0f)" % (c["term"], c["score"]) for c in top)))
    bad = [k for k, v in health.items() if not v["ok"]]
    if bad:
        log("Не ответили источники: " + ", ".join(bad) + " — остальные работают, это не страшно.")
    if not NO_UPLOAD:
        upload(pack)
    return pack


def keep_awake():
    try:
        import ctypes
        if ctypes.windll.kernel32.SetThreadExecutionState(0x80000000 | 0x00000001):
            log("Сон компьютера отключён, пока открыто это окно.")
    except Exception:
        pass


def main():
    keep_awake()
    log("Радар трендов %s запущен. Окно не закрывай: проход каждые %d ч, первый займёт около 40–50 минут." % (VERSION, CYCLE_HOURS))
    st = load_state()
    while True:
        start = time.time()
        try:
            cycle(st)
        except KeyboardInterrupt:
            raise
        except Exception as e:
            log("ОШИБКА: " + str(e)[:300])
            try:
                with open(LOG, "a", encoding="utf-8") as f:
                    f.write(traceback.format_exc() + "\n")
            except Exception:
                pass
            try:
                save_state(st)
            except Exception:
                pass
        if ONCE:
            break
        rest = max(900, CYCLE_HOURS * 3600 - (time.time() - start))
        log("Следующий проход в %s." % (datetime.now() + timedelta(seconds=rest)).strftime("%H:%M"))
        time.sleep(rest)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
