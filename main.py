import os
import re
import json
import time
import tempfile
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
from openai import OpenAI
from pydub import AudioSegment
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.enums import TA_RIGHT
import arabic_reshaper
from bidi.algorithm import get_display

CHANNEL = os.getenv("TELEGRAM_CHANNEL", "@varjedagsvenska")
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
TEXT_MODEL = os.getenv("OPENAI_TEXT_MODEL", "gpt-5.6-luna")
TTS_MODEL = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")

client = OpenAI(api_key=OPENAI_API_KEY)

def stockholm_now():
    return datetime.now(ZoneInfo("Europe/Stockholm"))

def should_run():
    """GitHub runs at both 04:00 and 05:00 UTC; only local 06:xx continues."""
    if os.getenv("FORCE_RUN") == "1":
        return True
    return stockholm_now().hour == 6

def extract_json(text):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except Exception:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end+1])
        raise

def create_lesson():
    date = stockholm_now().strftime("%Y-%m-%d")
    prompt = f"""
Du är en professionell lärare i svenska som andraspråk.
Skapa dagens kompletta utbildningspaket för nivån B2-C1, datum {date}.
Innehållet ska kännas modernt, praktiskt och användbart i vardag, arbete och samhälle i Sverige.
Undvik att återanvända ett generiskt tema. Välj ett tydligt tema för dagen.

Returnera ENDAST giltig JSON med exakt denna struktur:
{{
  "title": "svensk titel",
  "intro": "2-3 meningar på svenska",
  "vocabulary": [
    {{"word":"...", "persian":"...", "example":"...", "example_persian":"..."}}
  ],
  "expressions": [
    {{"expression":"...", "persian":"...", "example":"...", "example_persian":"..."}}
  ],
  "grammar": {{
    "title":"...",
    "explanation_sv":"...",
    "explanation_fa":"...",
    "examples":[{{"sv":"...", "fa":"..."}}]
  }},
  "reading": {{
    "title":"...",
    "text":"ca 500-700 ord på naturlig svenska",
    "questions":["..."],
    "answers":["..."]
  }},
  "podcast": {{
    "title":"...",
    "turns":[
      {{"speaker":"Sara", "text":"..."}},
      {{"speaker":"Johan", "text":"..."}}
    ]
  }},
  "telegram_summary":"kort, attraktiv sammanfattning på svenska med emojis"
}}

Krav:
- Exakt 15 relevanta ord i vocabulary.
- Exakt 9 idiom/uttryck i expressions.
- Grammatikdelen ska vara B2-C1 och förklaras tydligt.
- Reading ska ha exakt 6 frågor och 6 korta svar.
- Podcasten ska vara en naturlig dialog mellan Sara och Johan, totalt ungefär 1100-1400 svenska ord,
  cirka 8-10 minuters tal. Minst 14 repliker. Ingen persiska i själva poddmanuset.
- Använd dagens ord, uttryck och grammatik naturligt i reading och podcast.
- Persiska översättningar ska vara korrekta och lättförståeliga.
"""
    resp = client.responses.create(model=TEXT_MODEL, input=prompt)
    lesson = extract_json(resp.output_text)
    return lesson

def tts_piece(text, voice, path):
    # API input max is 4096 chars. Split conservatively by sentence/space.
    chunks = []
    remaining = text.strip()
    while len(remaining) > 3500:
        cut = remaining.rfind(". ", 0, 3500)
        if cut < 1500:
            cut = remaining.rfind(" ", 0, 3500)
        chunks.append(remaining[:cut+1].strip())
        remaining = remaining[cut+1:].strip()
    if remaining:
        chunks.append(remaining)

    combined = AudioSegment.silent(duration=0)
    for i, chunk in enumerate(chunks):
        tmp = path.parent / f"{path.stem}_{i}.mp3"
        with client.audio.speech.with_streaming_response.create(
            model=TTS_MODEL,
            voice=voice,
            input=chunk,
            instructions="Tala naturlig, varm och tydlig standardsvenska i normal poddhastighet.",
            response_format="mp3",
        ) as response:
            response.stream_to_file(tmp)
        combined += AudioSegment.from_mp3(tmp)
        tmp.unlink(missing_ok=True)
    combined.export(path, format="mp3")

def make_podcast(lesson, out_path):
    voices = {"Sara": "marin", "Johan": "cedar"}
    combined = AudioSegment.silent(duration=350)
    tmp_dir = out_path.parent / "audio_parts"
    tmp_dir.mkdir(exist_ok=True)

    for idx, turn in enumerate(lesson["podcast"]["turns"]):
        speaker = turn.get("speaker", "Sara")
        voice = voices.get(speaker, "marin")
        part = tmp_dir / f"{idx:03d}.mp3"
        tts_piece(turn["text"], voice, part)
        audio = AudioSegment.from_mp3(part)
        combined += audio + AudioSegment.silent(duration=280)

    combined.export(out_path, format="mp3", bitrate="128k")

def fa(text):
    if not text:
        return ""
    reshaped = arabic_reshaper.reshape(str(text))
    return get_display(reshaped)

