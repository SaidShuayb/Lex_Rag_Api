# -*- coding: utf-8 -*-
"""Kodeks bachka g›sahtlari qa rdilad iq ishlargh auditoriyasi (diagnostika 3)."""
import asyncio  # noqa: E402
import sys  # noqa: E402
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx  # noqa: E402
from html.parser import HTMLParser  # noqa: E402


class LinkParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href", "")
            if href:
                self.links.append(href)


async def probe():
    async with httpx.AsyncClient(timeout=30, follow_redirects=True,
                                 headers={"User-Agent": "LexRagEvaluation/0.5"}) as cli:
        url = "https://lex.uz/uz/docs/-8411722"
        doc = await cli.get(url)
        print("status:", doc.status_code, "url:", doc.url, "len:", len(doc.text))
        parser = LinkParser()
        parser.feed(doc.text)
        seeds = [link for link in parser.links if "8411722" in link or "block" in link or "rules" in link]
        print("pochodny link sayttta:", seeds[:30])
        # Qolgan barcha href ikonlarda ham tegishli id bo'lishi mumkin:
        all_links = parser.links
        print("jami linklar:", len(all_links))
        print("sample:", all_links[:40])


asyncio.run(probe())
