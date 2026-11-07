from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app import catalog as cat
from app.agents import IntentAgent
from app.llm import LLM
from app.main import app
from app.triage import infer_urgency, label_predictability, urgency_from_answer, verify_urgency
from app.vectors import (INDEX_NAME, LocalEmbedder, OpenAIEmbedder, VectorStore, build_atlas_index, request_clusters,
                         similar_requests, suggest_kpis)

from .fakes import ScriptedOpenAI
from .helpers import sse, stage

TABLEAU = "Please create a Power BI replacement for our legacy Tableau Xarelto commercial workbook."


@pytest.fixture(autouse=True)
def _catalog():
    cat.reset_catalog()


# ---------------------------------------------------------------- triage rules
@pytest.mark.parametrize("text, value, source", [
    ("Need Nubeqa sales ASAP for the CFO", "urgent", "inferred"),
    ("Can I have it before the board meeting?", "high", "inferred"),
    ("Kerendia net sales by country", "normal", "default"),
])
def test_infer_urgency(text, value, source):
    u = infer_urgency(text)
    assert (u["value"], u["source"]) == (value, source)
    if source == "inferred":
        assert u["evidence"].lower() in text.lower()


def test_urgency_answers_and_model_verification():
    assert urgency_from_answer("High: this week") == "high"
    assert urgency_from_answer("it's urgent") == "urgent"
    assert urgency_from_answer("whenever") is None
    ok = verify_urgency({"value": "urgent", "evidence": "today"}, "I need it today")
    assert ok == {"value": "urgent", "source": "inferred", "evidence": "today"}
    bad = verify_urgency({"value": "urgent", "evidence": "critical launch"}, "Lynkuet launch dashboard")
    assert bad["value"] == "normal" and bad["source"] == "default" and "note" in bad


def test_labels_are_not_predictable_from_text():
    r = label_predictability(cat.SHEETS["business_requests"])
    assert r["distinct_texts"] == 10 and r["urgency"]["texts_with_mixed_labels"] == 10
    assert r["urgency"]["majority_baseline"] == 0.52
    assert r["urgency"]["best_possible_from_text"] - r["urgency"]["majority_baseline"] < 0.05


# ---------------------------------------------------------------- vector search (offline)
async def test_duplicates_paraphrases_and_clusters():
    store = VectorStore(LocalEmbedder())
    same = await similar_requests(store, TABLEAU)
    assert same["duplicate_count"] == 22 and same["duplicates"][0]["asked"] == 22 and same["search"] == "memory"
    para = await similar_requests(store, "Could you replace the old Tableau workbook for Xarelto with Power BI?")
    assert para["duplicate_count"] == 0 and para["similar"][0]["text"] == TABLEAU
    off = await similar_requests(store, "How many patients adhere to Nubeqa?")
    assert not off["duplicates"] and not off["similar"]
    clusters = await request_clusters(store)
    assert len(clusters) == 10 and sum(c["count"] for c in clusters) == 150 and clusters[0]["count"] == 22


async def test_kpi_suggestions():
    hits = await suggest_kpis(VectorStore(LocalEmbedder()), "gross-to-net and budget variance")
    assert {"gross_to_net_rate", "budget_variance"} <= {h["measure_id"] for h in hits}


# ---------------------------------------------------------------- OpenAI embeddings and Atlas paths
class FakeEmbeddingsClient:
    def __init__(self):
        local = LocalEmbedder()
        self.calls = []

        async def create(model, input):
            self.calls.append((model, len(input)))
            return SimpleNamespace(data=[SimpleNamespace(embedding=local._vec(t)) for t in input])
        self.embeddings = SimpleNamespace(create=create)


async def test_openai_embedder_embeds_distinct_texts_once():
    client = FakeEmbeddingsClient()
    store = VectorStore(OpenAIEmbedder(client))
    r = await similar_requests(store, TABLEAU)
    assert r["embedder"] == "openai" and r["duplicate_count"] == 22
    assert ("text-embedding-3-small", 10) in client.calls   # 150 rows share 10 texts: embedded once each


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def __aiter__(self):
        self._it = iter(self.rows)
        return self

    async def __anext__(self):
        try:
            return next(self._it)
        except StopIteration:
            raise StopAsyncIteration


class FakeAtlasCollection:
    def __init__(self, fail=False):
        self.docs, self.pipelines, self.indexes, self.fail = [], [], [], fail

    async def find_one(self, *_a, **_k):
        return self.docs[0] if self.docs else None

    async def aggregate(self, pipeline):
        if self.fail:
            raise RuntimeError("index not ready")
        self.pipelines.append(pipeline)
        return _Cursor([{**{k: v for k, v in d.items() if k != "embedding"}, "score": 0.95} for d in self.docs[:2]])

    async def delete_many(self, _q):
        self.docs = []

    async def insert_many(self, docs):
        self.docs = list(docs)

    async def list_search_indexes(self):
        return _Cursor([{"name": n} for n in self.indexes])

    async def create_search_index(self, model):
        self.indexes.append(model.document["name"])
        self.created = model.document

    async def update_search_index(self, name, definition):
        self.updated = (name, definition)


