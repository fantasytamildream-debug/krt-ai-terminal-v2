"""Chartink scan clause-ஐ clipboard-ல் இருந்து save செய்யும்.
Usage: python scripts/set_clause.py ce   (அல்லது pe)"""
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
f = ROOT / "config" / "chartink_clauses.json"
side = (sys.argv[1] if len(sys.argv) > 1 else "").lower()
if side not in ("ce", "pe"):
    print("\n Usage: python scripts/set_clause.py ce   (illa)   python scripts/set_clause.py pe\n")
    sys.exit(1)

clause = ""
try:
    import tkinter
    t = tkinter.Tk(); t.withdraw()
    clause = t.clipboard_get().strip()
    t.destroy()
except Exception:
    pass
if not clause.startswith("("):
    print(" Clipboard-la clause illa. Ippo paste pannunga (right click) apram Enter:")
    clause = input(" > ").strip()

if not (clause.startswith("(") and "{" in clause):
    print("\n ✗ Idhu scan clause maadhiri illa. '( {' nu aarambikkanum. Thirumba copy pannunga.\n")
    sys.exit(1)

data = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
data[side] = clause
f.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"\n ✅ {side.upper()} clause saved ({len(clause)} characters)")
print(f"    {clause[:90]}{'...' if len(clause) > 90 else ''}")
print("\n Adutha step: python scripts/test_chartink.py\n")
