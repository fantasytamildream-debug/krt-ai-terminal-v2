# 🖥️ KRT — Smart Stock Options Terminal

Rule-based F&O opportunity scanner — 🟢 CE / 🔴 PE setups, levels, volume, risk check, timestamped signal log.

> ⚠️ இது rule-based scanner மட்டும். Guaranteed profit / accuracy claim இல்லை. Investment advice இல்லை.

## Development roadmap
| Phase | Module | Status |
|---|---|---|
| 1 | Stock scanner (PDH/PDL/PWH/PWL/PMH/PML, RVOL, market condition, scoring) | ✅ Starter ready |
| 1b | Chart patterns (H&S, Double top/bottom, triangles, flags, wedges) | ⏳ |
| 2 | Timestamped paper-trading log | ✅ Basic (`logs/signals.jsonl`) |
| 3 | Live option chain + strike selection | ⏳ |
| 4 | Premium entry / SL / T1-T3 engine | ⏳ |
| 5 | Alerts + performance dashboard | ⏳ |

## 👑 Jackpot Mannan (v79)
- `krt/mannan.py` — 3 தனி engines: 📊 Mannan Index · 🛢 Mannan Commodity · 📈 Mannan Stock Options, ஒவ்வொன்றிலும் 10 strategies
- Best setup மட்டும்: ≥2 strategies ஒரே பக்கம் · எதிர் 0 · score 75+ · market திசை · meta-label (triple-barrier backtest) · ஒரு scan-க்கு 1 call
- Website tab "👑 Jackpot Mannan": best setup, 10-strategy table (backtest + live + Test needed), open calls, முடிந்த calls (saved)
- Tests: `tests/test_mannan.py`

## V9 (v78) மாற்றங்கள்
- 🧭 ஒரே market திசை (`ai.market_dir`) — prediction / big move / banner இனி எதிரெதிரா சொல்லாது
- 🟠 Strong Break V9 — 9:25–2:30 மட்டும், fresh break முதலில், VWAP + market திசை filter, retest entry
- 🤖 AI Picks — 3 வழியில் call (AI ≥66% · 🩷 proven module + score 70 · learning score 85), காரணம் காட்டும்
- ⭐ Calls tab BEST SETUPS + 🩷 Pink filter · 📈 Chart Room live P/L, call marker, results table
- 👑 Goki — Angel API priority (deep scan காத்திருக்கும்), ready நேரம் காட்டும்
- 🩷 Pink alert — win ≥75% light / ≥80% dark (≥20 calls), charges சேர்த்து லாபம் கட்டாயம்
- Tests: `pytest -q tests`

## Quick start
```bash
git clone https://github.com/<your-username>/krt-terminal.git
cd krt-terminal
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python scripts/make_sample_data.py                  # demo data (random, real இல்லை)
python main.py --source csv --at "2026-10-01 12:15"
pytest -q
```

## Structure
```
config/settings.yaml      thresholds, universe, risk limits, score weights
krt/data/provider.py      broker adapter interface (Kite / Upstox / Angel / Dhan)
krt/data/csv_provider.py  offline CSV data
krt/levels.py             completed PDH/PWH/PMH levels, confluence, swing targets
krt/volume.py             same-time RVOL, HIGH PARTICIPATION tag
krt/market.py             market classification, relative strength
krt/setups/level_break.py previous-level break (gap-aware, completed candles only)
krt/scoring.py            100-point ranking (score ≠ win probability)
krt/risk.py               1-lot planned risk, ₹2,500 cap → SKIP
krt/signals.py            signal ID, dedupe, lifecycle status log
main.py                   CLI terminal
```

## Built-in rules
- Completed candles மட்டும் — future-data leakage இல்லை (tests உள்ளன)
- Gap-open → fresh breakout இல்லை, `WATCH` (retest / ORB confirmation தேவை)
- RVOL < 1.5× → CONFIRMED ஆகாது
- 3 practical targets இல்லையெனில் → `INSUFFICIENT TARGETS`
- Stale data → `BLOCKED`
- Same setup → duplicate alert இல்லை
- Failed CE ≠ auto PE

Full spec: [`docs/PROJECT_SPEC.md`](docs/PROJECT_SPEC.md)

## 🌐 Website mode
- **PC-ல்:** `KRT.bat` double-click → browser-ல் dashboard திறக்கும் (http://127.0.0.1:8765)
- **Render-ல்:** Build `pip install -r requirements.txt`, Start `python server.py`,
  Environment: `ANGEL_API_KEY, ANGEL_CLIENT_ID, ANGEL_MPIN, ANGEL_TOTP_SECRET, BROKER=angel, APP_PASSWORD, PYTHON_VERSION=3.12.7`
  (optional `CHARTINK_CE_CLAUSE`, `CHARTINK_PE_CLAUSE`)
- `.env` file-ஐ GitHub-ல் ஒருபோதும் upload செய்ய வேண்டாம்.
