# -*- coding: utf-8 -*-
"""Golden to'plam va batch natijalaridan 6-bo'lim metrikalarini hisoblaydi.

Kutilgan format:
- golden CSV: id,batch,category,question,expected_answer,expected_doc_id,expected_article,answerable
- runs katalog: run_id ichidagi b01.json ... b10.json (POST /v1/rag/batch javoblari)

Ishga tushirish:
    & .venv\\Scripts\\python.exe tests\\eval_metrics.py --golden golden.csv --runs runs\\eval-2026-11-07

Chek: Answer correctness va citation accuracy to'liq bahosi qo'lda yoki
LLM-hakam bilan beriladi; bu vosita taxminiy (proxy) ballni hisoblab,
baho uchun javoblar ro'yxatini ham chiqaradi.
"""
import argparse
import csv
import json
import re
import sys
from pathlib import Path
from statistics import mean

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ANSWERABLE = {"true", "1", "ha", "yes"}
STATUS_ERROR = {"error", "timeout"}
STALE_MARKERS = ("kuchi yoq", "kuchini yoqotgan", "bekor", "amaldan chiqqan", "утратил силу")
REF_RE = re.compile(r"\s*\[\d+\]")

TARGETS = {
    "doc_hit5": "≥ 90%",
    "article_hit5": "≥ 80%",
    "mrr": "≥ 0.70",
    "context_precision": "≥ 60%",
    "answer_correctness": "≥ 1.6/2 (taxminiy)",
    "faithfulness": "≥ 95% (qo'lda/LLM)",
    "citation_accuracy": "≥ 90% (qo'lda)",
    "fabricated_refs": "0",
    "stale_refs": "0",
    "no_answer_accuracy": "≥ 9/10",
    "error_share": "≤ 2%",
    "latency_p50": "≤ 5 s",
    "latency_p95": "≤ 12 s",
}


def percent(value):
    return f"{value * 100:.1f}%"


def tokens(text):
    cleaned = REF_RE.sub(" ", text or "")
    return {token.casefold().strip("'’ʻ") for token in re.findall(r"[\w'’ʻ-]+", cleaned) if len(token) > 2}


def token_f1(expected, actual):
    set_a, set_b = tokens(expected), tokens(actual or "")
    if not set_a or not set_b:
        return 0.0
    overlap = len(set_a & set_b)
    return 2 * overlap / (len(set_a) + len(set_b))


def proxy_score(expected, actual):
    """0/1/2 taxminiy ball: raqamlar ustuvor, so'ng token-F1."""
    numbers_expected = set(re.findall(r"\d[\d\s., ]*", expected or ""))
    numbers_actual = set(re.findall(r"\d[\d\s., ]*", actual or "")) if actual else set()
    if numbers_expected:
        if numbers_expected <= numbers_actual:
            return 2
        if numbers_expected & numbers_actual:
            return 1
        return 0
    f1 = token_f1(expected, actual)
    return 2 if f1 >= 0.7 else (1 if f1 >= 0.4 else 0)


def percentile(sorted_values, share):
    if not sorted_values:
        return None
    index = min(len(sorted_values) - 1, max(0, round(share * (len(sorted_values) - 1))))
    return sorted_values[index]


