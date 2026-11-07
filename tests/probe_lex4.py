# -*- coding: utf-8 -*-
"""lex.uz asosiy menyudan kodlar ro'yxatini topish (diagnostika 4)."""
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx  # noqa: E402
from app.lex_live import LexPageParser  # noqa: E402

UA = {"User-Agent": "LexRagEvaluation/0.5 (public legal document lookup)"}


async def probe():
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=UA) as cli:
        for url in ("https://lex.uz/uz/", "https://lex.uz/uz/kodlar", "https://lex.uz/uz/codes/all"):
            response = await cli.get(url)
            parser = LexPageParser()
            parser.feed(response.text)
            text = "\n".join(parser.text)
            # "Kodlar" nomi atrofidagi qatorlarni ko'rish
            hits = [line for line in text.split("\n") if "kodeks" in line.casefold()][:15]
            links = [attribute for attribute in parser.links]
            doc_links = list(dict.fromkeys(link for link, _ in links if "/doc" in link))[:15]
            print(f"\nURL: {url} status={response.status_code} len={len(response.text)} doc-links={doc_links[:10]}")
            for line in hits:
                print("   ", line[:110])


asyncio.run(probe())
