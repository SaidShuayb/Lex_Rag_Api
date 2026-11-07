# -*- coding: utf-8 -*-
"""Haqiqiy korpus (Lex.uz'dan yig'ilgan JSONL) dan 100 savolli golden to'plam yaratadi.

Format spetsifikatsiya 6-bo'limiga mos:
    id,batch,category,question,expected_answer,expected_doc_id,expected_article,answerable

MUHIM CHEGLOV: savollar haqiqiy moddalar matnidan avtomatik iborat
(savol kalitlari = manba gapining kalitlari), shu sababli Hit@k biroz
"qulay" chiqadi. Objektiv sporlar uchun jamoa bu savollarni o'zroq
yerda qayta yozishi kerak; CSV strukturasini saqlab qoladi — boshqa
qo'lliq qatorlar bilan aralashtirish mumkin.

    & .venv\\Scripts\\python.exe tests\\build_golden_live.py `
        --corpus data\\lex_live_chunks.jsonl `
        --out tests\\data\\golden_live.csv
"""
import argparse
import csv
import json
import os
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

NUM_RE = re.compile(r"\d[\d.,:%'-]*")
STOP = {
    "qonun", "qonuni", "boylacha", "tarzda", "shu", "boshqa", "bir", "ibu",
    "uchun", "yoki", "hamda", "bilan", "tomonidan", "huquq", "huquqi",
    "huquqlari", "mudda", "quyida", "kerak", "bo'ladi", "bog'loqlar",
}
TOKEN_RE = re.compile(r"[\wʻ’'-]+", re.UNICODE)


def keywords(sentence, limit=7):
    seen, unique = set(), []
    for token in TOKEN_RE.findall(sentence):
        low = token.casefold().replace("’", "'").replace("ʻ", "'")
        if len(low) < 4 or low in STOP or re.search(r"\d", low):
            continue
        if low not in seen:
            seen.add(low)
            unique.append(low)
    return unique[:limit]


def sentences(text):
    parts = re.split(r"(?<=[.!?])\s+", text.strip())
    return [part.strip() for part in parts if len(part.strip()) > 40]


def question_from(sentence, tail):
    keys = keywords(sentence)
    if len(keys) < 4:
        return None
    return " ".join(keys) + " " + tail


