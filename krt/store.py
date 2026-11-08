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
        self.load_failed = False        # v89: GitHub load fail ஆனா → remote save தடை (history overwrite ஆகாம) + retry
        self._retry_t = 0.0

    @property
    def remote(self):
        return bool(self.token and self.repo)

    def _h(self):
        return {"Authorization": f"Bearer {self.token}", "Accept": "application/vnd.github+json"}

    def _fetch(self):
        """GitHub-ல் இருந்து (data, sha, status). status: 200 / 404 / error code / 'exc'."""
        r = requests.get(f"https://api.github.com/repos/{self.repo}/contents/{self.path}", headers=self._h(), timeout=20)
        if r.status_code != 200:
            return None, None, r.status_code
        j = r.json()
        if j.get("content"):
            return json.loads(base64.b64decode(j["content"]).decode("utf-8")), j["sha"], 200
        rr = requests.get(f"https://api.github.com/repos/{self.repo}/contents/{self.path}",
                          headers={**self._h(), "Accept": "application/vnd.github.raw+json"}, timeout=60)
        return (json.loads(rr.text), j["sha"], 200) if rr.status_code == 200 else (None, None, rr.status_code)

    def _merge(self, remote, mem):
        """GitHub data அடிப்படை + memory-ல் புதுசா வந்தவை (அதே id-க்கு memory = புதியது)."""
        out = dict(remote or {})
        for k, v in (mem or {}).items():
            if isinstance(v, dict) and isinstance(out.get(k), dict):
                out[k] = {**out[k], **v}
            elif k not in out or not out[k]:
                out[k] = v
        return out

    def retry_remote(self, force=False):
        """Load fail ஆன பிறகு 60 sec-க்கு ஒருமுறை மறுபடி try → வெற்றி = merge, remote save மீண்டும் அனுமதி."""
        if not (self.remote and self.load_failed):
            return False
        if not force and time.time() - self._retry_t < 60:
            return False
        self._retry_t = time.time()
        try:
            data, sha, st = self._fetch()
        except Exception as e:
            self.error = f"GitHub load: {e}"
            return False
        if st == 200 or st == 404:
            with self.lock:
                self.data = self._merge(data or {}, self.data or {})
                if self.default is None:
                    self.data.setdefault("calls", {})
                    self.data.setdefault("published", {})
                self.sha, self.load_failed, self.error, self.dirty = sha, False, None, True
            return True
        self.error = f"GitHub load {st}" + (" — GITHUB_TOKEN தவறு / expire ஆச்சு" if st in (401, 403) else "")
        return False

    def load(self):
        if self.data is not None:
            if self.load_failed:
                self.retry_remote()
            return self.data
        data = None
        if self.remote:
            try:
                r = requests.get(f"https://api.github.com/repos/{self.repo}/contents/{self.path}", headers=self._h(), timeout=20)
                if r.status_code == 200:
                    j = r.json()
                    self.sha = j["sha"]
                    if j.get("content"):
                        data = json.loads(base64.b64decode(j["content"]).decode("utf-8"))
                    else:   # 1MB-க்கு மேல் → raw ஆக எடு
                        rr = requests.get(f"https://api.github.com/repos/{self.repo}/contents/{self.path}",
                                          headers={**self._h(), "Accept": "application/vnd.github.raw+json"}, timeout=60)
                        if rr.status_code == 200:
                            data = json.loads(rr.text)
                elif r.status_code != 404:
                    self.error = f"GitHub load {r.status_code}" + (" — GITHUB_TOKEN தவறு / expire ஆச்சு" if r.status_code in (401, 403) else "")
                    self.load_failed, self._retry_t = True, time.time()
            except Exception as e:
                self.error = f"GitHub load: {e}"
                self.load_failed, self._retry_t = True, time.time()
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
        blocked = bool(self.remote and self.load_failed and not self.retry_remote(force=force))   # வெற்றி = merge ஆன data
        body = json.dumps(self.data, default=str, ensure_ascii=False, separators=(",", ":"))
        self.local.parent.mkdir(parents=True, exist_ok=True)
        self.local.write_text(body, encoding="utf-8")
        if blocked:
            return                       # GitHub history load ஆகாம remote-ல் எழுதவே கூடாது (overwrite ஆபத்து) — dirty-ஆ இருக்கும், அடுத்த முறை
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
SNAP = Store("snapshot.json", default={}, min_gap=600)
BARS = Store("bars.json", default={}, min_gap=3600)   # 213 stocks daily bars — restart-க்கு பின் 210 API calls தவிர்க்க  # கடைசி scan result + daily cache (restart-க்கு பின் உடனே காட்ட)