def make_pdf(lesson, out_path):
    font_candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
    ]
    font_path = next((p for p in font_candidates if Path(p).exists()), None)
    if font_path:
        pdfmetrics.registerFont(TTFont("Unicode", font_path))
        font = "Unicode"
    else:
        font = "Helvetica"

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("h1x", parent=styles["Heading1"], fontName=font, fontSize=20, leading=25, spaceAfter=12)
    h2 = ParagraphStyle("h2x", parent=styles["Heading2"], fontName=font, fontSize=14, leading=18, spaceBefore=10, spaceAfter=7)
    body = ParagraphStyle("bodyx", parent=styles["BodyText"], fontName=font, fontSize=10.5, leading=15, spaceAfter=6)
    rtl = ParagraphStyle("rtlx", parent=body, fontName=font, alignment=TA_RIGHT, leading=16)

    doc = SimpleDocTemplate(str(out_path), pagesize=A4, rightMargin=42, leftMargin=42, topMargin=42, bottomMargin=42)
    story = []
    story += [Paragraph(lesson["title"], h1), Paragraph(lesson.get("intro",""), body)]
    story += [Paragraph("1. Ordförråd / واژگان", h2)]
    for i, x in enumerate(lesson["vocabulary"], 1):
        story.append(Paragraph(f"<b>{i}. {x['word']}</b> — {x['example']}", body))
        story.append(Paragraph(fa(f"{x['persian']} — {x['example_persian']}"), rtl))

    story += [Paragraph("2. Uttryck / اصطلاحات", h2)]
    for i, x in enumerate(lesson["expressions"], 1):
        story.append(Paragraph(f"<b>{i}. {x['expression']}</b> — {x['example']}", body))
        story.append(Paragraph(fa(f"{x['persian']} — {x['example_persian']}"), rtl))

    g = lesson["grammar"]
    story += [Paragraph(f"3. Grammatik: {g['title']}", h2), Paragraph(g["explanation_sv"], body),
              Paragraph(fa(g["explanation_fa"]), rtl)]
    for x in g["examples"]:
        story.append(Paragraph("• " + x["sv"], body))
        story.append(Paragraph(fa(x["fa"]), rtl))

    r = lesson["reading"]
    story += [PageBreak(), Paragraph(f"4. Läsförståelse: {r['title']}", h2), Paragraph(r["text"].replace("\n","<br/>"), body)]
    story.append(Paragraph("Frågor", h2))
    for i, q in enumerate(r["questions"], 1):
        story.append(Paragraph(f"{i}. {q}", body))
    story.append(Paragraph("Facit", h2))
    for i, a in enumerate(r["answers"], 1):
        story.append(Paragraph(f"{i}. {a}", body))

    p = lesson["podcast"]
    story += [PageBreak(), Paragraph(f"5. Podcastmanus: {p['title']}", h2)]
    for t in p["turns"]:
        story.append(Paragraph(f"<b>{t['speaker']}:</b> {t['text']}", body))

    story += [Spacer(1, 12), Paragraph("Varje Dag Svenska • B2–C1", body)]
    doc.build(story)

def tg(method, **kwargs):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    r = requests.post(url, timeout=120, **kwargs)
    r.raise_for_status()
    data = r.json()
    if not data.get("ok"):
        raise RuntimeError(data)
    return data

def send_package(lesson, audio_path, pdf_path):
    date = stockholm_now().strftime("%d/%m/%Y")
    msg = (
        f"🇸🇪 <b>Varje Dag Svenska • B2–C1</b>\n"
        f"📅 {date}\n\n"
        f"🎯 <b>{lesson['title']}</b>\n"
        f"{lesson['telegram_summary']}\n\n"
        f"📚 15 ord • 9 uttryck • grammatik • läsförståelse\n"
        f"🎧 Podcast med två röster\n"
        f"📄 PDF med manus + persiska förklaringar\n\n"
        f"#svenska #B2 #C1 #lärsvenska"
    )
    tg("sendMessage", data={"chat_id": CHANNEL, "text": msg, "parse_mode": "HTML"})

    with open(audio_path, "rb") as f:
        tg("sendAudio", data={"chat_id": CHANNEL, "caption": f"🎧 {lesson['podcast']['title']}"},
           files={"audio": (audio_path.name, f, "audio/mpeg")})

    with open(pdf_path, "rb") as f:
        tg("sendDocument", data={"chat_id": CHANNEL, "caption": "📄 Dagens PDF: manus, ord, uttryck och grammatik"},
           files={"document": (pdf_path.name, f, "application/pdf")})

def main():
    if not should_run():
        print("Not 06:xx in Europe/Stockholm; exiting.")
        return

    out = Path("output")
    out.mkdir(exist_ok=True)
    stamp = stockholm_now().strftime("%Y-%m-%d")

    lesson = create_lesson()
    (out / f"lesson_{stamp}.json").write_text(json.dumps(lesson, ensure_ascii=False, indent=2), encoding="utf-8")

    audio = out / f"podcast_{stamp}.mp3"
    pdf = out / f"lektion_{stamp}.pdf"

    make_podcast(lesson, audio)
    make_pdf(lesson, pdf)
    send_package(lesson, audio, pdf)
    print("Published successfully:", stamp)

if __name__ == "__main__":
    main()
