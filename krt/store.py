"""எல்லா calls-ஐயும் நிரந்தரமாக save செய்யும்.
Render free disk restart-ல் அழியும் → GITHUB_TOKEN + GITHUB_DATA_REPO env இருந்தால் GitHub-ல் (calls.json) save.
இல்லையென்றால் logs/calls.json (local)."""
import base64, json, os, threading, time
import requests
from .config import ROOT

LOCAL = ROOT / "logs" / "calls.json"


class Store:
    def __init__(self, path="calls.json", default=None, min_gap=120):
        self.token = os.getenv("GITHUB_TOKEN", "").strip()
        self.repo = os.getenv("GITHUB_DATA_REPO", "").strip()
        self.path, self.default, self.min_gap = path, default, min_gap
        self.local = LOCAL.parent / path
        self.sha, self.data, self.dirty, self.last_save = None, None, False, 0.0
        self.lock = threading.Lock()
        self.error = None

    @property
    def remote(self):
        return bool(self.token and self.repo)

    def _h(self):
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json"}

    def load(self):
        if self.data is not None:
            return self.data
        data = None
        if self.remote:
            try:
                r = requests.get(f"https://api.github.com/repos/{self.repo}/contents/{self.path}", headers=self._h(), timeout=20)
                if r.status_code == 200:
                    j = r.json()
                    self.sha = j["sha"]
                    data = json.loads(base64.b64decode(j["content"]).decode("utf-8"))
                elif r.status_code != 404:
                    self.error = f"GitHub load {r.status_code}"
            except Exception as e:
                self.error = f"GitHub load: {e}"
        if data is None and self.local.exists():
            try:
                data = json.loads(self.local.read_text(encoding="utf-8"))
            except Exception:
                data = None
        if self.default is None:
            self.data = data or {"calls": {}, "published": {}}
            self.data.setdefault("calls", {})
            self.data.setdefault("published", {})
        else:
            self.data = data or dict(self.default)
        return self.data

    def save(self, force=False):
        if not self.dirty and not force:
            return
        if not force and time.time() - self.last_save < self.min_gap:
            return
        body = json.dumps(self.data, default=str, ensure_ascii=False, separators=(",", ":"))
        self.local.parent.mkdir(parents=True, exist_ok=True)
        self.local.write_text(body, encoding="utf-8")
        if self.remote:
            try:
                p = {"message": f"KRT {self.path} update", "content": base64.b64encode(body.encode("utf-8")).decode()}
                if self.sha:
                    p["sha"] = self.sha
                r = requests.put(f"https://api.github.com/repos/{self.repo}/contents/{self.path}", headers=self._h(), json=p, timeout=30)
                if r.status_code in (200, 201):
                    self.sha = r.json()["content"]["sha"]
                    self.error = None
                elif r.status_code == 409:  # sha mismatch → reload sha, அடுத்த முறை
                    g = requests.get(f"https://api.github.com/repos/{self.repo}/contents/{self.path}", headers=self._h(), timeout=20)
                    self.sha = g.json().get("sha") if g.status_code == 200 else None
                    self.error = "GitHub save conflict — retry"
                    return
                else:
                    self.error = f"GitHub save {r.status_code}: {r.text[:120]}"
                    return
            except Exception as e:
                self.error = f"GitHub save: {e}"
                return
        self.dirty, self.last_save = False, time.time()


STORE = Store()
SNAP = Store("snapshot.json", default={}, min_gap=600)  # கடைசி scan result + daily cache (restart-க்கு பின் உடனே காட்ட)
