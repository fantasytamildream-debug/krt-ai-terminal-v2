"""Angel One login + NIFTY live price test."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")
from krt.data.angel_provider import angel_login

try:
    api, s = angel_login()
except Exception as e:
    print(f"\n ❌ {e}\n")
    sys.exit(1)
name = (s.get("data") or {}).get("name") or ""
print(f"\n ✅ Angel One login OK  {name}")
try:
    ltp = api.ltpData("NSE", "Nifty 50", "99926000")
    print(f" NIFTY LTP: {ltp['data']['ltp']}")
except Exception as e:
    print(f" ⚠ LTP check failed: {e}")
print()
