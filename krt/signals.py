"""Signal lifecycle + timestamped paper-trading log (JSONL). Original levels மாற்றப்படாது."""
from __future__ import annotations
import hashlib, json
from dataclasses import dataclass, field, asdict
from pathlib import Path
import pandas as pd

STATUSES = ["BUILDING", "WATCH", "CONFIRMED", "TRIGGERED", "EXTENDED",
            "T1 HIT", "T2 HIT", "T3 HIT", "SL HIT", "INVALIDATED", "EXPIRED"]


@dataclass(frozen=True)
class Signal:
    symbol: str
    direction: str
    setup: str
    level_name: str
    entry_zone: tuple
    sl: float
    targets: tuple
    confirm_candle: str
    generated_at: str
    price_at_signal: float
    score: int
    reasons: tuple = field(default_factory=tuple)

    @property
    def id(self) -> str:
        # same stock + setup + level + day → same ID (duplicate alert தடுக்க)
        key = f"{self.symbol}|{self.direction}|{self.setup}|{self.level_name}|{self.confirm_candle[:10]}"
        return hashlib.sha1(key.encode()).hexdigest()[:12]


class SignalLog:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.seen = set()
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                rec = json.loads(line)
                if rec.get("event") == "NEW":
                    self.seen.add(rec["id"])

    def add(self, s: Signal) -> bool:
        if s.id in self.seen:
            return False
        self._write({"event": "NEW", "id": s.id, **asdict(s)})
        self.seen.add(s.id)
        return True

    def update_status(self, sig_id: str, status: str, at: pd.Timestamp, note: str = ""):
        assert status in STATUSES
        self._write({"event": "STATUS", "id": sig_id, "status": status, "at": str(at), "note": note})

    def _write(self, rec: dict):
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, default=str, ensure_ascii=False) + "\n")
