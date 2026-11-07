# -*- coding: utf-8 -*-
"""Haqiqiy Lex.uz hujjatlaridan evaluable JSONL korpus yig'adi.

Lex.uz ochiq qidiruvi orqali mavzular bo'yicha hujjatlarni topadi,
sahifalarni moddalarga ajratadi (app.lex_live) va tests/data
uchun o'zgarmas korpus faylini yozadi:

    & .venv\\Scripts\\python.exe tests\\build_live_corpus.py `
        --out data/lex_live_chunks.jsonl

Ogohlantirish: onlayn qidiruv tashqi tarmoqqa bog'liq; yig'ilgan
korpus "run_id" taqqoslash uchun barqaror snapshot sifatida saqlanadi.
"""
import argparse
import asyncio
import json
import sys
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.lex_live import search_lex  # noqa: E402

# Mavzular: spetsifikatsiya kategoriyalarini real hujjatlar bilan qoplash.
# (qidiruv, til, as_of_date yoki None)
QUERIES = [
    ("mehnat ta'tili muddati", "uz-Latn", None),
    ("ish haqi to'g'risida", "uz-Latn", None),
    ("ish vaqti registratorlar", "uz-Latn", None),
    ("mehnat kelishuvini bekor qilish javobgarlik", "uz-Latn", None),
    ("ishonchnoma imtiyozlar soliq", "uz-Latn", None),
    ("yer uchastkasi chegara jarayoniga o'tkazish", "uz-Latn", None),
    ("tadbirkorlik subyektlari reyestr to'g'risida", "uz-Latn", None),
    ("audit nazorati qanday amalga oshiriladi", "uz-Latn", None),
    ("ma'lumot konfidensiallik ruxsati", "uz-Latn", None),
    ("ishonchli hisob qaydnomasi to'g'risida", "uz-Latn", None),
    ("adliya organlarining huquqiy islohotlar", "uz-Latn", None),
    ("javobgarlik haqidagi kodeks hujjatlari", "uz-Latn", None),
    ("sud ijro organlari qarorlari", "uz-Latn", None),
    ("ishonchli daleri hujjat nazarda", "uz-Latn", None),
    ("Меҳнат таътили муддати", "uz-Cyrl", None),
    ("Адвокатура жавобгарлиги", "uz-Cyrl", None),
    ("Nodavlat notariat idoralari", "uz-Latn", None),
    ("Aholiga xizmat ko'rsatish qanday tartiblangan", "uz-Latn", None),
    ("ishonchli muddati tenderlarini o'tkazish tartibi", "uz-Latn", None),
    ("Гражданский кодекс исковая давность срок", "ru", None),
    ("Трудовой кодекс отпуск продолжительность", "ru", None),
    ("Налоговый кодекс льготы", "ru", None),
    # Eskirgan tahrirlarni ham yig'ish uchun o'tmish sanasi bilan:
    ("mehnat ta'tili muddati", "uz-Latn", date(2015, 6, 1)),
    ("ish haqi to'g'risida", "uz-Latn", date(2015, 6, 1)),
    ("solik imtiyozlar kichik biznes", "uz-Latn", date(2018, 1, 1)),
]


def _chunk_ok(chunk, seen_text):
    text = chunk["text"].strip()
    if len(text) < 80:
        return False
    fingerprint = text[:200].casefold()
    if fingerprint in seen_text:
        return False
    host = (urlparse(chunk["url"]).hostname or "").casefold()
    if host not in {"lex.uz", "www.lex.uz"}:
        return False
    return True


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data/lex_live_chunks.jsonl")
    parser.add_argument("--top-k", type=int, default=6, help="qidiruv natijasi: yig'iladigan chunk soni")
    parser.add_argument("--since", default=None, help="chunk_id/chiziq-dedup kesh fayli (ixtiyoriy)")
    args = parser.parse_args()

    rows, seen_chunks, seen_text = {}, set(), set()
    for query, language, as_of in QUERIES:
        try:
            chunks = await search_lex(query, args.top_k, as_of, language)
        except Exception as exc:  # noqa: BLE001
            print(f"[SKIP] {query!r} ({language}, as_of={as_of}): {exc.__class__.__name__}: {exc}")
            continue
        added = 0
        for chunk in chunks:
            if not _chunk_ok(chunk, seen_text):
                continue
            key = chunk["chunk_id"]
            if key in seen_chunks:
                # Xuddi shu modda boshqa qidiruvda: barqaror id saqlanadi.
                continue
            seen_chunks.add(key)
            seen_text.add(chunk["text"][:200].casefold())
            rows[key] = {k: v for k, v in chunk.items() if not k.startswith("_")}
            added += 1
        print(f"[OK]   {query!r} ({language}, as_of={as_of}) -> {added} chunk")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as stream:
        for row in rows.values():
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
    statuses = {}
    for row in rows.values():
        statuses[row["doc_status"]] = statuses.get(row["doc_status"], 0) + 1
    print(f"Korpus: {len(rows)} chunk -> {out}")
    print("Amal qilish holatlari:", statuses)


if __name__ == "__main__":
    asyncio.run(main())
