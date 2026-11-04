"""Пробная озвучка одной страницы несколькими голосами (Kokoro + Piper). Запускается вручную на GitHub."""
import json, os, subprocess, sys
slug = sys.argv[1] if len(sys.argv) > 1 else "telerally"
x = json.load(open("data/topics.json"))["explainers"][slug]
text = x["title"] + ".\n\n" + x["answer"] + "\n\n" + x["body"]
os.makedirs("voice_out", exist_ok=True)
open("voice_out/text.txt", "w").write(text)

import numpy as np, soundfile as sf
from kokoro import KPipeline
pipe = KPipeline(lang_code="a")
for v in ["am_michael", "am_fenrir", "am_puck", "af_heart"]:
    audio = np.concatenate([a for _, _, a in pipe(text, voice=v, speed=0.95)])
    sf.write(f"voice_out/{v}.wav", audio, 24000)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", f"voice_out/{v}.wav", "-ac", "1", "-b:a", "48k",
                    f"voice_out/kokoro_{v}.mp3"], check=True)
    os.remove(f"voice_out/{v}.wav")

subprocess.run("piper --model en_US-ryan-high --data-dir /tmp/pv --download-dir /tmp/pv "
               "--output_file voice_out/ryan.wav < voice_out/text.txt", shell=True)
if os.path.exists("voice_out/ryan.wav"):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", "voice_out/ryan.wav", "-ac", "1", "-b:a", "48k",
                    "voice_out/piper_ryan.mp3"], check=True)
    os.remove("voice_out/ryan.wav")
print(os.listdir("voice_out"))
