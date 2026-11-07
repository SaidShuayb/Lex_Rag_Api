# -*- coding: utf-8 -*-
"""Lex.uz live sahifalari strukturasini tekshirish (diagnostika)."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx  # noqa: E402

from app.lex_live import (  # noqa: E402
    LexPageParser,
    _chunks_from_document,
    _clean_text,
    _document_links,
    _split_relevant_chunks,
)

UA = {"User-Agent": "LexRagEvaluation/0.5 (public legal document lookup)"}


async def probe():
    async with httpx.AsyncClient(timeout=25, follow_redirects=True, headers=UA) as cli:
        response = await cli.get("https://lex.uz/uz/search/all", params={"searchtext": "mehnat ta'tili muddati", "lang": "4"})
        links = _document_links(response.text)
        print("qidiruv status:", response.status_code, "linklar:", links[:5])
        if not links:
            return
        doc = await cli.get(links[0])
        print("doc status:", doc.status_code, "url:", doc.url)
        parser = LexPageParser()
        parser.feed(doc.text)
        content = _clean_text("\n".join(parser.text))
        print("tozalangan matn uzunligi:", len(content))
        print("matn boshlanishi:", repr(content[:400]))
        print("title:", parser.title_parts[:3])
        segments = _split_relevant_chunks(content)
        print("segmentlar:", len(segments), [segment[0] for segment in segments[:5]])
        chunks = _chunks_from_document(str(doc.url), doc.text, None)
        print("chunklar:", len(chunks), [chunk["article"] for chunk in chunks[:5]])


asyncio.run(probe())
