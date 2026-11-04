"""Озвучка страниц голосом Michael (Kokoro, бесплатная открытая модель).
Берёт очередь data/narrate_queue.json (её пишет trend_site.py), делает mp3 в site/audio/, записывает data/audio.json.
Новости старше 14 дней — озвучку удаляем (место в хранилище)."""
import json, os, re, subprocess, sys, time
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUEUE = os.path.join(HERE, "data", "narrate_queue.json")
INDEX = os.path.join(HERE, "data", "audio.json")
OUT = os.path.join(HERE, "site")
VOICE, SPEED = "am_michael", 0.95
MAX_ITEMS = int(os.environ.get("NARRATE_MAX", "8"))
BUDGET = int(os.environ.get("NARRATE_SECONDS", "600"))

def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def age_days(iso):
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds() / 86400
    except Exception:
        return 0

index = json.load(open(INDEX)) if os.path.exists(INDEX) else {}
queue = json.load(open(QUEUE)) if os.path.exists(QUEUE) else []

# уборка: старые новости
for key in [k for k, v in index.items() if k.startswith("t/") and age_days(v.get("made", "")) > 14]:
    try:
        os.remove(os.path.join(OUT, index[key]["file"]))
    except OSError:
        pass
    index.pop(key)

todo = [q for q in queue if (index.get(q["key"]) or {}).get("hash") != q["hash"]][:MAX_ITEMS]
if todo:
    import numpy as np, soundfile as sf
    from kokoro import KPipeline
    pipe = KPipeline(lang_code="a")
    start = time.time()
    for q in todo:
        if time.time() - start > BUDGET:
            break
        text = re.sub(r"\s+", " ", q["text"]).strip()
        try:
            audio = np.concatenate([a for _, _, a in pipe(text, voice=VOICE, speed=SPEED)])
        except Exception as e:
            print("не озвучено", q["key"], e); continue
        rel = f"audio/{q['key']}.mp3"
        dst = os.path.join(OUT, rel); os.makedirs(os.path.dirname(dst), exist_ok=True)
        wav = dst[:-4] + ".wav"
        sf.write(wav, audio, 24000)
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", wav, "-ac", "1", "-b:a", "40k", dst], check=True)
        os.remove(wav)
        index[q["key"]] = {"file": rel, "hash": q["hash"], "made": now(), "sec": round(len(audio) / 24000)}
        print("озвучено", q["key"], index[q["key"]]["sec"], "с")
json.dump(index, open(INDEX, "w"), ensure_ascii=False, indent=0)
print("в очереди было", len(queue), "сделано", len(todo))
