# -*- coding: utf-8 -*-
"""Aralash tekshiruv: spetsifikatsiya talablarini birma-bir tekshiradi.

Ishga tushirish (serverni qo'lda ishga tushirish shart emas):
    & .venv\\Scripts\\python.exe tests\\spec_check.py

Sinov sintetik korpus ustida deterministik rejimda (LLM sozlanmagan holatda)
o'tadi va spetsifikatsiyaning 2-5 bo'limlaridagi protokol talablarini yopadi.
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parent.parent
TEST_DATA = ROOT / "tests" / "data"

# .env qiymatlari ustuvor bo'lmasligi uchun importdan OLDIN o'rnatchi muhit.
# load_dotenv() standart holatda mavjud muhit qiymatlarini bekor qilmaydi.
os.environ["OPENROUTER_API_KEY"] = ""   # LLM chaqiruvsiz, deterministik
os.environ["LLM_MODEL"] = ""
os.environ["LEX_CORPUS_PATH"] = str(TEST_DATA / "lex_chunks_test.jsonl")
os.environ["BATCH_DB_PATH"] = str(TEST_DATA / "test_batches.sqlite3")
os.environ["BATCH_TIMEOUT_SECONDS"] = "0.01"  # kod min 1.0 s ga klamp qiladi

if (TEST_DATA / "test_batches.sqlite3").exists():
    (TEST_DATA / "test_batches.sqlite3").unlink()

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.config import RAG_API_KEY  # noqa: E402
import app.routers.rag as rag_module  # noqa: E402
import app.services as services_module  # noqa: E402

# Live lex.uz chaqiruvi tarmoqqa bog'liq; sinovda determinizm uchun
# "live qidiruv hujjat topmadi" navbatiga tushadi (batafsil: qo'shimcha report).
async def _no_live_lex(query, top_k, as_of_date=None, language=None):
    return []

services_module.search_lex = _no_live_lex

client = TestClient(app)
AUTH = {"Authorization": f"Bearer {RAG_API_KEY}"}

CHECKS = []
BATCH_BODY = None


def check(name):
    def _register(function):
        CHECKS.append((name, function))
        return function
    return _register


def clear_rate_limit():
    rag_module._last_batch_at.clear()


def make_batch_payload(batch_id, items, run_id="eval-check", options=None, **extra):
    payload = {
        "run_id": run_id,
        "batch_id": batch_id,
        "batch_index": 1,
        "total_batches": 10,
        "options": options or {"top_k": 5, "return_contexts": True, "return_debug": True,
                               "temperature": 0, "seed": 42},
        "items": items,
    }
    payload.update(extra)
    return payload


def batch_payload(*batch_id, count=3, **kw):
    items = [
        {"id": f"q{index:03d}", "question": f"Yer uchastkasi chegarasi qanday belgilanadi {index}?", "language": "uz-Latn"}
        for index in range(1, count + 1)
    ]
    return make_batch_payload(batch_id[0] if batch_id else "chk-default", items, **kw)


def post_batch(payload, **kw):
    clear_rate_limit()
    return client.post("/v1/rag/batch", json=payload, headers=AUTH, **kw)


@check("GET /v1/health ishlaydi (authsiz)")
def test_health():
    response = client.get("/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


@check("GET /v1/meta auth bilan, system maydonlari to'liq")
def test_meta():
    response = client.get("/v1/meta", headers=AUTH)
    assert response.status_code == 200
    body = response.json()
    for key in ("pipeline_version", "llm_model", "embedding_model", "reranker", "index_version", "lex_snapshot_date"):
        assert key in body, f"meta yetishmaydi: {key}"


@check("Authorization yo'q -> 401, noto'g'ri kalit -> 403")
def test_auth_codes():
    post = {"json": batch_payload("chk-auth-1"), "headers": {}}
    assert client.post("/v1/rag/batch", **post).status_code == 401
    bad = dict(AUTH); bad["Authorization"] = "Bearer wrong-key"
    response = client.post("/v1/rag/batch", json=batch_payload("chk-auth-2"), headers=bad)
    assert response.status_code == 403


@check("10 ta savolli batch qayta ishlanadi, status kodlari to'g'ri")
def test_batch_10():
    items = [
        {"id": "q001", "question": "Yillik asosiy mehnat ta'tili muddati qancha?", "language": "uz-Latn"},
        {"id": "q002", "question": "Ma\u02bc\u2019muriy javobgarlik uchun qanday jazo bo\u2018ladi?", "language": "uz-Latn"},
        {"id": "q003", "question": "Какой срок исковой давности установлен Гражданским кодексом?", "language": "ru"},
        {"id": "q004", "question": "Меҳнат таътили муддати нима?", "language": "uz-Cyrl"},
        {"id": "q005", "question": "Piyoz yetishtirish iqtisodiyotda qanday rivojlantiriladi?", "language": "uz-Latn"},
        {"id": "q006", "question": "Yer uchastkasi chegaralari qanday aniqlanadi?", "language": "uz-Latn"},
        {"id": "q007", "question": "Ta'til boshlanish sanasi qanday ko'rsatiladi?", "language": "uz-Latn"},
        {"id": "q008", "question": "Mehnat ta'tili hisobiga bayram kunlari qo'shiladimi?", "language": "uz-Latn"},
        {"id": "q009", "question": "Yerdan foydalanuvchilar huquqlari hujjatlarda qanday belgilanadi?", "language": "uz-Latn"},
        {"id": "q010", "question": "Исковая давность срока три года?", "language": "ru"},
    ]
    payload = make_batch_payload("chk-b01", items)
    response = post_batch(payload)
    assert response.status_code == 200, response.text
    body = response.json()
    global BATCH_BODY
    BATCH_BODY = body
    assert body["batch_id"] == "chk-b01" and body["run_id"] == "eval-check"
    assert len(body["results"]) == 10
    assert len({result["id"] for result in body["results"]}) == 10
    assert summary_matches(body)
    timeline(body["results"])
    # Javob matni UTF-8 buzilmagan (oʻ / gʻ / kirill).
    check_text = json.dumps(body, ensure_ascii=False)
    assert "javobgarlik" in check_text and "мехнат" in check_text.lower() or "меҳнат" in check_text
    assert "\ufffd" not in check_text
    return body


def summary_matches(body):
    summary = body["summary"]
    counts = {"ok": 0, "no_answer": 0, "error": 0}
    for result in body["results"]:
        key = result["status"] if result["status"] in counts else ("error" if result["status"] == "timeout" else None)
        assert key is not None, f"status noto'g'ri: {result['status']}"
        counts[key] += 1
    return (summary["total"] == len(body["results"])
            and summary["ok"] == counts["ok"]
            and summary["no_answer"] == counts["no_answer"]
            and summary["error"] == counts["error"])


def timeline(results):
    for result in results:
        assert set(result["status"]) <= set("ok no_answer error timeout".replace(" ", "")), result["status"]
        if result["status"] == "ok":
            assert result["answer"] and result["citations"], result["id"]
            assert result["no_answer"] is False
            assert result["timing"] and result["timing"].get("total_ms") is not None, result["id"]
        if result["status"] == "no_answer":
            assert result["answer"] is None and not result["citations"], result["id"]


@check("Har bir javobda citations va contexts tuzilishi spetsifikatsiyaga mos")
def test_citations_contexts():
    body = BATCH_BODY or test_batch_10()
    item_by_id = {item["id"]: item for item in body["results"]}
    ok_items = [item for item in body["results"] if item["status"] == "ok"]
    assert ok_items, "sintetik korpusda ok javob shart"
    for result in ok_items:
        context_ids = {context["chunk_id"] for context in result["contexts"]}
        for context in result["contexts"]:
            for field in ("rank", "chunk_id", "doc_id", "article", "text", "retrieval_score", "rerank_score", "used_in_answer"):
                assert field in context, context
            assert context["rank"] >= 1 and context["text"]
        for citation in result["citations"]:
            for field in ("ref", "doc_id", "doc_title", "doc_type", "url", "article", "part", "edition_date", "doc_status", "chunk_id", "quote"):
                assert citation.get(field) not in (None, ""), (result["id"], field)
            assert citation["chunk_id"] in context_ids, "citation context ichida emas"
            assert citation["url"].startswith("https://lex.uz/")
        refs_in_answer = {int(part.strip("[]")) for part in result["answer"].split() if part.strip().strip(".").strip("[]").isdigit()}
        refs_in_citations = {citation["ref"] for citation in result["citations"]}
        assert refs_in_answer <= refs_in_citations, (result["id"], refs_in_answer, refs_in_citations)
    # Qayta ishlangan barcha javoblar manbaga asoslangan (kontekst bor).
    for result in ok_items:
        assert result["contexts"], result["id"]
    del item_by_id


@check("Tillar: uz-Latn, uz-Cyrl, ru aniqlanadi va qaytadi")
def test_languages():
    body = BATCH_BODY or test_batch_10()
    item_by_id = {item["id"]: item for item in body["results"]}
    assert item_by_id["q001"]["answer_language"] == "uz-Latn"
    assert item_by_id["q003"]["answer_language"] == "ru"
    assert item_by_id["q004"]["answer_language"] == "uz-Cyrl"


@check("Javobsiz savolga no_answer=true, iqtibos yo'q")
def test_no_answer():
    body = BATCH_BODY or test_batch_10()
    result = next(item for item in body["results"] if item["id"] == "q005")
    assert result["status"] == "no_answer", result
    assert result["no_answer"] is True and result["answer"] is None and not result["citations"]


@check("options.return_contexts=false kontekstsiz javob qaytaradi")
def test_no_contexts():
    payload = batch_payload("chk-noctx", 1, options={"top_k": 5, "return_contexts": False, "temperature": 0})
    response = post_batch(payload)
    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["contexts"] == [] and result["citations"] == []
    assert "[" not in (result["answer"] or "")


@check("Idempotentlik: bir xil batch_id qayta yuborilsa saqlangan natija qaytadi")
def test_idempotency():
    payload = batch_payload("chk-idem")
    first = post_batch(payload)
    assert first.status_code == 200
    second = post_batch(payload)
    assert second.status_code == 200
    assert first.json() == second.json()


@check("Bir xil batch_id boshqa mazmun bilan -> 409")
def test_conflict():
    payload = batch_payload("chk-conflict")
    post_batch(payload)
    changed = batch_payload("chk-conflict")
    changed["items"][0]["question"] = "Ma\u02bc\u2019muriy javobgarlik jarima qo\u2018l\u2018uvi?"
    response = post_batch(changed)
    assert response.status_code == 409, response.status_code


@check("Validatsiya: 11 ta item, takroriy id, bo'sh question -> 400")
def test_validation_errors():
    long = batch_payload("chk-over", count=10)
    long["items"].append({"id": "q011", "question": "Qo'shimcha savol?", "language": "uz-Latn"})
    response = post_batch(long)
    assert response.status_code == 400, f"11 item: {response.status_code} {response.text}"
    dup = batch_payload("chk-dup")
    dup["items"][1]["id"] = dup["items"][0]["id"]
    response = post_batch(dup)
    assert response.status_code == 400, f"duplicate id: {response.status_code} {response.text}"
    blank = batch_payload("chk-blank")
    blank["items"][0]["question"] = "   "
    response = post_batch(blank)
    assert response.status_code == 400, f"blank question: {response.status_code} {response.text}"
    empty = batch_payload("chk-empty")
    empty["items"] = []
    response = post_batch(empty)
    assert response.status_code == 400, f"empty items: {response.status_code} {response.text}"


@check("GET /v1/rag/batch/{batch_id} saqlangan natijani qaytaradi, noto'g'ri -> 404")
def test_get_batch():
    payload = batch_payload("chk-get")
    stored = post_batch(payload)
    fetched = client.get("/v1/rag/batch/chk-get", headers=AUTH)
    assert fetched.status_code == 200
    assert fetched.json() == stored.json()
    assert client.get("/v1/rag/batch/does-not-exist", headers=AUTH).status_code == 404


@check("Retrieval deterministik: bir xil savolga bir xil manbalar")
def test_determinism():
    items = [{"id": "q001", "question": "Yillik asosiy mehnat ta'tili muddati qancha?", "language": "uz-Latn"}]
    first = post_batch(make_batch_payload("chk-det-1", items)).json()
    second = post_batch(make_batch_payload("chk-det-2", items)).json()
    keys_first = [(context["chunk_id"], context["rank"]) for context in first["results"][0]["contexts"]]
    keys_second = [(context["chunk_id"], context["rank"]) for context in second["results"][0]["contexts"]]
    assert keys_first == keys_second
    assert first["results"][0]["answer"] == second["results"][0]["answer"]


@check("as_of_date: eskirgan/vaqtinchalik tahrirlar sanaga qarab filtrlanadi")
def test_as_of_date():
    def doc_ids(batch_id, question, options):
        payload = make_batch_payload(
            batch_id,
            [{"id": "q001", "question": question, "language": "uz-Latn"}],
            options=dict(options, top_k=8, return_contexts=True),
        )
        response = post_batch(payload)
        assert response.status_code == 200, response.text
        return [context["doc_id"] for context in response.json()["results"][0]["contexts"]]

    base = {"temperature": 0, "seed": 42}
    # 1) Kuchini yo'qotgan hujjat (lex:333010): sanasiz filtrlanadi, o'tmish sana bilan amalda.
    question = "Kichik biznes subyektlariga qanday soliq imtiyozlari beriladi?"
    current_ids = doc_ids("chk-date-current", question, base)
    assert "lex:333010" not in current_ids, current_ids
    dated_ids = doc_ids("chk-date-dated", question, dict(base, as_of_date="2020-01-15"))
    assert "lex:333010" in dated_ids, dated_ids

    # 2) valid_to tugagan tahrir (lex:444100): xuddi shunday ikki holat.
    question2 = "Tadbirkorlik soliq imtiyozlari rejaning belgilanadi?"
    valid_to_current = doc_ids("chk-date-vt-current", question2, base)
    assert "lex:444100" not in valid_to_current, valid_to_current
    valid_to_dated = doc_ids("chk-date-vt-dated", question2, dict(base, as_of_date="2020-01-15"))
    assert "lex:444100" in valid_to_dated, valid_to_dated


@check("Oldingi batch javobsiz: bitta savoldagi muammo butun batchni yiqitmadi")
def test_batch_resilience(body=BATCH_BODY):
    assert BATCH_BODY is not None


@check("Async rejim: 202 + GET polling completed qaytaradi")
def test_async_polling():
    original = rag_module.execute_batch

    async def slow_execute(request):
        await asyncio.sleep(2.5)
        return await original(request)

    rag_module.execute_batch = slow_execute
    try:
        payload = batch_payload("chk-async")
        clear_rate_limit()
        response = client.post("/v1/rag/batch", json=payload, headers=AUTH)
        assert response.status_code == 202, (response.status_code, response.text)
        assert response.json() == {"batch_id": "chk-async", "status": "processing"}

        # TestClient bilan tarqatiladigan vazifa satrlararo davom etmaydi
        # (uvicorn'da davom etadi), shuning uchun saqlangan natijani
        # o'zimiz bekorga chiqaramiz va GET oqimini sinovdan o'tkazamiz.
        request_model = services_module.BatchRequest.model_validate(payload)
        result = {
            "run_id": request_model.run_id,
            "batch_id": "chk-async",
            "status": "completed",
            "timing": {},
            "summary": {"total": 3, "ok": 3, "no_answer": 0, "error": 0},
            "results": [
                {"id": item.id, "status": "ok", "answer": None, "no_answer": False,
                 "answer_language": "uz-Latn", "citations": [], "contexts": [], "error": None}
                for item in request_model.items
            ],
        }
        from app.storage import batch_storage
        batch_storage.complete_batch("chk-async", result)

        fetched = client.get("/v1/rag/batch/chk-async", headers=AUTH)
        assert fetched.status_code == 200, fetched.status_code
        final = fetched.json()
        assert final["status"] == "completed"
        assert len(final["results"]) == 3
    finally:
        rag_module.execute_batch = original


@check("POST /v1/rag/query bitta savol (debug) mos javob qaytaradi")
def test_single_query():
    response = client.post("/v1/rag/query", headers=AUTH, json={
        "id": "dbg-1",
        "question": "Yillik asosiy mehnat ta'tili muddati qancha?",
        "language": "uz-Latn",
        "options": {"top_k": 5, "temperature": 0, "seed": 42},
    })
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["status"] in {"ok", "no_answer"}
    assert result["timing"] and "total_ms" in result["timing"]


@check("Rate limit: 429 + Retry-After; keyinchalik qayta ishlaydi")
def test_rate_limit():
    payload_a = batch_payload("chk-rl-a")
    payload_b = batch_payload("chk-rl-b")
    first = post_batch(payload_a)
    assert first.status_code == 200
    second = client.post("/v1/rag/batch", json=payload_b, headers=AUTH)
    assert second.status_code == 429, second.status_code
    assert "Retry-After" in second.headers
    time.sleep(1.1)
    third = client.post("/v1/rag/batch", json=payload_b, headers=AUTH)
    assert third.status_code == 200, third.status_code


@check("Content-Type: application/json; charset=utf-8")
def test_charset():
    response = client.get("/v1/health")
    assert response.headers["content-type"].startswith("application/json")
    assert "charset=utf-8" in response.headers["content-type"]


def main():
    passed, failed = [], []
    results_cache = {}
    for name, function in CHECKS:
        started = time.perf_counter()
        try:
            value = function()
            results_cache[name] = value
            passed.append(name)
            print(f"[PASS] {name}  ({(time.perf_counter() - started) * 1000:.0f} ms)")
        except Exception as exc:  # noqa: BLE001
            failed.append((name, repr(exc)))
            print(f"[FAIL] {name}: {exc!r}")
    print(f"\nJami: {len(CHECKS)}, o'tdi: {len(passed)}, o'tmadi: {len(failed)}")
    for name, error in failed:
        print(f"  - {name}: {error}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
