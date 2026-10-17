"""The one web server. Runs in one Docker container on EC2.

    /api/...   endpoints for the website
    /mcp       the MCP server, for Claude (custom connector)

Run locally:   uvicorn api.main:app --reload
"""
# In short: this file starts one server, prepares the database, 
# protects /mcp, gives you a health check, and serves both the website API 
# and Claude’s MCP endpoint from the same place.
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from mcp.server.transport_security import TransportSecuritySettings

from core import db
from mcp_server import mcp

# PUBLIC_HOST = your domain, e.g. studyai.example.com. When set, the MCP endpoint
# only answers requests for that host (protects against DNS-rebinding attacks).
_public_host = os.getenv("PUBLIC_HOST")
_security = (TransportSecuritySettings(allowed_hosts=[_public_host, "localhost", "127.0.0.1"],
                                       allowed_origins=[f"https://{_public_host}"])
             if _public_host else TransportSecuritySettings(enable_dns_rebinding_protection=False))

# stateless + JSON replies: every request stands alone, so a restart never breaks a chat.
mcp_app = mcp.streamable_http_app(streamable_http_path="/mcp", stateless_http=True,
                                  json_response=True, transport_security=_security)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if os.getenv("INIT_DB_ON_START", "1") == "1":
        db.init_db()                       # create tables if they don't exist yet
    async with mcp.session_manager.run():  # needed for the /mcp endpoint
        yield
    db.close_pool()                        # on shutdown: close pooled DB connections


app = FastAPI(title="study-ai", lifespan=lifespan)


@app.get("/api/health")
def health():
    """Used by you (and later a load balancer) to check the server and database are up."""
    try:
        with db.connect() as conn:
            row = conn.execute(
                "SELECT extversion FROM pg_extension WHERE extname = 'vector'").fetchone()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=503, detail=f"database unreachable: {type(e).__name__}")
    return {"ok": True, "pgvector": row["extversion"] if row else None}


# The MCP endpoint lives at /mcp. Added last so /api routes are matched first.
app.router.routes.extend(mcp_app.routes)