NOANSWER_QUESTIONS = [
    "Futbol jamoasi g'alaba ochkosi qanday belgilanadi?",
    "Choyxona xizmat haqi foizda qanday hisoblanadi?",
    "Piyoz yetishtirishni rag'batlantiruvchi subsidiya qaysi qonunda?",
    "Mehmonxona narxlari qaysi qonun bilan bog'liq?",
    "Televizor antenna or'restushingdagi qoidalar nima?",
    "Aviabilet orqaga qaytarilmasligi qanday rasmiylashtiriladi?",
    "Sabzi narxi qaysi qonunning chegarasida?",
    "Kompyuter garanaygning muddati kim tomonin bіlgilangan?",
    "Dorixona foydasi foizda qanday hal qilinadi?",
    "Futbol stadionining besh chali narxi qanday belgilanadi?",
]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", default="data/lex_live_chunks.jsonl")
    parser.add_argument("--out", default="tests/data/golden_live.csv")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    rows = [json.loads(line) for line in open(args.corpus, encoding="utf-8") if line.strip()]
    if len(rows) < 40:
        raise SystemExit(f"Korpus juda kichik: {len(rows)} chunk — oldin build_live_corpus.py ishga tushiring")

    random.seed(args.seed)

    pools = {"faktik": [], "raqamli": [], "kop_modda": [], "ozgargan": [], "ru": [], "uz_cyrl": []}
    for row in rows:
        sents = sentences(row["text"])
        if not sents:
            continue
        status_low = (row["doc_status"] or "").casefold()
        with_digits = [s for s in sents if NUM_RE.search(s)]
        without_digits = [s for s in sents if not NUM_RE.search(s)]
        base = {
            "doc_id": row["doc_id"], "article": row["article"], "chunk_id": row["chunk_id"],
            "title": row["doc_title"], "language": row.get("language") or "uz-Latn",
        }
        if without_digits:
            item = dict(base, sentences=without_digits)
            pools["faktik"].append(item)
        if with_digits:
            pools["raqamli"].append(dict(base, sentences=with_digits))
        if len(sents) >= 2 and without_digits:
            pools["kop_modda"].append(dict(base, sentences=sents))
        if without_digits and any(marker in status_low for marker in ("kuchi", "utratil", "bekor")):
            pools["ozgargan"].append(dict(base, sentences=without_digits))
        if row.get("language") == "ru":
            pools["ru"].append(dict(base, sentences=sents))
        if row.get("language") == "uz-Cyrl":
            pools["uz_cyrl"].append(dict(base, sentences=sents))

    print("Bakslarda mavjud chunclar:")
    for name, pool in pools.items():
        print(f"  {name}: {len(pool)}")

    counts = {
        "faktik": 35, "raqamli": 15, "kop_modda": 15, "ozgargan": 10,
        "ru": 10, "uz_cyrl": 4, "javobsiz": 10, "noaniq": 5,
    }
    # Kirildif pool bo'sh bo'lsa, o'sha qatorlarni metallik 'noaniq'ga o'tkaz (100 saqlanadi)
    cyr = len(pools["uz_cyrl"])
    if cyr < counts["uz_cyrl"]:
        counts["noaniq"] += counts["uz_cyrl"] - cyr
        counts["uz_cyrl"] = cyr

    golden, used_channels = [], set()

    def pick(pool):
        fresh = [item for item in pool if item["chunk_id"] not in used_channels]
        if not fresh:
            fresh = list(pool) or []
        if not fresh:
            return None
        return random.choice(fresh)

    for category, count in counts.items():
        if category == "javobsiz":
            continue
        for _ in range(count):
            item = pick(pools[category])
            if not item:
                break
            used_channels.add(item["chunk_id"])
            sents = item["sentences"]
            first = sents[0]
            expected_answer = first

            if category == "faktik":
                question = question_from(first, "qanday belgilangan?")
                if not question:
                    question = question_from(first, "qanday tartiblangan?")
            elif category == "raqamli":
                question = question_from(first, "qanchaga teng?")
                if not question:
                    question = question_from(first, "qancha?")
            elif category == "kop_modda":
                second = random.choice(sents[1:] or sents)
                keys = keywords(first, 5)[-3:] + keywords(second, 5)[:3]
                question = (" ".join(keys) + " qanday hujjatlarda?") if keys else None
            elif category == "ozgargan":
                question = question_from(first, "qanday tahririda belgilangan?")
            elif category == "ru":
                keys = keywords(first, 5)
                question = ("Какой срок " + " ".join(keys[:3]) + "?") if keys else None
                expected_answer = sents[0]
            elif category == "uz_cyrl":
                keys = keywords(first, 5)
                question = (" ".join(keys) + " нимани англатади?") if keys else None
            elif category == "noaniq":
                keys = keywords(first, 3)
                question = (" ".join(keys) + " umumiy tartibda nima?") if len(keys) >= 3 else None
            if not question:
                used_channels.discard(item["chunk_id"])
                continue
            golden.append({
                "id": None, "batch": None, "category": category,
                "question": question.strip(), "expected_answer": (expected_answer or "").strip(),
                "expected_doc_id": item["doc_id"], "expected_article": item["article"], "answerable": "true",
                "language": item["language"],
            })

    # 10 ta javobsiz: mahalliy BM25 topmasligi kerak — tekshiriladi
    os.environ["LEX_CORPUS_PATH"] = str(Path(args.corpus).resolve())
    from app.retrieval import search

    added_no_answer = 0
    for question in NOANSWER_QUESTIONS:
        if added_no_answer >= counts["javobsiz"]:
            break
        try:
            hits = search(question, 5, None)
        except Exception:  # noqa: BLE001
            hits = []
        if hits:
            print(f"[SKIP] javobsiz nomzod topdi qidiruvni: {question}")
            continue
        added_no_answer += 1
        golden.append({
            "id": None, "batch": None, "category": "javobsiz", "question": question,
            "expected_answer": "", "expected_doc_id": "", "expected_article": "", "answerable": "false",
            "language": "uz-Latn",
        })
    while added_no_answer < counts["javobsiz"]:
        added_no_answer += 1
        golden.append({
            "id": None, "batch": None, "category": "javobsiz",
            "question": f"Umumiy {added_no_answer} transistor ta'mirlovchi qanday qabul qilingan?",
            "expected_answer": "", "expected_doc_id": "", "expected_article": "", "answerable": "false",
            "language": "uz-Latn",
        })

    random.shuffle(golden)
    total = len(golden)
    for index, row in enumerate(golden, 1):
        row["id"] = f"q{index:03d}"
        row["batch"] = f"b{(index - 1) // 10 + 1:02d}"

    fields = ["id", "batch", "category", "question", "expected_answer", "expected_doc_id", "expected_article", "answerable", "language"]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in golden:
            writer.writerow({key: (row[key] if key in row else "") for key in fields})

    categories = {}
    for row in golden:
        categories[row["category"]] = categories.get(row["category"], 0) + 1
    print(f"Golden: {total} savol -> {out}")
    print("Kategoriyalar:", categories)


if __name__ == "__main__":
    main()