async def test_atlas_build_and_vector_search():
    cols = {"request_vectors": FakeAtlasCollection(), "kpi_vectors": FakeAtlasCollection()}
    store = VectorStore(LocalEmbedder(), cols)
    report = await build_atlas_index(store)
    assert report["request_vectors"]["documents"] == 150 and report["kpi_vectors"]["documents"] == 18
    created = cols["request_vectors"].created
    assert created["name"] == INDEX_NAME and created["type"] == "vectorSearch"
    assert created["definition"]["fields"][0] == {"type": "vector", "path": "embedding", "numDimensions": 512, "similarity": "cosine"}
    hits = await store.search("requests", TABLEAU, k=2)
    stage0 = cols["request_vectors"].pipelines[0][0]["$vectorSearch"]
    assert stage0["index"] == INDEX_NAME and stage0["path"] == "embedding" and len(stage0["queryVector"]) == 512
    assert store.backend["requests"] == "atlas" and hits[0].score == pytest.approx(0.9)   # (1+cos)/2 → cos


async def test_atlas_failure_falls_back_to_memory():
    cols = {"request_vectors": FakeAtlasCollection(fail=True), "kpi_vectors": FakeAtlasCollection(fail=True)}
    store = VectorStore(LocalEmbedder(), cols)
    cols["request_vectors"].docs = [{"_id": "x", "embedding_model": LocalEmbedder.model}]
    r = await similar_requests(store, TABLEAU)
    assert r["search"] == "memory" and r["duplicate_count"] == 22


# ---------------------------------------------------------------- intent agent and pipeline
async def test_intent_llm_urgency_needs_quoted_evidence():
    llm = LLM(client=ScriptedOpenAI([{"json": {"status": "clear", "question": None, "suggestions": [], "intent": {
        "decision": "Review", "measures": ["net_sales"], "filters": {"product": ["Nubeqa"]},
        "urgency": {"value": "urgent", "evidence": "critical launch"}}}}]), provider="openai")
    run = await IntentAgent(llm).run({"transcript": [{"role": "user", "content": "Nubeqa net sales by country"}],
                                      "intent": {"measures": []}, "asked": 0, "preset": None})
    assert run.output["intent"]["urgency"]["value"] == "normal"
    assert any(s.kind == "check" and "Urgency" in s.name for s in run.steps)


def test_pipeline_tags_status_urgency_and_duplicates():
    with TestClient(app) as c:
        evs = sse(c.post("/api/chat", json={"preset_id": "req_migrate_xarelto"}))
        tri = stage(evs, "intent")["data"]["triage"]
        assert tri["status"] == "new" and tri["urgency"]["source"] == "default"
        assert tri["similar"]["duplicate_count"] == 22
        assert stage(evs, "decision")["data"]["triage"]["status"] == "triaged"
        intents = c.get("/api/conversations/" + evs[0]["id"]).json()
        assert intents["triage"]["status"] == "triaged"


def test_grill_me_asks_when_needed_and_accepts_stated_urgency():
    with TestClient(app) as c:
        evs = sse(c.post("/api/chat", json={"message": "Net sales and gross-to-net for all products"}))
        conv = evs[0]["id"]
        q1 = next(e for e in evs if e["type"] == "message")["content"]
        evs = sse(c.post("/api/chat", json={"conversation_id": conv, "message": "Monthly performance review"}))
        q2 = next(e for e in evs if e["type"] == "message")
        assert "decision" in q1.lower() and q2["content"] == "When do you need this?" and "High: this week" in q2["suggestions"]
        evs = sse(c.post("/api/chat", json={"conversation_id": conv, "message": "High: this week"}))
        tri = stage(evs, "decision")["data"]["triage"]
        assert tri["urgency"] == {"value": "high", "source": "stated", "evidence": "High: this week"} and tri["status"] == "triaged"


def test_inferred_urgency_skips_the_question():
    with TestClient(app) as c:
        evs = sse(c.post("/api/chat", json={"message": "I need net sales for all products ASAP"}))
        assert stage(evs, "intent")["data"]["triage"]["urgency"]["value"] == "urgent"


def test_request_endpoints():
    with TestClient(app) as c:
        assert c.get("/api/requests/clusters").json()["distinct_asks"] == 10
        assert c.get("/api/requests/similar", params={"q": TABLEAU}).json()["duplicate_count"] == 22
        assert c.get("/api/requests/label-check").json()["status"]["majority_baseline"] == 0.52
