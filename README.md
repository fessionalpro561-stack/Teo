# FER3OON Telegram Channel Sync
## أداة مزامنة قنوات التيليجرام

نظام احترافي ومتكامل لمزامنة محتوى قنوات التيليجرام تلقائياً —  
يستورد الأرشيف القديم أولاً، ثم يتابع المنشورات الجديدة لحظةً بلحظة.

---

## هيكل المشروع

```
fer3oon_sync/
├── config/
│   ├── __init__.py
│   └── settings.py          ← كل الإعدادات هنا
├── database/
│   ├── __init__.py
│   └── db.py                ← SQLite layer
├── logs/                    ← تُنشأ تلقائياً عند التشغيل
├── modules/
│   ├── __init__.py
│   ├── logger.py            ← نظام السجلات
│   ├── content_modifier.py  ← قواعد تعديل المحتوى
│   ├── telegram_client.py   ← Telethon wrapper
│   ├── publisher.py         ← نشر الرسائل والميديا
│   ├── archive_importer.py  ← المرحلة الأولى: الأرشيف
│   └── live_watcher.py      ← المرحلة الثانية: المراقبة الحية
├── main.py                  ← نقطة الدخول
├── requirements.txt
├── .env.example
└── README.md
```

---

## التثبيت والتشغيل خطوة بخطوة

### الخطوة 1 — المتطلبات

- Python 3.11+
- حساب تيليجرام نشط

### الخطوة 2 — تثبيت المكتبات

```bash
pip install -r requirements.txt
```

### الخطوة 3 — إنشاء API credentials

