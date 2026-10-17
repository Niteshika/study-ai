"""The MCP server: the tools Claude can call.

Phase 0: one `ping` tool, just to prove Claude can connect.
Phase 1+: plan tools (list_plans, get_plan, save_plan) once login (OAuth) works,
because every tool needs to know WHICH user is calling.

Claude does the teaching. These tools only save and load the learning data,
by calling into core/ - the same code the website uses.
"""

from mcp.server.mcpserver import MCPServer

from core import db

mcp = MCPServer(
    name="study-ai",
    instructions=(
        "study-ai remembers a learner's study plans, what they have mastered, their mistakes "
        "and when each concept is due for review. Use these tools to save and load that data; "
        "you do the explaining and quizzing yourself."
    ),
)


@mcp.tool()
def ping() -> dict:
    """Check that the study-ai server and its database are reachable.
    Call this only when the user asks whether study-ai is connected."""
    with db.connect() as conn:
        conn.execute("SELECT 1")
    return {"ok": True, "server": "study-ai"}
