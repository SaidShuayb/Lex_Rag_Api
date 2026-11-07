"""On-demand Lex.uz search and document extraction for environments with internet access.

Lex.uz does not expose a documented public JSON search API, so this adapter uses
the site's public search and document pages. The local JSONL index remains the
preferred and more reliable source for evaluation runs.
"""
import asyncio
import re
import time
from datetime import date
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, urlencode, urljoin, urlparse, urlunparse

import httpx


USER_AGENT = "LexRagEvaluation/0.5 (public legal document lookup)"
_cache: Dict[str, tuple[float, List[Dict[str, Any]]]] = {}
_cache_lock = asyncio.Lock()
_upstream_limit = asyncio.Semaphore(4)


class LexPageParser(HTMLParser):
    BLOCKS = {"p", "div", "br", "li", "tr", "td", "h1", "h2", "h3", "h4", "section"}
    SKIP = {"script", "style", "noscript", "svg"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text: List[str] = []
        self.links: List[tuple[str, str]] = []
        self.title = False
        self.title_parts: List[str] = []
        self.skip_depth = 0
        self.anchor_depth = 0
        self.anchor_href = ""
        self.anchor_text: List[str] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in self.SKIP:
            self.skip_depth += 1
        if tag == "title":
            self.title = True
        if tag == "a":
            self.anchor_depth += 1
            self.anchor_href = attrs.get("href", "")
            self.anchor_text = []
        if tag in self.BLOCKS:
            self.text.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.skip_depth:
            self.skip_depth -= 1
        if tag == "title":
            self.title = False
        if tag == "a" and self.anchor_depth:
            self.links.append((self.anchor_href, " ".join(self.anchor_text).strip()))
            self.anchor_depth -= 1
        if tag in self.BLOCKS:
            self.text.append("\n")

    def handle_data(self, data):
        if self.skip_depth:
            return
        clean = " ".join(data.split())
        if not clean:
            return
        self.text.append(clean)
        if self.title:
            self.title_parts.append(clean)
        if self.anchor_depth:
            self.anchor_text.append(clean)


def _clean_text(value: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in value.splitlines()]
    return "\n".join(line for line in lines if line)


def _document_links(html: str) -> List[str]:
    parser = LexPageParser()
    parser.feed(html)
    links = []
    for href, _ in parser.links:
        absolute = urljoin("https://lex.uz", href)
        parsed = urlparse(absolute)
        host = (parsed.hostname or "").casefold()
        if host not in {"lex.uz", "www.lex.uz"}:
            continue
        if re.search(r"/(?:docs|acts)/-?\d+", parsed.path):
            links.append(absolute)
    return list(dict.fromkeys(links))


def _source_language(text: str, hint: Optional[str] = None) -> str:
    if re.search(r"[\u049b\u0492\u04b3\u045e\u049a\u0493\u04b2\u040e]", text):
        return "uz-Cyrl"
    if re.search(r"[\u044b\u044d\u0451\u044a\u042b\u042d\u0401\u042a]", text):
        return "ru"
    if re.search(r"[\u0400-\u04ff]", text):
        return "uz-Cyrl" if hint == "uz-Cyrl" else "ru"
    return "uz-Latn"


def _split_relevant_chunks(content: str):
    article_re = re.compile(r"(?im)^\s*((?:\d{1,4}|[IVXLCDM]+)[-–— ]?(?:modda|модда|статья))\.?\s*[:–—-]?\s*")
    matches = list(article_re.finditer(content))
    segments = []
    if matches:
        for index, match in enumerate(matches):
            end = matches[index + 1].start() if index + 1 < len(matches) else len(content)
            article_text = content[match.start():end].strip()
            if len(article_text) > 80:
                segments.append((match.group(1).strip(), article_text))
    if not segments and content:
        size = 4000
        segments = [("modda aniqlanmadi", content[start:start + size]) for start in range(0, min(len(content), 30000), size)]
    return segments


def _chunks_from_document(url: str, html: str, as_of_date: Optional[date], language_hint: Optional[str] = None) -> List[Dict[str, Any]]:
    parser = LexPageParser()
    parser.feed(html)
    content = _clean_text("\n".join(parser.text))
    title = " ".join(parser.title_parts).strip() or "Lex.uz hujjati"
    path_match = re.search(r"/(?:docs|acts)/(-?\d+)", urlparse(url).path)
    doc_num = path_match.group(1).lstrip("-") if path_match else "unknown"
    doc_id = f"lex:{doc_num}"
    host = (urlparse(url).hostname or "").casefold()
    if host not in {"lex.uz", "www.lex.uz"}:
        raise ValueError("Manba URL lex.uz domenida bo'lishi kerak")

    segments = _split_relevant_chunks(content)

    query = parse_qs(urlparse(url).query)
    edition = (query.get("ONDATE") or query.get("ondate") or [None])[0]
    if edition:
        edition = edition[:10]
    else:
        # Use only an explicit date visible on the page; never claim today's date is an edition date.
        date_match = re.search(r"(?i)(?:tahrir|редакци)[^\n]{0,80}(\d{2}\.\d{2}\.\d{4})", content)
        edition = f"{date_match.group(1)[6:10]}-{date_match.group(1)[3:5]}-{date_match.group(1)[:2]}" if date_match else "unknown"

    status = "unknown"
    status_match = re.search(r"(?i)(amalda|kuchi(?:ni)? yo['’ʻ]?qotgan|bekor qilingan|действует|утратил силу)", content)
    if status_match:
        status = status_match.group(1)

    doc_type = "kodeks" if re.search(r"(?i)kodeks|кодекс|code", title) else "normativ-huquqiy hujjat"
    chunks = []
    for index, (article, text) in enumerate(segments):
        part_match = re.search(r"(?im)^\s*(\d+[- ]?(?:qism|қисм|часть))\b", text)
        chunks.append({
            "doc_id": doc_id,
            "doc_title": title,
            "doc_type": doc_type,
            "url": url,
            "article": article,
            "part": part_match.group(1) if part_match else None,
            "edition_date": edition,
            "doc_status": status,
            "chunk_id": f"{doc_id}#chunk-{index + 1}",
            "text": text[:12000],
            "language": _source_language(text, language_hint),
            "_as_of_date": as_of_date.isoformat() if as_of_date else None,
        })
    return chunks


async def search_lex(query: str, top_k: int, as_of_date: Optional[date] = None, language: Optional[str] = None) -> List[Dict[str, Any]]:
    locale = "ru" if language == "ru" else "uz"
    lex_language = {"ru": "1", "uz-Cyrl": "3", "uz-Latn": "4"}.get(language or "uz-Latn", "4")
    search_url = f"https://lex.uz/{locale}/search/all"
    cache_key = f"{locale}|{query.casefold()}|{top_k}|{as_of_date}"
    async with _cache_lock:
        cached = _cache.get(cache_key)
        if cached and cached[0] > time.monotonic():
            return [dict(item) for item in cached[1]]

    headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"}
    timeout = httpx.Timeout(12.0, connect=5.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
        search_terms = re.sub(r"\s+", " ", query).strip()[:350]
        stop_words = {"qancha", "qanday", "qaysi", "uchun", "haqida", "bo‘yicha", "bo'yicha", "что", "какой", "какая", "какие", "сколько", "установлен", "как", "the", "what", "how", "which"}
        title_terms = " ".join(token for token in re.findall(r"[\wʻ’'-]+", search_terms) if token.casefold() not in stop_words)[:250]
        result_html = ""
        urls: List[str] = []
        # Search field names have varied across Lex.uz UI versions. Try the
        # documented full-text field, its legacy URL parameter, then title search.
        for params in (
            {"searchtext": search_terms, "lang": lex_language},
            {"searchword": search_terms, "searchphrase": "all", "lang": lex_language},
            {"searchtitle": title_terms or search_terms, "lang": lex_language},
        ):
            async with _upstream_limit:
                response = await client.get(search_url, params=params)
            response.raise_for_status()
            result_html = response.text
            urls = _document_links(result_html)
            if urls:
                break
        urls = urls[:min(max(top_k, 3), 5)]
        if not urls:
            # A real zero-result page means no answer; an unexpected page is an upstream failure.
            if re.search(r"(?:0|no)\s+(?:documents?|hujjat|документ)", result_html, re.I):
                return []
            raise httpx.HTTPError("Lex.uz search page returned no document links")

        async def fetch(url):
            if as_of_date:
                parsed = urlparse(url)
                values = parse_qs(parsed.query)
                values["ONDATE"] = [as_of_date.isoformat()]
                url = urlunparse(parsed._replace(query=urlencode(values, doseq=True)))
            async with _upstream_limit:
                page = await client.get(url)
            page.raise_for_status()
            return _chunks_from_document(str(page.url), page.text, as_of_date, language)

        pages = await asyncio.gather(*(fetch(url) for url in urls), return_exceptions=True)
    chunks = [chunk for page in pages if isinstance(page, list) for chunk in page]
    if not chunks:
        raise httpx.HTTPError("Lex.uz documents could not be parsed")

    query_terms = set(re.findall(r"[\wʻ’'-]+", query.casefold()))
    scored = []
    for chunk in chunks:
        terms = set(re.findall(r"[\wʻ’'-]+", (chunk["article"] + " " + chunk["text"]).casefold()))
        overlap = len(query_terms & terms)
        if overlap:
            chunk["retrieval_score"] = overlap / max(1, len(query_terms))
            chunk["rerank_score"] = chunk["retrieval_score"]
            scored.append(chunk)
    scored.sort(key=lambda item: (-item["rerank_score"], item["chunk_id"]))
    result = scored[:top_k]
    for rank, chunk in enumerate(result, 1):
        chunk["rank"] = rank
        chunk.pop("_as_of_date", None)
    async with _cache_lock:
        _cache[cache_key] = (time.monotonic() + 900, [dict(item) for item in result])
    return result
