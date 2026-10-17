"""The one LLM wrapper. Only OpenAI or Gemini.

Provider is picked with LLM_PROVIDER in .env:
  openai  -> text-embedding-3-small (1536 dims)
  gemini  -> gemini-embedding-001   (768 dims requested)
  fake    -> offline hashing embedder, for tests only (no API key needed)
"""

import hashlib
import math
import os
import re

from dotenv import load_dotenv

load_dotenv()


def _load_keys_from_secrets_manager():
    """On EC2: if APP_SECRET_ID is set (e.g. study-ai/app), copy OPENAI_API_KEY and
    GEMINI_API_KEY from that secret into the environment, so no key sits in a file.
    Keys already set in the environment win."""
    secret_id = os.getenv("APP_SECRET_ID")
    if not secret_id:
        return
    import json
    import boto3
    sm = boto3.client("secretsmanager", region_name=os.getenv("AWS_REGION", "ap-south-1"))
    for k, v in json.loads(sm.get_secret_value(SecretId=secret_id)["SecretString"]).items():
        if v and not os.getenv(k):
            os.environ[k] = v


_load_keys_from_secrets_manager()

PROVIDER =os.getenv("LLM_PROVIDER", "openai").lower()
OPENAI_EMBED_MODEL = os.getenv("OPENAI_EMBED_MODEL", "text-embedding-3-small")
OPENAI_CHAT_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")
GEMINI_EMBED_MODEL = os.getenv("GEMINI_EMBED_MODEL", "gemini-embedding-001")
GEMINI_CHAT_MODEL = os.getenv("GEMINI_CHAT_MODEL", "gemini-2.5-flash")
_BATCH = 64


def embed(texts, kind="document"):
    """Return one vector per text. kind = 'document' (chunks) or 'query' (searches)."""
    if not texts:
        return []
    if PROVIDER == "fake":
        return [_fake_embed(t) for t in texts]
    out = []
    for i in range(0, len(texts), _BATCH):
        batch = texts[i:i + _BATCH]
        out.extend(_openai_embed(batch) if PROVIDER == "openai" else _gemini_embed(batch, kind))
    return out


def chat(prompt, system=None):
    """Plain text in, plain text out. Used by Phase 5-7 (LLM checks)."""
    if PROVIDER == "openai":
        from openai import OpenAI
        msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
        r = OpenAI().chat.completions.create(model=OPENAI_CHAT_MODEL, messages=msgs, temperature=0)
        return r.choices[0].message.content
    if PROVIDER == "gemini":
        from google import genai
        from google.genai import types
        r = genai.Client().models.generate_content(
            model=GEMINI_CHAT_MODEL, contents=prompt,
            config=types.GenerateContentConfig(system_instruction=system, temperature=0))
        return r.text
    raise RuntimeError("chat() needs LLM_PROVIDER=openai or gemini")


def _openai_embed(batch):
    from openai import OpenAI
    r = OpenAI().embeddings.create(model=OPENAI_EMBED_MODEL, input=batch)
    return [d.embedding for d in r.data]


def _gemini_embed(batch, kind):
    from google import genai
    from google.genai import types
    task = "RETRIEVAL_QUERY" if kind == "query" else "RETRIEVAL_DOCUMENT"
    r = genai.Client().models.embed_content(
        model=GEMINI_EMBED_MODEL, contents=batch,
        config=types.EmbedContentConfig(task_type=task, output_dimensionality=768))
    return [_normalize(e.values) for e in r.embeddings]  # truncated dims need re-normalizing


def _fake_embed(text, dims=256):
    """Bag of words hashed into a fixed vector. Similar words -> similar vectors. Tests only."""
    v = [0.0] * dims
    for w in re.findall(r"[a-z0-9]+", text.lower()):
        if len(w) < 3:
            continue
        w = w[:6]  # crude stemming: 'gradients' ~ 'gradient'
        h = int(hashlib.md5(w.encode()).hexdigest(), 16)
        v[h % dims] += 1.0 if (h >> 8) & 1 else -1.0
    return _normalize(v)


def _normalize(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]