def load_results(runs_dir: Path):
    results = {}
    batches = sorted(runs_dir.glob("b*.json"))
    if not batches:
        raise SystemExit(f"{runs_dir} ichida b*.json topilmadi")
    for path in batches:
        body = json.loads(path.read_text(encoding="utf-8"))
        for result in body.get("results", []):
            if result["id"] in results:
                raise SystemExit(f"{result['id']} bir necha marta qaytgan")
            results[result["id"]] = result
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--golden", required=True)
    parser.add_argument("--runs", required=True)
    parser.add_argument("--out", default=None, help="Taxminiy baholar ro'yxati (CSV) yoziladi")
    args = parser.parse_args()

    golden = list(csv.DictReader(open(args.golden, encoding="utf-8-sig")))
    if not golden:
        raise SystemExit("Golden to'plam bo'sh")
    results = load_results(Path(args.runs))

    missing = [row["id"] for row in golden if row["id"] not in results]
    extra = [key for key in results if key not in {row["id"] for row in golden}]

    answerable_rows = [row for row in golden if (row.get("answerable") or "").casefold() in ANSWERABLE]
    non_answerable_rows = [row for row in golden if (row.get("answerable") or "").casefold() not in ANSWERABLE]

    doc_hits, article_hits, reciprocal_ranks, precisions = [], [], [], []
    proxy_scores, judge_list = [], []
    fabricated_citations, stale_citations, wrong_status = 0, 0, 0
    latencies, error_items, statuses = [], [], {"ok": 0, "no_answer": 0, "error": 0}

    for row in answerable_rows:
        result = results.get(row["id"]) or {}
        if not result:
            continue
        contexts = result.get("contexts") or []
        top5 = contexts[:5]
        doc_ids = {context.get("doc_id") for context in top5}
        articles = {context.get("article") for context in top5}
        expected_doc = (row.get("expected_doc_id") or "").strip()
        expected_article = (row.get("expected_article") or "").strip()

        doc_hit = expected_doc in doc_ids if expected_doc else None
        article_hit = expected_article in articles if expected_article else None
        if doc_hit is not None:
            doc_hits.append(1 if doc_hit else 0)
        if article_hit is not None:
            article_hits.append(1 if article_hit else 0)

        rank = next(
            (context["rank"] for context in top5
             if context.get("doc_id") == expected_doc
             and (not expected_article or context.get("article") == expected_article)),
            None,
        )
        reciprocal_ranks.append(1 / rank if rank else 0)

        relevant = sum(
            1 for context in top5
            if context.get("doc_id") == expected_doc
            and (not expected_article or context.get("article") == expected_article)
        )
        cells = min(5, len(contexts)) if contexts else 1
        precisions.append(min(relevant, cells) / cells)

        answer = result.get("answer") or ""
        proxy_scores.append(proxy_score(row.get("expected_answer", ""), answer))
        judge_list.append({
            "id": row["id"], "question": row["question"], "expected_answer": row.get("expected_answer", ""),
            "actual_answer": answer,
            "categories": row.get("category", ""),
            "citations": [
                {"doc_id": citation.get("doc_id"), "article": citation.get("article"),
                 "url": citation.get("url"), "quote": (citation.get("quote") or "")[:300]}
                for citation in result.get("citations") or []
            ],
        })

        context_chunk_ids = {context.get("chunk_id") for context in contexts}
        for citation in result.get("citations") or []:
            if citation.get("chunk_id") not in context_chunk_ids:
                fabricated_citations += 1
            status_text = (citation.get("doc_status") or "").casefold()
            if any(marker in status_text for marker in STALE_MARKERS):
                stale_citations += 1

        timing = result.get("timing") or {}
        if timing and timing.get("total_ms") is not None:
            latencies.append(timing["total_ms"])

    for row in non_answerable_rows:
        result = results.get(row["id"]) or {}
        if not result:
            continue
        if result.get("status") != "no_answer":
            wrong_status += 1  # javobsiz savolga to'qilgan javob

    for result in results.values():
        statuses[result.get("status", "error")] = statuses.get(result.get("status", "error"), 0) + 1
        if result.get("status") in STATUS_ERROR:
            error_items.append(result["id"])

    total = len(golden)
    error_share = len(error_items) / total if total else 1.0
    sorted_latencies = sorted(latencies)
    p50 = percentile(sorted_latencies, 0.50)
    p95 = percentile(sorted_latencies, 0.95)
    no_answer_hits = (len(non_answerable_rows) - wrong_status) if non_answerable_rows else 0

    def fmt(key, value):
        target = TARGETS[key]
        return {"metrika": key, "natija": value, "maqsad": target}

    report = [
        fmt("doc_hit5", percent(mean(doc_hits)) if doc_hits else "-"),
        fmt("article_hit5", percent(mean(article_hits)) if article_hits else "-"),
        fmt("mrr", f"{mean(reciprocal_ranks):.2f}" if reciprocal_ranks else "-"),
        fmt("context_precision", percent(mean(precisions)) if precisions else "-"),
        fmt("answer_correctness", f"{mean(proxy_scores):.2f}/2 (taxminiy)" if proxy_scores else "-"),
        fmt("faithfulness", "qo'lda/LLM-hakam uchun --out ro'yxati"),
        fmt("citation_accuracy", "qo'lda tekshirish uchun --out ro'yxati"),
        fmt("fabricated_refs", str(fabricated_citations)),
        fmt("stale_refs", str(stale_citations)),
        fmt("no_answer_accuracy", f"{no_answer_hits}/{len(non_answerable_rows)}"),
        fmt("error_share", percent(error_share)),
        fmt("latency_p50", f"{p50 / 1000:.1f} s" if p50 is not None else "-"),
        fmt("latency_p95", f"{p95 / 1000:.1f} s" if p95 is not None else "-"),
    ]

    print(f"Golden: {total} savol ({len(answerable_rows)} javobi bor / {len(non_answerable_rows)} javobsiz), natija: {len(results)}")
    if missing:
        print(f"Javobsiz qolgan savollar: {missing[:10]}{'...' if len(missing) > 10 else ''}")
    if extra:
        print(f"Golden'ga kirmagan savollar: {extra[:10]}")
    if error_items:
        print(f"Xatolar: {error_items[:10]}")
    statuses.pop("error", None)
    print("\n| Metrika | Natija | Maqsad |")
    print("|---|---|---|")
    for row in report:
        print(f"| {row['metrika']} | {row['natija']} | {row['maqsad']} |")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as output:
            json.dump(judge_list, output, ensure_ascii=False, indent=2)
        print(f"\nHakam uchun javoblar ro'yxati: {args.out}")


if __name__ == "__main__":
    main()
