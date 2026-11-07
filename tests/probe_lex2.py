# -*- coding: utf-8 -*-
"""Kodeks sahifalari qidirilganda nima topiladi (diagnostika 2)."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx  # noqa: E402

from app.lex_live import _chunks_from_document, _document_links  # noqa: E402

UA = {"User-Agent": "LexRagEvaluation/0.5 (public legal document lookup)"}
PROBES = [
    ("Mehnat kodeksi", {"searchtext": "Mehnat kodeksi", "lang": "4"}),
    ("searchtitle=Mehnat kodeksi", {"searchtitle": "Mehnat kodeksi", "lang": "4"}),
    ("Fuqarolik kodeksi", {"searchtext": "Fuqarolik kodeksi", "lang": "4"}),
]


async def probe():
    async with httpx.AsyncClient(timeout=25, follow_redirects=True, headers=UA) as cli:
        for label, params in PROBES:
            response = await cli.get("https://lex.uz/uz/search/all", params=params)
            links = _document_links(response.text)
            print(label, "->", links[:6])
            for url in links[:2]:
                doc = await cli.get(url)
                try:
                    chunks = _chunks_from_document(str(doc.url), doc.text, None)
                    print(f"   {url}: status={doc.status_code} chunklar={len(chunks)}", [c["article"] for c in chunks[:3]])
                except Exception as exc:  # noqa: BLE001
                    print(f"   {url}: status={doc.status_code} parse xato: {exc!r}")


asyncio.run(probe())
