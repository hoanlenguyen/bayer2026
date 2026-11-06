"""Capture real offline SSE payloads for the frontend presentation contract test."""
import json
import os
import sys
import tempfile
from pathlib import Path

os.environ.update(LLM_PROVIDER="mock", MONGODB_URI="", STAGE_DELAY="0")
os.environ["OUTPUT_DIR"] = tempfile.mkdtemp(prefix="workbench-test-")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from fastapi.testclient import TestClient
from app import catalog as cat
from app.main import app


def events(response):
    response.raise_for_status()
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


with TestClient(app) as client:
    catalog = client.get("/api/catalog").json()
    runs = []
    for preset in client.get("/api/presets").json():
        cat.reset_catalog()  # each preset runs against the untouched estate
        result = events(client.post("/api/chat", json={"preset_id": preset["id"]}))
        conv = next(e["id"] for e in result if e["type"] == "conversation")
        for _ in range(2):
            if next(e["state"] for e in reversed(result) if e["type"] == "done") != "clarifying":
                break
            result += events(client.post("/api/chat", json={"conversation_id": conv, "message": "All products, all markets"}))
        runs.append({"preset": preset["id"], "events": result})
        if next(e["state"] for e in reversed(result) if e["type"] == "done") == "awaiting_approval":
            approved = events(client.post("/api/approve", json={"conversation_id": conv, "approved": True, "approver": "Test reviewer"}))
            runs.append({"preset": preset["id"] + "_approved", "events": result + approved})
    # A free-text request exercises grill-me questions and the consolidate path.
    cat.reset_catalog()
    result = events(client.post("/api/chat", json={"message": "I need net sales and gross-to-net"}))
    conv = next(e["id"] for e in result if e["type"] == "conversation")
    for answer in ("All products, all markets", "Monthly performance review"):
        result += events(client.post("/api/chat", json={"conversation_id": conv, "message": answer}))
    runs.append({"preset": "free_text", "events": result})
    print(json.dumps({"catalog": catalog, "runs": runs}))
