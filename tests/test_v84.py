"""v84: 📲 push notifications · 🧭 regime · 🏦 trap · 📒 journal · 📰 index news."""
import time

import numpy as np
import pandas as pd

from tests.test_mannan import FakeStore


def _fs(monkeypatch):
    from krt import calls as CL, store as SM
    fs = FakeStore()
    for m in (CL, SM):
        monkeypatch.setattr(m, "STORE", fs)
    return fs


def test_vapid_keys_persist_and_push_encrypts(monkeypatch):
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    import base64, os
    from krt import notify as NT
    fs = _fs(monkeypatch)
    V1, pub1 = NT.vapid()
    V2, pub2 = NT.vapid()
    assert pub1 == pub2 and len(base64.urlsafe_b64decode(pub1 + "==")) == 65       # ஒரே key (save ஆகுது), uncompressed P-256
    # உண்மையான browser subscription மாதிரி keys
    k = ec.generate_private_key(ec.SECP256R1())
    p256 = base64.urlsafe_b64encode(k.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)).decode().rstrip("=")
    auth = base64.urlsafe_b64encode(os.urandom(16)).decode().rstrip("=")
    NT.subscribe({"endpoint": "https://fcm.googleapis.com/fcm/send/abc", "keys": {"p256dh": p256, "auth": auth}}, "Android")
    sent = []

    class R:
        status_code = 201
        text = ""
    monkeypatch.setattr("requests.post", lambda url, data=None, headers=None, timeout=None, **k: sent.append((url, data, headers)) or R())
    assert NT.push("🔔 BUY NIFTY 24000 CE", "Entry ₹120", tag="t", urgent=True, wait=True) == 1
    url, body, hd = sent[0]
    assert url.startswith("https://fcm.googleapis.com") and hd.get("Content-Encoding") == "aes128gcm" and len(body) > 100
    assert hd.get("Authorization", "").startswith("vapid ") and hd.get("Urgency") == "high"       # VAPID-signed + encrypted


def test_dead_subscription_removed(monkeypatch):
    from krt import notify as NT
    fs = _fs(monkeypatch)
    NT.vapid()
    fs.data["push_subs"] = {"e": {"sub": {"endpoint": "e", "keys": {"p256dh": "x", "auth": "y"}}}}
    from pywebpush import WebPushException

    class Resp:
        status_code = 410
    def boom(*a, **k):
        raise WebPushException("gone", response=Resp())
    monkeypatch.setattr("pywebpush.webpush", boom)
    NT.push("x", "y", wait=True)
    assert fs.data["push_subs"] == {}


def test_notify_tick_new_calls_once_no_old_spam(monkeypatch):
    from krt import notify as NT
    fs = _fs(monkeypatch)
    now = pd.Timestamp("2026-11-05 19:30")
    fs.data["calls"] = {"new": {"id": "new", "date": "2026-11-05", "time": "19:29", "signal_time": "2026-11-05 19:29:10", "status": "OPEN",
                                "symbol": "CRUDEOIL", "strike": 5600, "side": "CE", "entry": 120, "sl": 90, "targets": [150], "kind": "MCX",
                                "pink": {"tier": "dark", "win": 82}},
                        "old": {"id": "old", "date": "2026-11-05", "time": "10:00", "signal_time": "2026-11-05 10:00:00", "status": "OPEN",
                                "symbol": "NIFTY", "strike": 24000, "side": "CE", "entry": 1, "sl": 1, "targets": [2], "kind": "V4"}}
    got = []
    monkeypatch.setattr(NT, "push", lambda t, b, tag=None, url="/", urgent=False, wait=False: got.append((t, urgent)))
    assert NT.notify_tick(now) == 1 and got == [("🩷🩷 DARK PINK · BUY CRUDEOIL 5600 CE", True)]
    NT.notify_tick(now + pd.Timedelta(minutes=1))
    assert len(got) == 1                                                       # ஒருமுறை மட்டும்


def _ohlc(c, spread=1.0):
    c = np.asarray(c, float)
    o = np.r_[c[0], c[:-1]]
    return o, np.maximum(o, c) + spread * 0.3, np.minimum(o, c) - spread * 0.3, c


def test_regime_detector():
    from krt.chartroom import regime_engine
    o, h, l, c = _ohlc(100 + np.arange(80) * 1.0)
    assert regime_engine(h, l, c)["kind"] == "TRENDING UP"
    o, h, l, c = _ohlc(100 + np.sin(np.arange(80) / 1.5) * 0.8, 0.5)
    assert regime_engine(h, l, c)["kind"] == "SIDEWAYS"
    base = 100 + np.sin(np.arange(80) / 1.5) * 0.8
    base[-14:] = 100 + np.array([(-1) ** i * 6 for i in range(14)])
    o, h, l, c = _ohlc(base, 0.5)
    assert regime_engine(h, l, c)["kind"] == "VOLATILE"


def test_trap_confirmed():
    from krt.chartroom import pivots, trap_engine
    n = 60
    c = list(100 + np.sin(np.arange(n) / 3) * 2)
    o, h, l, c = [np.array(x, float) for x in _ohlc(c)]
    v = np.full(n, 1000.0)
    hi, lo = pivots(h, l)
    lvl = max(p[1] for p in hi if p[0] < n - 4)
    j = n - 3                                                        # sweep bar: wick மேல், close உள்ளே, volume 2×
    h[j], c[j], o[j], l[j], v[j] = lvl + 1.5, lvl - 0.4, lvl - 0.2, lvl - 0.9, 2000
    c[j + 1], l[j + 1], h[j + 1], o[j + 1] = l[j] - 0.5, l[j] - 0.8, lvl - 0.3, lvl - 0.5   # sweep bar low-க்கு கீழ் close
    t = trap_engine(o, h, l, c, v, hi, lo, 1.0)
    assert t and t["kind"] == "BULL TRAP" and t["status"] == "CONFIRMED" and t["side"] == "PE" and t["inst"]


def test_trade_journal_metrics():
    from krt import ai
    mk = lambda i, p: {"id": str(i), "date": "2026-11-05", "time": f"10:{i:02d}", "exit_time": f"2026-11-05 11:{i:02d}", "status": "SL HIT" if p < 0 else "T3 DONE",
                       "pnl_lot": p, "kind": "V4", "source": "V4 X", "lot": 65, "entry": 100, "exit": 100}
    calls = [mk(i, p) for i, p in enumerate([3000, -1000, -1000, 2000, -500])]
    orig = ai.charges
    ai.charges = lambda c: 0
    try:
        j = ai.trade_journal(calls)
    finally:
        ai.charges = orig
    a = j["all"]
    assert a["n"] == 5 and a["win"] == 2 and a["win_rate"] == 40.0 and a["net"] == 2500
    assert a["pf"] == round(5000 / 2500, 2) and a["mdd"] == 2000 and a["max_loss_streak"] == 2 and j["curve"][-1] == 2500


def test_index_news_bias_no_call():
    from krt import newsradar as NR
    assert NR.mscore("RBI cuts repo rate by 25 bps, Sensex rallies") >= 5
    items = [{"symbol": "BANKNIFTY", "title": "RBI cuts repo rate", "source": "x", "ts": time.time(), "time": "", "score": 3, "event": "MARKET"},
             {"symbol": "NIFTY", "title": "RBI cuts repo rate", "source": "x", "ts": time.time(), "time": "", "score": 3, "event": "MARKET"}]
    F = NR.build_focus(items, {}, {})
    assert {f["symbol"] for f in F} == {"NIFTY", "BANKNIFTY"} and all(f["status"] == "BIAS" and f["side"] == "CE" for f in F)