1. افتح [https://my.telegram.org/apps](https://my.telegram.org/apps)
2. سجّل دخولك برقم هاتفك
3. أنشئ تطبيقاً جديداً
4. احفظ قيمة `App api_id` و `App api_hash`

### الخطوة 4 — إعداد ملف البيئة

```bash
cp .env.example .env
```

ثم افتح `.env` وعدّل:

```env
API_ID=12345678
API_HASH=abcdef1234567890abcdef1234567890
SESSION_NAME=fer3oon_sync_session
SOURCE_CHANNELS=ForexBreakingNews
DESTINATION_CHANNEL=FOREX_NEWS_EGY
```

### الخطوة 5 — التشغيل

```bash
python main.py
```

في أول مرة ستُطلب منك بيانات تسجيل الدخول لحسابك على تيليجرام  
(رقم الهاتف ثم كود التحقق).  
بعدها تُحفظ الجلسة محلياً ولا تُطلب مجدداً.

---

## أوضاع التشغيل

| الأمر | الوصف |
|-------|-------|
| `python main.py` | المرحلتان معاً (الأرشيف ثم الحي) |
| `python main.py --archive-only` | استيراد الأرشيف فقط ثم الإيقاف |
| `python main.py --live-only` | تخطي الأرشيف والبدء مباشرةً بالمراقبة الحية |

---

## قواعد تعديل المحتوى

### التوقيع / الفوتر

الأداة تكتشف تلقائياً أي توقيع يشير لقناة المصدر وتستبدله بتوقيع القناة المستهدفة:

```
⬤ قناة أَخبار الفوركس العاجلة 🌎
https://t.me/FOREX_NEWS_EGY ✅
```

إذا لم يكن هناك توقيع في المنشور الأصلي، يُضاف التوقيع تلقائياً.

### الهاشتاجات

في ملف `.env`:

```env
# حذف هاشتاجات (بدون #)
REMOVE_HASHTAGS=forex,news,breaking

# إضافة هاشتاجات (بدون #)
ADD_HASHTAGS=FOREX_EGY,أخبار_الفوركس
```

لاستبدال هاشتاجات، عدّل `REPLACE_HASHTAGS` مباشرةً في `config/settings.py`.

---

## منع التكرار

- يُحسب Hash لمحتوى كل رسالة
- يُحفظ في قاعدة البيانات
- أي رسالة تكررت تُتجاهل تلقائياً
- لإيقاف هذه الميزة: `DUPLICATE_CHECK=false`

---

## قاعدة البيانات

تُنشأ تلقائياً في `database/sync.db`.

جداول SQLite:
- **channels** — القنوات المتابَعة وحالة الأرشيف
- **processed_messages** — كل رسالة تمت معالجتها
- **content_hashes** — بصمات المحتوى للكشف عن التكرار
- **sync_logs** — سجل العمليات

---

## السجلات (Logs)

تظهر في:
- الطرفية (مُلوَّنة)
- ملف `logs/sync.log` (يدور تلقائياً عند 10 ميجابايت)

مستويات: `DEBUG` | `INFO` | `WARNING` | `ERROR` | `CRITICAL`

---

## إدارة الأخطاء

| الخطأ | التعامل |
|-------|---------|
| FloodWait | انتظار المدة المطلوبة من تيليجرام × 1.2 |
| انقطاع الإنترنت | إعادة محاولة تلقائية بـ exponential backoff |
| RPC errors | إعادة محاولة حتى MAX_RETRIES مرات |
| خطأ تنزيل ميديا | نشر النص فقط كبديل |

---

## تغيير القنوات

لإضافة أكثر من قناة مصدر، عدّل في `.env`:

```env
SOURCE_CHANNELS=ForexBreakingNews,AnotherChannel,ThirdChannel
```

---

---

## Deploy على Railway — خطوة بخطوة

### الخطوة 1 — توليد STRING_SESSION على جهازك

```bash
# تأكد إن .env فيه API_ID و API_HASH أولاً
python generate_session.py
```

سيطلب منك رقم هاتفك وكود التحقق مرة واحدة فقط،
ثم يطبع قيمة `STRING_SESSION` — **احفظها**.

### الخطوة 2 — رفع المشروع على GitHub

```bash
git init
git add .
git commit -m "initial commit"
git remote add origin https://github.com/YOUR_USERNAME/fer3oon-sync.git
git push -u origin main
```

> تأكد إن `.gitignore` موجود حتى لا ترفع ملف `.env` أو `.session`

### الخطوة 3 — إنشاء مشروع على Railway

1. افتح [railway.app](https://railway.app) وسجّل دخولك
2. **New Project** ← **Deploy from GitHub repo**
3. اختر الـ repo

### الخطوة 4 — إضافة المتغيرات

في Railway: **Variables** ← أضف هذه القيم:

| Variable | القيمة |
|----------|--------|
| `API_ID` | رقم من my.telegram.org |
| `API_HASH` | الهاش من my.telegram.org |
| `STRING_SESSION` | القيمة من generate_session.py |
| `SOURCE_CHANNELS` | `ForexBreakingNews` |
| `DESTINATION_CHANNEL` | `FOREX_NEWS_EGY` |
| `POST_DELAY` | `1.5` |
| `DUPLICATE_CHECK` | `true` |
| `LOG_LEVEL` | `INFO` |

### الخطوة 5 — تفعيل الـ Worker

Railway قد يحاول تشغيله كـ web server.
تأكد من:
- **Settings** ← **Start Command**: `python main.py`
- أو الـ `Procfile` موجود: `worker: python main.py`

### الخطوة 6 — متابعة الـ Logs

في Railway: **Deployments** ← اضغط على أحدث deployment ← **View Logs**

```
FER3OON Telegram Channel Sync
Sources       : ForexBreakingNews
Destination   : FOREX_NEWS_EGY
▶ Phase 1: Archive import starting…
[ForexBreakingNews] ✓ msg 1234 → dest 5678
…
▶ Phase 2: Live monitoring starting…
Live watcher active on 1 channel(s). Waiting for new posts…
```

---

### ملاحظات Railway

- **الجلسة محفوظة** في `STRING_SESSION` — لا تُفقد عند كل redeploy
- **إعادة التشغيل تلقائية** عند أي crash
- **الـ Free plan** يكفي للتشغيل المستمر (500 ساعة/شهر مجاناً)
- قاعدة البيانات `sync.db` تُعاد عند كل redeploy — لتجنب ذلك استخدم Railway PostgreSQL أو Volume

---

## ملاحظة قانونية

تأكد من حصولك على إذن صريح من مالكي القنوات المصدر  
قبل مزامنة محتواها.
