# Lex.uz RAG API — taqdimot rejasi

**Davomiyligi:** 4–6 daqiqa  
**Taqdimot maqsadi:** tizim vazifasi, savoldan manbali javobgacha bo‘lgan oqim, tekshiruv natijalari va qolgan ishlarni tushuntirish.

## 1-slayd. Loyiha maqsadi

**Slaydda:** `Lex.uz RAG API — qonunchilik savollariga manbali javob`

**Gapirish uchun:**

> Assalomu alaykum. Men Lex.uz hujjatlari bo‘yicha savollarga javob berishga mo‘ljallangan API tizimini taqdim qilaman. Tizim javob bilan birga hujjat havolasi, modda va javobga asos bo‘lgan matn parchasini ham qaytaradi. Maqsad — javobning o‘zini ham, qaysi qonuniy manbadan olinganini ham tekshirish imkonini berish.

## 2-slayd. Ishlash oqimi

**Slaydda:**

`Savol → validatsiya → mahalliy indeks / Lex.uz qidiruvi → hujjat sahifasi → modda va kontekst → javob + citation`

**Gapirish uchun:**

> Foydalanuvchi savolni batch endpointga yuboradi. Tizim avval mahalliy JSONL indeksni qidiradi. Indeks bo‘lmasa, savol tiliga mos Lex.uz qidiruv sahifasidan hujjat izlaydi, topilgan hujjat sahifalarini yuklaydi va matnini moddalar bo‘yicha ajratadi. Keyin savolga mos parcha javob va manba sifatida qaytariladi. Bu jonli qidiruv ishlashi uchun server ishlayotgan kompyuterda Lex.uz’ga internet ulanishi bo‘lishi kerak.

## 3-slayd. Javob qanday hosil bo‘ladi?

**Slaydda:**

- Mahalliy indeks bo‘lsa: BM25 qidiruv va metadata bo‘yicha saralash.
- Indeks bo‘lmasa: Lex.uz ochiq qidiruvidan hujjatlarni topishga urinish.
- LLM modeli sozlanmagan bo‘lsa: topilgan matndan savolga mos gaplar ajratiladi.
- Javob bilan birga citation va contexts qaytariladi.

**Gapirish uchun:**

> Hozirgi sozlamada LLM modeli ko‘rsatilmagan. Shuning uchun tizim yangi yuridik fikr yaratmaydi, manbadagi mos gaplarni ajratib ko‘rsatadi. LLM keyin sozlansa, unga faqat topilgan huquqiy kontekst berilib, har bir da’voni manbaga bog‘lash talab qilinadi. Agar qidiruv yoki internet ishlamasa, tizim xatoni yashirmasdan `RETRIEVAL_FAILED` qaytaradi.

## 4-slayd. API va barqaror ishlash

**Slaydda:**

| Endpoint | Vazifasi |
|---|---|
| `POST /v1/rag/batch` | 1–10 savolni qabul qilish |
| `GET /v1/rag/batch/{batch_id}` | Saqlangan natija yoki jarayon holatini olish |
| `POST /v1/rag/query` | Bitta savolni tekshirish |
| `GET /v1/meta` | Tizim versiyalari |
| `GET /v1/health` | Servis holati |

**Gapirish uchun:**

> API Bearer token bilan himoyalangan. Natijalar SQLite’da saqlanadi va bir xil `batch_id` bilan ayni so‘rov qayta yuborilsa, saqlangan javob qaytadi. Yangi batchlar uchun rate limit bor. Uzoq batch `202 processing` holatini qaytarishi va GET endpointi orqali tekshirilishi mumkin.

## 5-slayd. Tekshiruv natijalari

**Slaydda:**

| Tekshiruv | Natija |
|---|---|
| API protokoli va validatsiya | 18/18 tekshiruv o‘tdi |
| Idempotency, auth va rate limit | O‘tdi |
| Async polling | `202 → processing → completed`, o‘tdi |
| UTF-8 va citation/context bog‘lanishi | Sintetik manbada o‘tdi |
| Lex.uz’dan haqiqiy hujjat olish | `ConnectError`; bu muhitda tashqi ulanish yo‘q |
| 100 savol bo‘yicha RAG metrikalari | Golden to‘plam yo‘qligi sabab hisoblanmadi |

**Gapirish uchun:**

> API protokoli sintetik manba bilan 18 ta tekshiruvdan o‘tdi. Bu autentifikatsiya, batch hajmi, xatoli so‘rovlar, idempotency, rate limit, UTF-8, citation/context mosligi va async pollingni qamrab oldi. Lekin Lex.uz’ga haqiqiy so‘rov bu muhitda tarmoq ulanishi xatosi bilan to‘xtadi. Shuning uchun 100 ta savol bo‘yicha qidiruv yoki javob aniqligi o‘lchangan deb ayta olmaymiz.

## 6-slayd. Keyingi bosqichlar

**Slaydda:**

1. API ishlaydigan serverdan Lex.uz’ga internet ulanishini tekshirish.
2. Lex.uz sahifalaridan hujjat va metadata ajratilishini real sahifalarda tasdiqlash.
3. Indeks versiyasi va snapshot sanasi bilan mahalliy korpus tayyorlash.
4. Ixtiyoriy LLM modelini sozlash.
5. 100 savolli golden to‘plam bilan Hit@5, MRR, correctness, faithfulness, citation accuracy va latency’ni hisoblash.

**Gapirish uchun:**

> Keyingi bosqichda avval real Lex.uz ulanishi va sahifadan matn ajratilishi tekshiriladi. So‘ng test korpusi hamda kutilgan javob va manbalari bo‘lgan 100 savolli to‘plam bilan metrikalar hisoblanadi. Shundan keyingina retrieval va generatsiya sifati spetsifikatsiyadagi mezonlar bilan baholanadi.

## 7-slayd. Demo va yakun

**Demo:**

1. Serverni ishga tushirib, `/` savol-javob sahifasini ochish.
2. Savol va API kalitni kiritish.
3. Javob bilan birga hujjat nomi, modda, iqtibos va Lex.uz havolasini ko‘rsatish.
4. Kerak bo‘lsa, `/docs` orqali API JSON formatini ko‘rsatish.

**Gapirish uchun:**

> Xulosa qilib aytganda, tizim savolni qabul qilish, qidiruvga yuborish, natijani saqlash va manba bilan qaytarish uchun tayyorlangan. API oqimi tekshirildi; haqiqiy qonunchilik savollaridagi aniqlikni tasdiqlash uchun tashqi Lex.uz ulanishi va golden test to‘plami kerak. E’tiboringiz uchun rahmat.

## Savol-javob uchun muhim eslatma

> 18/18 — sintetik ma’lumot bilan o‘tgan API protokoli tekshiruvlari. Bu Lex.uz’dan olingan haqiqiy 18 ta javob yoki 100 savolli RAG bahosi degani emas.
