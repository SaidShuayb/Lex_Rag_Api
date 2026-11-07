# Lex.uz RAG API — qayta tekshiruv hisoboti

**Tekshiruv sanasi:** 2026-11-07  
**Kod holati:** savol bo‘yicha Lex.uz qidiruv sahifasini chaqirish, hujjat sahifalarini olish va matnni modda/chunklarga ajratish qo‘shilgan. Mahalliy JSONL indeks, `as_of_date` filtri va tahminiy baholash vositalari sinovdan o‘tgan.  
**Muhim cheklov:** haqiqiy Lex.uz’dan jonli hujjat olish bu muhitda tashqi tarmoqqa bog‘liq. Quyidagi qayta tekshiruv deterministik sinov muhitida (sintetik korpus, LLM sozlanmagan holat) bajarildi; qaerda jonli Lex.uz va golden to‘plam ham kerak ekanligi quyida ko‘rsatilgan.

## Aralash tekshiruv — 2026-11-07 (tests/)

Spetsifikatsiyaning 2–5 bo‘limlari (protokol talablari) endi **avtomatik tekshiriladi** va hammasi o‘tdi: **19/19 PASS**.

Ishga tushirish (serverni qo‘lda ishga tushirish shart emas):

```powershell
& .venv\Scripts\python.exe tests\spec_check.py
```

| # | Tekshiruv | Natija |
|---:|---|---|
| 1 | `GET /v1/health`, `GET /v1/meta` (system maydonlari to‘liq) | PASS |
| 2 | Auth: yo‘q → 401, noto‘g‘ri kalit → 403 | PASS |
| 3 | 10 ta savolli batch (uz-Latn, uz-Cyrl, ru aralash), UTF-8 (oʻ/gʻ) buzilmaydi | PASS |
| 4 | `citations` tuzilishi: doc_id, url, article, part, edition_date, doc_status, quote; `chunk_id` context ichida; javobdagi `[n]` ↔ `citations` mos | PASS |
| 5 | Tillar: `answer_language` uz-Latn / uz-Cyrl / ru | PASS |
| 6 | Javobsiz savol → `no_answer: true`, iqtibos yo‘q | PASS |
| 7 | `return_contexts=false` → kontekstsiz javob | PASS |
| 8 | Idempotentlik: bir xil `batch_id` → saqlangan natija | PASS |
| 9 | Bir xil `batch_id`, boshqa mazmun → 409 | PASS |
| 10 | Validatsiya: 11 item / takroriy id / bo‘sh question → 400 | PASS |
| 11 | `GET /v1/rag/batch/{batch_id}`, noto‘g‘ri id → 404 | PASS |
| 12 | Determinizm: bir xil savol → bir xil manbalar | PASS |
| 13 | `as_of_date`: kuchini yo‘qotgan hujjat faqat o‘tgan sana ko‘rinishida qaytadi | PASS |
| 14 | Async: 202 `processing` → `GET` polling → `completed` | PASS |
| 15 | Rate limit: 429 + `Retry-After`, keyin ishlashni davom ettiradi | PASS |
| 16 | `Content-Type: application/json; charset=utf-8` | PASS |
| 17 | `POST /v1/rag/query` (debug, bitta savol) | PASS |

Bitta tuzatish kiritildi: `app/retrieval.py` — endi sanasiz so‘rovda ham `valid_to` muddati o‘tgan tahrirlar hozirgi ko‘rinishda **qaytmaydi** (avval faqat `doc_status` bo‘yicha tekshirilgan edi; spetsifikatsiyaning “eskirgan norma: 0 ta” mezoniga mos). Yaxlitlik: `valid_from` kelajakda bo‘lsa ham bugungi ko‘rinishda chiqmaydi.

Baholash vositalari ham qo‘shildi:

```powershell
# 1) 100 savolni 10 tadan ketma-ket yuborish, javoblar runs/eval-... ichida:
& .venv\Scripts\python.exe tests\run_eval.py --golden tests\data\golden_example.csv --out runs\demo-eval

# 2) 6-bo‘lim metrikalari (Hit@5, MRR, context precision, no-answer, latency, xato ulushi):
& .venv\Scripts\python.exe tests\eval_metrics.py --golden tests\data\golden_example.csv --runs runs\demo-eval --out runs\demo-eval\judge.json
```

Namoyaviy yakun (tests/data/golden_example.csv, 7 savolli sintetik korpus): doc Hit@5 100%, modda Hit@5 100%, MRR 1.00, context precision 80%, no-answer 2/2, xato ulushi 0%, to‘qilgan/eskirgan havola 0. `answer_correctness` bu vositada faqat taxminiy (proxy) bo‘ladi; yakuniy ball va faithfulness `judge.json` ro‘yxati bo‘yicha qo‘lda yoki LLM-hakam bilan beriladi.

Yakuniy qiymat bahosi (real 100 savol) uchun hali kerak: haqiqiy lex.uz hujjatlari korpusi (`LEX_CORPUS_PATH`) va tester tomonidan 100 savoldan iborat golden to‘plam.

## Spetsifikatsiya metrikalari (eski qayta tekshiruv — 2026-11-06)

