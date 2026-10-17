# One container = website API (/api) + MCP server (/mcp).
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY core ./core
COPY api ./api
COPY mcp_server ./mcp_server

# Don't run as root inside the container.
RUN useradd --create-home app && mkdir -p /app/data && chown app /app/data
USER app

EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
