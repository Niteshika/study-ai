# study-ai

A study assistant that remembers what you're learning: plans, concepts, your notes,
and (soon) mastery, mistakes and review dates. It has two front doors that share one core:

```
Website ──► /api ─┐
                  ├──► core/  (all the logic)  ──► Postgres + pgvector, S3
Claude  ──► /mcp ─┘
```

| Folder | What's in it |
|---|---|
| `core/` | All real logic: `db.py`, `schema.sql`, `llm.py` (OpenAI/Gemini), `storage.py`, `curriculum/`, `retrieval/` |
| `api/` | The web server (FastAPI). Serves `/api/...` and mounts the MCP server at `/mcp` |
| `mcp_server/` | The tools Claude can call |
| `workers/` | Lambda jobs (later phases) |
| `tests/` | Run against a real local Postgres + pgvector |

## Run locally

```bash
pip install -r requirements.txt
cp .env.example .env            # fill in DATABASE_URL and an API key

python -m core.db init           # create tables (safe to re-run)
uvicorn api.main:app --reload    # http://localhost:8000/api/health  and  /mcp
```

## Tests

Tests need a **local** Postgres with pgvector (they wipe the tables, so never use RDS):

```bash
docker run -d --name studyai-pg -e POSTGRES_PASSWORD=pw -e POSTGRES_DB=studyai_test \
    -p 5432:5432 pgvector/pgvector:pg17
pytest -q
```

Tests also run automatically on GitHub (Actions tab) on every push. See `.github/workflows/tests.yml`.

## Run on EC2

On the server (Session Manager → `sudo su - ubuntu`):

```bash
cd ~/study-ai && git pull
cat > .env <<'EOF'
LLM_PROVIDER=openai
APP_SECRET_ID=study-ai/app
DB_SECRET_ID=rds!db-XXXXXXXX
DB_HOST=YOUR-ENDPOINT.ap-south-1.rds.amazonaws.com
AWS_REGION=ap-south-1
S3_BUCKET=study-ai-uploads-YOURNAME
EOF

docker compose up -d --build
curl localhost:8000/api/health         # {"ok": true, "pgvector": "..."}
docker compose logs -f                  # watch logs (Ctrl+C to stop watching)
```

No passwords or API keys go in `.env`: the server reads them from Secrets Manager using its IAM role.
