"""Phase 7b: ask-the-repo - tarball indexing, retrieval, cited answers, endpoint."""

import io
import tarfile

import pytest
from fastapi.testclient import TestClient

import sentinel.server as server_mod
from sentinel.ask.answer import _AskOut, answer_question, build_sources
from sentinel.ask.index import RepoIndex, index_db_path, query_tokens
from sentinel.config import Settings
from sentinel.hub import sessions
from sentinel.hub.store import HubStore, hub_db_path
from sentinel.server import SESSION_COOKIE, create_app

SECRET = "hub-secret"

FILES = {
    "README.md": "# Shop\nA tiny shop API. Payments go through `billing/charge.py`.\n",
    "billing/charge.py": "def charge(user, amount):\n    # retry thrice: gateway flakes\n"
                         "    return gateway.post(user, amount)\n",
    "src/authService/login.py": "def login(u, p):\n    return check_password(u, p)\n",
    "node_modules/lib/index.js": "module.exports = 1\n",
    "package-lock.json": "{}\n",
    "logo.png": "not really a png",
    "big/blob.bin": "x",
}


def _tarball(files: dict[str, str], top: str = "acme-shop-abc1234") -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path, text in files.items():
            data = text.encode()
            info = tarfile.TarInfo(f"{top}/{path}")
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        binary = b"\x00\x01\x02" * 10
        info = tarfile.TarInfo(f"{top}/data/raw.dat")
        info.size = len(binary)
        tar.addfile(info, io.BytesIO(binary))
    return buf.getvalue()


@pytest.fixture
def index(tmp_path):
    idx = RepoIndex(index_db_path(str(tmp_path), "acme/shop"))
    idx.build_from_tarball(_tarball(FILES))
    yield idx
    idx.close()


def test_build_skips_vendor_lockfiles_binaries(index):
    tree = index.tree()
    assert "README.md" in tree and "billing/charge.py" in tree
    assert "src/authService/login.py" in tree
    for skipped in ("node_modules/lib/index.js", "package-lock.json", "logo.png",
                    "big/blob.bin", "data/raw.dat"):
        assert skipped not in tree
    assert index.meta("ref") == "abc1234"
    assert index.built


def test_search_hits_path_words_and_content(index):
    # "auth" only appears in the camelCase path, not the file body.
    assert index.search("how does auth work")[0].path == "src/authService/login.py"
    assert index.search("why does the gateway retry")[0].path == "billing/charge.py"
    # porter stemming: plural "retries" still finds "retry"
    assert any(c.path == "billing/charge.py" for c in index.search("gateway retries"))


def test_query_tokens_drop_stopwords_hinglish():
    assert query_tokens("payment retry kaise hota hai") == ["payment", "retry"]
    assert "auth" in query_tokens("where is authService used")


def test_build_sources_numbered_with_blob_links(index):
    context, records = build_sources("acme/shop", index, "payment retry")
    assert "[1]" in context and "FILES:" in context
    urls = [r["url"] for r in records]
    assert any(
        u.startswith("https://github.com/acme/shop/blob/abc1234/billing/charge.py#L1-")
        for u in urls
    )
    assert any("README.md" in u for u in urls)  # README anchors every answer


class _FakeLLM:
    def __init__(self, cited):
        self.cited = cited
        self.prompt = ""

    def structured(self, **kw):
        self.prompt = kw["user_content"]
        return _AskOut(answer="Payments retry [1].", cited=self.cited)


def test_answer_maps_citations_and_drops_bogus(index):
    llm = _FakeLLM(cited=[1, 1, 99])
    settings = Settings(_env_file=None)
    out = answer_question("acme/shop", index, "payment retry", settings, llm=llm)
    assert out["answer"] == "Payments retry [1]."
    assert [s["n"] for s in out["sources"]] == [1]  # deduped, 99 dropped
    assert "QUESTION: payment retry" in llm.prompt


# --- endpoint ---

@pytest.fixture
def client(tmp_path, monkeypatch):
    settings = Settings(
        memory_home=str(tmp_path), post_comments=False,
        github_client_id="cid", github_client_secret="csec", session_secret=SECRET,
        _env_file=None,
    )
    store = HubStore(hub_db_path(str(tmp_path)))
    store.record_installation(10, "acme")
    store.set_repos(10, ["acme/shop"])
    store.link_user(1, [10])
    store.close()

    calls = {"downloads": 0}

    def fake_download(self, owner, repo, max_bytes=0):
        calls["downloads"] += 1
        return _tarball(FILES)

    monkeypatch.setattr(server_mod.GitHubClient, "download_tarball", fake_download)
    monkeypatch.setattr(
        server_mod, "answer_question",
        lambda repo, index, q, s, memory=None: {
            "answer": f"{repo}: {q}", "sources": [], "files": len(index.tree()),
        },
    )
    c = TestClient(create_app(settings), follow_redirects=False)
    c.cookies.set(SESSION_COOKIE, sessions.sign({"uid": 1, "login": "acme"}, SECRET))
    c.calls = calls
    return c


def test_ask_indexes_once_then_reuses(client):
    r1 = client.post("/api/repo/acme/shop/ask", json={"question": "what is this?"})
    assert r1.status_code == 200
    assert r1.json()["answer"] == "acme/shop: what is this?"
    assert r1.json()["indexed_files"] == 3
    client.post("/api/repo/acme/shop/ask", json={"question": "again"})
    assert client.calls["downloads"] == 1  # cached index
    client.post("/api/repo/acme/shop/ask", json={"question": "again", "reindex": True})
    assert client.calls["downloads"] == 2


def test_ask_validation_and_authz(client):
    assert client.post("/api/repo/acme/shop/ask", json={"question": " "}).status_code == 400
    long_q = {"question": "x" * 700}
    assert client.post("/api/repo/acme/shop/ask", json=long_q).status_code == 400
    assert client.post("/api/repo/other/secret/ask", json={"question": "hi"}).status_code == 404
    client.cookies.clear()
    assert client.post("/api/repo/acme/shop/ask", json={"question": "hi"}).status_code == 401


def test_repo_page_has_ask_panel(client, monkeypatch):
    monkeypatch.setattr(server_mod.GitHubClient, "list_open_prs", lambda *a, **k: [])
    monkeypatch.setattr(server_mod.GitHubClient, "list_open_issues", lambda *a, **k: [])
    text = client.get("/repo/acme/shop").text
    assert "Ask this repo" in text
    assert 'data-api="/api/repo/acme/shop/ask"' in text
