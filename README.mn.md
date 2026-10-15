# Forex бот (XM MT5) — P2

P0: XM демо дансанд холбогдож шалгана. P1: түүхэн өгөгдөл татаж, стратегийг backtest хийнэ.
**Аль ч хувилбар захиалга илгээхгүй.**

## 1. Нэг удаагийн бэлтгэл

1. **Python 3.11 эсвэл 3.12** суулгана: https://www.python.org/downloads/
   Суулгахдаа **"Add Python to PATH"**-ийг заавал чагтална.
2. **XM MT5 терминал**-аа нээгээд демо дансаараа нэвтэрсэн байна.
3. Энэ хавтсыг (`forex-bot`) жишээ нь `Documents\forex-bot` руу задлаад
   **VS Code**-оор нээнэ (File → Open Folder).

## 2. Орчин тохируулах (VS Code-ийн Terminal дээр)

VS Code-д `Terminal → New Terminal` нээгээд дараахыг нэг нэгээр бичнэ:

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

> `activate` хийхэд алдаа гарвал (PowerShell-ийн хориг):
> `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` гэж бичээд дахин оролдоно.

## 3. Нууц мэдээлэл оруулах

`.env.example` файлыг хуулж `.env` гэж нэрлээд XM-ээс ирсэн мэдээллээ бөглөнө:

```
MT5_LOGIN=таны_дансны_дугаар
MT5_PASSWORD=таны_нууц_үг
MT5_SERVER=серверийн_нэр
```

Серверийн нэрийг MT5 терминалд `File → Login to Trade Account` цонхноос
эсвэл XM-ийн и-мэйлээс яг таг хуулна (жишээ нь `XMGlobal-MT5 2`).

## 4. Ажиллуулах

```powershell
python -m pytest -q                    # тооцооллын тест (11 тест OK байх ёстой)
python scripts/check_connection.py     # XM-тэй холбогдох шалгалт
```

## 5. Үр дүнг надад илгээх

`check_connection.py`-ийн гаралтыг бүхлээр нь хуулж илгээнэ үү (нууц үг
гаралтад харагдахгүй). Түүнээс:

- symbol-ын бодит нэр (дагавартай эсэх),
- filling mode, серверийн цаг, swap, stop out түвшин

зэргийг авч дараагийн шат (P1: өгөгдөл, стратеги, backtest)-ийг тохируулна.

## P1: Түүхэн өгөгдөл ба backtest

P0-оос шинэчлэхдээ хуучин `.env` болон `.venv`-ээ хадгалаад бусад файлыг солино
(доорх "Шинэчлэх" хэсгийг үз). Дараа нь:

```powershell
pip install -r requirements.txt         # matplotlib, tzdata нэмэгдсэн
python -m pytest -q                     # 24 passed байх ёстой
python scripts/download_history.py      # MT5-аас H1, H4 түүх татна (data/ хавтаст)
python scripts/run_backtest.py          # 2-5 минут ажиллана
```

Үр дүн `reports/<огноо_цаг>/` хавтаст гарна:

- `report.txt` — EMA ба Fibonacci хувилбарын харьцуулалт, in-sample ба out-of-sample
- `equity_*.png` — балансын график
- `trades_*.csv` — арилжаа бүрийн дэлгэрэнгүй (Excel-ээр нээж болно)

**`report.txt`-ийн агуулгыг бүхлээр нь надад илгээнэ үү.**

> MT5 хэдэн жилийн түүх өгөхийг терминалын `Tools → Options → Charts → Max bars in chart`
> тохиргоо хязгаарладаг. "Unlimited" болгоод MT5-ийг дахин ачааллавал илүү урт түүх татагдана.

## P1.1: Оношлогоо (зөвхөн 2018–2023)

```powershell
python -m pytest -q              # 28 passed
python scripts/diagnose.py       # 5–15 минут
```

`reports/diag_<огноо_цаг>/diagnose.txt` файлын агуулгыг бүхлээр нь илгээнэ үү.
Энэ скрипт out-of-sample (2024–2026) өгөгдлийг огт ашиглахгүй.

## P1.2: Зардлын шинжилгээ ба D1 олон зах зээлийн судалгаа

```powershell
python -m pytest -q                       # 30 passed
python scripts/cost_analysis.py           # 1–2 минут, H1 өгөгдөл ашиглана
python scripts/download_universe.py       # 18 хүртэл хэрэгслийн D1 түүх
python scripts/research_d1.py             # in-sample + validation
```

- `cost_analysis.py` — дэлгэцэнд гарсан хүснэгтийг бүхлээр нь илгээнэ.
- `download_universe.py` — `[OK]` / `[--]` мөрүүдийг илгээнэ.
- `research_d1.py` — `reports/d1_<огноо_цаг>/report.txt`-ийг илгээнэ.

**`research_d1.py --final`-ийг бүү ажиллуул.** Энэ нь 2024–2026 оны өгөгдлийг ашиглах тул
хувилбараа хамтдаа сонгосны дараа ганцхан удаа ажиллуулна.

## P2: E1b бодит цагийн бот (ДЕМО)

Стратеги: индексийн RSI(2) < 5 mean reversion (D1, long only). Тохиргоо: `config.yaml` → `live`.

```powershell
python scripts/run_live.py      # MT5 асаалттай, демо дансаар нэвтэрсэн байх ёстой
```

