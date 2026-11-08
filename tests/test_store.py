"""v89: GitHub 401 → history overwrite ஆகக்கூடாது · retry · merge."""
import base64
import json

from krt import store as SM


class R:
    def __init__(self, code, js=None):
        self.status_code, self._js, self.text = code, js, json.dumps(js or {})

    def json(self):
        return self._js


def _gh(monkeypatch, state):
    def get(url, headers=None, timeout=None):
        if state["code"] != 200:
            return R(state["code"])
        body = base64.b64encode(json.dumps(state["remote"]).encode()).decode()
        return R(200, {"sha": state["sha"], "content": body})

    def put(url, headers=None, json=None, timeout=None):
        state["puts"].append(json)
        if json.get("sha") != state["sha"]:
            return R(409)
        state["remote"] = __import__("json").loads(base64.b64decode(json["content"]).decode())
        state["sha"] = state["sha"] + "x"
        return R(200, {"content": {"sha": state["sha"]}})
    monkeypatch.setattr(SM.requests, "get", get)
    monkeypatch.setattr(SM.requests, "put", put)


def _store(tmp_path, monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_DATA_REPO", "u/r")
    st = SM.Store("calls.json")
    st.local = tmp_path / "calls.json"
    return st


def test_401_never_overwrites_and_merges_after_fix(tmp_path, monkeypatch):
    state = {"code": 401, "remote": {"calls": {f"old{i}": {"id": f"old{i}"} for i in range(950)}, "published": {}}, "sha": "s1", "puts": []}
    _gh(monkeypatch, state)
    st = _store(tmp_path, monkeypatch)
    d = st.load()
    assert d["calls"] == {} and st.load_failed and "GITHUB_TOKEN" in st.error
    d["calls"]["new1"] = {"id": "new1"}                     # 401 நேரத்தில் வந்த புது call
    st.dirty = True
    st.save(force=True)
    assert state["puts"] == [] and len(state["remote"]["calls"]) == 950       # GitHub-ல் எதுவும் எழுதல
    state["code"] = 200                                   # token சரி பண்ணாச்சு
    st.save(force=True)
    assert not st.load_failed and len(state["remote"]["calls"]) == 951 and "new1" in state["remote"]["calls"]   # 950 பழையது + புதுசு
    assert len(st.load()["calls"]) == 951


def test_load_retries_on_read(tmp_path, monkeypatch):
    state = {"code": 401, "remote": {"calls": {"a": {"id": "a"}}, "published": {}}, "sha": "s1", "puts": []}
    _gh(monkeypatch, state)
    st = _store(tmp_path, monkeypatch)
    assert st.load()["calls"] == {}
    state["code"] = 200
    st._retry_t = 0
    assert "a" in st.load()["calls"]                      # restart இல்லாமலே history திரும்ப வருது
