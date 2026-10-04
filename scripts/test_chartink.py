"""Chartink scans வேலை செய்கிறதா என்று test."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from krt.config import load_settings
from krt.chartink import build_watchlist

watch, msgs = build_watchlist(load_settings())
print()
for m in msgs:
    print(" " + m)
print(f"\n Total: {len(watch)} stocks\n")
