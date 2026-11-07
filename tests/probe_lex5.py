# -*- coding: utf-8 -*-
"""Asosiy sahifadagi "Kodlar" tegi atrofidagi raw HTML (diagnostika 5)."""
import asyncio
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx  # noqa: E402

UA = {"User-Agent": "LexRagEvaluation/0.5 (public legal document lookup)"}


async def probe():
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=UA) as cli:
        response = await cli.get("https://lex.uz/uz/")
        html = response.text
        for match in re.finditer(r"[КK]odeks", html):
            start = max(0, match.start() - 250)
            end = min(len(html), match.end() + 400)
            print("----")
            print(html[start:end].replace("\n", " ")[:600])


asyncio.run(probe())
