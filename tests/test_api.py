"""The web server: /api/health and the MCP endpoint at /mcp."""

import json

import pytest
from fastapi.testclient import TestClient

from api.main import app

MCP_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


def rpc(client, method, params=None, id_=1):
    body = {"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}}
    r = client.post("/mcp", json=body, headers=MCP_HEADERS)
    assert r.status_code == 200, r.text
    return r.json()


@pytest.fixture(scope="module")
def client():
    # One app start for the whole file: the MCP session manager can only start once.
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["ok"] is True and r.json()["pgvector"]


def test_mcp_lists_and_calls_ping(client):
    init = rpc(client, "initialize", {
        "protocolVersion": "2025-06-18", "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"}})
    assert init["result"]["serverInfo"]["name"] == "study-ai"

    tools = rpc(client, "tools/list", id_=2)["result"]["tools"]
    assert "ping" in {t["name"] for t in tools}

    out = rpc(client, "tools/call", {"name": "ping", "arguments": {}}, id_=3)["result"]
    assert out.get("isError") is not True
    assert json.loads(out["content"][0]["text"])["ok"] is True