| № | Mezon | Maqsad | Qayta tekshiruv natijasi | Holat |
|---:|---|---:|---|---|
| 1 | Hujjatni topish — Hit@5 | ≥ 90% | Haqiqiy Lex.uz natijalarini golden manbalar bilan taqqoslaydigan test to‘plami yo‘q; live qidiruv ulanish xatosi bilan tugadi. | Hisoblanmadi |
| 2 | Moddani topish — Hit@5 | ≥ 80% | Kutilgan hujjat va modda ID’lari bo‘lgan golden to‘plam yo‘q. | Hisoblanmadi |
| 3 | Retrieval — MRR | ≥ 0.70 | Haqiqiy qidiruv natijalarini kutilgan modda tartibi bilan solishtirish imkoni bo‘lmadi. | Hisoblanmadi |
| 4 | Javob to‘g‘riligi | O‘rtacha ≥ 1.6 / 2 | Kutilgan javoblar yo‘q; javoblar sifatiga ball berilmadi. | Hisoblanmadi |
| 5 | Manbaga sodiqlik — Faithfulness | ≥ 95% | Haqiqiy Lex.uz konteksti va javoblar bilan da’volar tekshirilmadi. | Hisoblanmadi |
| 6 | Citation aniqligi | ≥ 90% | Sintetik manbada citation chunk ID mos context ichida ekanligi tekshirildi. Haqiqiy manbaning ishonchliligi tasdiqlanmadi. | Qisman tekshirildi |
| 7 | Javobsiz savollarni to‘g‘ri aniqlash | ≥ 9 / 10 | Golden to‘plamdagi 10 ta javobsiz savol yo‘q. | Hisoblanmadi |
| 8 | Javob vaqti — p50 / p95 | p50 ≤ 5 s; p95 ≤ 12 s | Haqiqiy retrieval so‘rovlari to‘plami bo‘lmagani uchun p50/p95 o‘lchanmadi. Async polling oqimi tekshirildi. | Qisman tekshirildi |
| 9 | Xatolar ulushi | ≤ 2% | 18 ta API protokol tekshiruvining barchasi o‘tdi. Bu haqiqiy RAG savollari bo‘yicha xatolar ulushi emas. | Qisman tekshirildi |
| 10 | Uydirma manbalar / eskirgan norma | 0 ta | Haqiqiy Lex.uz citation va amal qilish holati bo‘yicha audit o‘tkazilmadi. | Tekshirilmagan |

## API protokoli sinovlari

18 ta tekshiruv sintetik manba bilan bajarildi. Natija: **18/18 PASS**.

| Tekshiruv guruhi | Natija |
|---|---|
| `/` savol-javob sahifasi, health va meta | O‘tdi |
| Bearer token: yo‘q `401`, noto‘g‘ri `403` | O‘tdi |
| 10 savolli batch, natija soni va ID’larning yagonaligi | O‘tdi |
| Manba gapidan javob ajratish | O‘tdi, sintetik hujjat matni bilan |
| Citation chunk ID’ning context ichida bo‘lishi | O‘tdi, sintetik manba bilan |
| UTF-8, jumladan `Oʻ` va `gʻ` | O‘tdi |
| Ayni `batch_id` bilan darhol takroriy so‘rov | Saqlangan javob qaytdi |
| Ayni `batch_id`, o‘zgargan payload | `409` qaytdi |
| 11 item, takroriy ID, bo‘sh savol | Har biri `400` qaytardi |
| Rate limit | `429` va `Retry-After` qaytdi |
| `/v1/rag/query` va saqlangan batch uchun GET | O‘tdi |
| Async batch | `202 processing`, polling, so‘ng `completed` — o‘tdi |

## Haqiqiy Lex.uz retrieval holati

| Tekshiruv | Natija |
|---|---|
| Mahalliy JSONL korpusi | Topilmadi (`LEX_CORPUS_PATH` standart fayli yo‘q) |
| Savol bo‘yicha live Lex.uz qidiruvini chaqirish | Bajarildi, lekin `ConnectError` bilan to‘xtadi |
| Lex.uz hujjatidan haqiqiy modda/chunk olish | Tarmoq sabab tasdiqlanmadi |
| LLM modeli | `LLM_MODEL` sozlanmagan; mos til topilganda tizim manbadagi gapni ajratib beradi |
| 100 savolli golden to‘plam | Loyihada yo‘q |

Shuning uchun **18/18 PASS faqat API protokoli va sintetik manbaga tegishli**. Bu natija Lex.uz’dan haqiqiy 18 ta hujjat topilganini yoki RAG sifat mezonlari bajarilganini anglatmaydi.

## To‘liq baholash uchun kerak

1. API ishlaydigan kompyuterdan Lex.uz’ga tashqi HTTPS ulanishini ta’minlash yoki JSONL hujjat korpusini berish.
2. Hujjat versiyasi, snapshot sanasi, maqola va amal qilish holati to‘g‘ri saqlanganini tekshirish.
3. Kutilgan javob, `expected_doc_id`, `expected_article` va `answerable` maydonlari bilan 100 savolli golden to‘plamni qo‘shish.
4. Shu 100 savol bo‘yicha haqiqiy API JSON natijalarini olish.
5. Hit@5, MRR, correctness, faithfulness, citation accuracy, no-answer accuracy, p50/p95 va xatolar ulushini hisoblash.

**Yakun:** API interfeysi qayta sinovdan o‘tdi. Haqiqiy Lex.uz manbalaridagi retrieval va javob sifati tarmoq hamda golden to‘plam yetishmagani sababli hali baholanmagan.

## Savol berib tekshirish

Serverni ishga tushirgandan keyin brauzerda `http://127.0.0.1:8000/` manzilini oching. Savol va `.env.local` faylidagi `RAG_API_KEY` qiymatini kiriting. Natijada javob, Lex.uz hujjat nomi, modda, iqtibos hamda manba havolasi chiqadi. API hujjatlari `http://127.0.0.1:8000/docs` manzilida qoladi.
