"""KRT Terminal — command line.
  python main.py                                      (live, Angel One)
  python main.py --source csv --at "2026-10-01 12:15" (demo)
Website-க்கு: KRT.bat double-click."""
import argparse
from krt.runner import run_scan


def fmt(r):
    t = "/".join(str(x) for x in r["targets"]) or "-"
    return (f"  {r['symbol']:<11}{r['level_name']:<12}{r['level']:>10}  px {r['price']:>9}  "
            f"RVOL {r['rvol'] or '-':>5}  score {r['score']:>3}  SL {r['sl']:>9}  T {t:<26} {r['status']}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--at", default=None)
    ap.add_argument("--source", choices=["csv", "angel"], default=None)
    ap.add_argument("--no-chartink", action="store_true")
    a = ap.parse_args()
    res = run_scan(a.source, a.at, not a.no_chartink)
    print(f"\n KRT TERMINAL  |  {res['time']}  |  MARKET: {res['market']}  |  {res['source'].upper()}")
    for m in res["msgs"]:
        print(" " + m)
    print(" " + "━" * 100)
    for side, label in (("ce", "🟢 TOP CE CANDIDATES"), ("pe", "🔴 TOP PE CANDIDATES")):
        print(f"\n {label}")
        print("\n".join(fmt(r) for r in res[side]) or "  NO CONFIRMED SETUP")
    for b in res["blocked"]:
        print(f"  ⚠ {b['symbol']}: {b['status']}")
    print(f"\n New signals logged: {res['new_signals']}")
    if not res["signals"]:
        print(" WAIT — நல்ல setup இல்லை.")
    print("\n ⚠ Rule-based scanner. Profit / accuracy guarantee இல்லை. Not investment advice.\n")


if __name__ == "__main__":
    main()