- **Эхлээд `dry_run: true`** — захиалга илгээхгүй, юу хийхээ лог болон Telegram-д бичнэ.
- Бот өдөрт нэг удаа (шинэ D1 лаа хаагдахад) шийдвэр гаргана. Дохио сард 1–3 удаа гарна.
- Компьютер, MT5 хоёулаа асаалттай байх ёстой. Унтах горимыг унтраа.
- Зогсоох: `Ctrl+C`. Дахин асаахад төлөв (`data/live_state.sqlite`) хадгалагдсан тул үргэлжилнэ.
- Лог: `logs/live.log`

### Зөөврийн компьютер: өдөрт нэг удаа автоматаар

Стратеги өдөрт нэг удаа шийдвэр гаргадаг тул 24 цаг асаалттай байх шаардлагагүй.

1. PowerShell-ийг нээгээд: `powershell -ExecutionPolicy Bypass -File C:\Projects\forex-bot\setup_task.ps1`
2. Компьютерийг унтраахын оронд **Sleep** (таг хаах) горимд оруул, цэнэглэгчид залгаатай байлга.
3. Power Options → Advanced → Sleep → **Allow wake timers: Enable**.

Мягмар–Бямба 06:30-д компьютер сэрж, `run_once.bat` ботыг 30 минут хүртэл ажиллуулаад унтраана.
Компьютер тэр үед бүрэн унтраалттай байсан бол дараагийн асах үед шууд ажиллана. Лог: `logs/once.log`.

### Telegram

1. Telegram-д **@BotFather** → `/newbot` → нэр, username (`...bot`-оор төгссөн) → token авна.
2. `.env`-д `TELEGRAM_BOT_TOKEN=<token>` гэж бичиж хадгална (token-оо хэнд ч бүү өг).
3. Өөрийн ботыг Telegram-д нээж **Start** дарна.
4. `python scripts/telegram_setup.py` — chat ID-г олж `.env`-д бичээд туршилтын мессеж илгээнэ.
5. `python scripts/telegram_listener.py` — компьютер асаалттай үед утаснаас команд илгээх боломжтой.

Командууд: `/check EURUSD BUY`, `/status`, `/checks`, `/pause`, `/resume`, `/stop`, `/help`

### Шинэчлэх

1. Шинэ zip-ийг түр хавтаст задална.
2. `C:\Projects\forex-bot` доторх `bot`, `scripts`, `tests`, `config`, `requirements.txt`, `README.md`-ийг
   шинээр солино. **`.env` болон `.venv`-д бүү хүр.**

## Бүтэц

```
forex-bot/
├─ bot/
│  ├─ config.py                    тохиргоо + .env унших
│  ├─ broker/mt5_broker.py         MT5 adapter (зөвхөн унших)
│  ├─ data/store.py                өгөгдөл хадгалах, серверийн цаг → UTC
│  ├─ indicators.py                EMA, RSI, ATR, ADX, swing, Fibonacci
│  ├─ strategy/trend_pullback.py   trend + pullback стратеги, шүүлтүүрүүд
│  ├─ backtest/engine.py           SimBroker: spread, slippage, swap, лимитүүд
│  ├─ backtest/metrics.py          win rate, PF, drawdown, Sharpe, Monte Carlo
│  └─ risk/sizing.py               lot / SL / TP тооцоолол
├─ config/config.yaml      эрсдэл, хос, шүүлтүүрийн тохиргоо
├─ scripts/check_connection.py, download_history.py, run_backtest.py
├─ tests/                   24 тест (тооцоолол, индикатор, look-ahead, backtest)
├─ .env.example
└─ requirements.txt
```

## Аюулгүй байдал

- `.env` файлыг хэнд ч бүү өг, Git-д бүү оруул (`.gitignore`-д орсон).
- `config.yaml`-д `allow_live: false` байгаа тул бодит дансанд холбогдвол бот зогсоно.

## Мэдээний календарийн шүүлтүүр

Өндөр нөлөөтэй мэдээний (NFP, CPI, хүүгийн шийдвэр) 30 минутын өмнөөс 30 минутын дараа хүртэл
тухайн валюттай хэрэгслээр шинэ арилжаа нээхгүй (US500, US30 → USD, GER40 → EUR, JP225 → JPY).
Дохиог цуцлахгүй, мэдээ өнгөрсний дараа гүйцэтгэнэ. Нээлттэй позицыг хаахыг хэзээ ч хориглохгүй.

- Эх үүсвэр: ForexFactory-ийн үнэгүй JSON (энэ долоо хоног). Кэш: `data/news_calendar.json`, 6 цаг.
- Шалгах: `python scripts/news_check.py` (MT5 шаардахгүй), Telegram: `/news`
- Тохиргоо: `config/config.yaml` → `news:` хэсэг.

## Telegram listener-ийг автоматаар асаах

`/check`, `/news`, `/status` командууд listener ажиллаж байх үед л хариулна. Windows-д нэвтрэх бүрт
далд (цонхгүй) асаах:

```
powershell -ExecutionPolicy Bypass -File C:\Projects\forex-bot\setup_listener_task.ps1
```

- Лог: `logs/telegram.log`. MT5 холбогдохгүй бол 60 сек тутам дахин оролдоно.
- Зогсоох: `Stop-ScheduledTask -TaskName "ForexBot Telegram"`
- Устгах: `Unregister-ScheduledTask -TaskName "ForexBot Telegram" -Confirm:$false`

