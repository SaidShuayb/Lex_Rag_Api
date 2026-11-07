# -*- coding: utf-8 -*-
"""Golden to'plamni 10 talik batch'larga bo'lib ketma-ket yuboradi (b01 -> b10).

Spetsifikatsiya 1 va 3-bo'limlariga mos: har bir batch javobi kelgach
keyingisi yuboriladi, javoblar run katalogida saqlanadi:
    & .venv\\Scripts\\python.exe tests\\run_eval.py --golden golden.csv --base-url http://127.0.0.1:8000 --out runs\\eval-2026-11-07
"""
import argparse
import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import httpx  # noqa: E402
from app.config import RAG_API_KEY  # noqa: E402

BATCH_SIZE = 10
RETRY_DELAYS = (5, 15, 45)


def build_batches(rows, batch_size=BATCH_SIZE):
    """Har batch'a kategoriyalar aralash chiqishi uchun ketma-ket o'lchovda bo'linadi."""
    return [rows[index:index + batch_size] for index in range(0, len(rows), batch_size)]


def build_payload(run_id, batch_index, total, rows):
    return {
        "run_id": run_id,
        "batch_id": f"{run_id}-b{batch_index:02d}",
        "batch_index": batch_index,
        "total_batches": total,
        "options": {"top_k": 5, "return_contexts": True, "return_debug": True,
                    "temperature": 0, "seed": 42},
        "items": [
            {"id": row["id"], "question": row["question"].strip(), "language": (row.get("language") or "").strip() or None}
            for row in rows
        ],
    }


def submit(client, headers, payload):
    url = "/v1/rag/batch"
    for attempt, delay in enumerate((0, *RETRY_DELAYS), 1):
        if delay:
            time.sleep(delay)
        try:
            response = client.post(url, json=payload, headers=headers, timeout=150.0)
        except httpx.HTTPError as exc:
            print(f"  [attempt {attempt}] tarmoq xatosi: {exc.__class__.__name__}: {exc}")
            continue
        if response.status_code == 429:
            wait = float(response.headers.get("Retry-After", 1))
            print(f"  [attempt {attempt}] 429, {wait} s kutiladi")
            time.sleep(wait)
            continue
        if response.status_code == 202:
            print("  202 processing — GET bilan so'raladi")
            return poll(client, headers, payload["batch_id"])
        if response.status_code in (500, 503, 504):
            print(f"  [attempt {attempt}] {response.status_code}, qayta yuboriladi")
            continue
        if response.status_code == 401:
            raise SystemExit("401: API kalit noto'g'ri")
        if response.status_code == 409:
            raise SystemExit(f"409: {payload['batch_id']} boshqa mazmun bilan yuborilgan")
        if response.status_code == 400:
            raise SystemExit(f"400: validatsiya xatosi: {response.text}")
        response.raise_for_status()
        return response.json()
    raise SystemExit(f"{payload['batch_id']} 3 marta qayta yuborilgandan keyin ham bajarmadi")


def poll(client, headers, batch_id, timeout_minutes=5):
    deadline = time.time() + timeout_minutes * 60
    while time.time() < deadline:
        response = client.get(f"/v1/rag/batch/{batch_id}", headers=headers)
        if response.status_code == 200:
            return response.json()
        if response.status_code == 202:
            time.sleep(2)
            continue
        response.raise_for_status()
    raise SystemExit(f"GET /v1/rag/batch/{batch_id} {timeout_minutes} daqiqada tayyor bo'lmadi")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--golden", required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--out", required=True, help="runs katalogi, masalan runs/eval-2026-11-07")
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()

    rows = [row for row in csv.DictReader(open(args.golden, encoding="utf-8-sig")) if row.get("question", "").strip()]
    run_id = args.run_id or Path(args.out).name
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    batches = build_batches(rows)
    headers = {"Authorization": f"Bearer {RAG_API_KEY}"}
    base_url = args.base_url.rstrip("/")
    with httpx.Client(base_url=base_url, headers=headers) as client:
        print(f"{len(rows)} savol -> {len(batches)} batch ({base_url})")
        try:
            client.get("/v1/health", timeout=10).raise_for_status()
        except httpx.HTTPError as exc:
            raise SystemExit(f"Servisga ulanib bo'lmadi ({base_url}): {exc}")

        for index, chunk in enumerate(batches, 1):
            payload = build_payload(run_id, index, len(batches), chunk)
            print(f"b{index:02d}: {len(chunk)} savol yuborilmoqda...")
            body = submit(client, headers, payload)
            path = out_dir / f"b{index:02d}.json"
            path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
            summary = body.get("summary", {})
            print(f"b{index:02d}: saqlandi -> {path} (ok={summary.get('ok')}, no_answer={summary.get('no_answer')}, error={summary.get('error')})")
            if index < len(batches):
                time.sleep(1.0)  # spetsifikatsiya: kamida 1 batch/soniya
    print(f"Yakun: natijalar {out_dir} ichida. Metrikalar: python tests/eval_metrics.py --golden {args.golden} --runs {out_dir}")


if __name__ == "__main__":
    main()
