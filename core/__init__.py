"""All the real logic, written once. The website (api/) and the MCP server
(mcp_server/) both call into here.

    core.db          database connection + schema
    core.llm         OpenAI / Gemini wrapper (chat + embeddings)
    core.storage     uploads (S3 or local folder)
    core.curriculum  plans and concepts
    core.retrieval   files, chunks, notes search
"""
