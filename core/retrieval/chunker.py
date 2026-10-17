"""Group text blocks into chunks of about 300-500 tokens.

Rules:
- A heading starts a new chunk (once the current one is big enough) and is
  remembered as the chunk's `section`.
- Paragraphs are never cut in half unless one paragraph alone is too long;
  then it is split on sentence ends.
- Each chunk keeps page_start / page_end so answers can cite the page.
"""

import re

MIN_TOKENS = 300
MAX_TOKENS = 500


def count_tokens(text):
    # ~1.3 tokens per English word. Close enough for sizing; no tokenizer dependency.
    return int(len(text.split()) * 1.3) + 1


def chunk_blocks(blocks, min_tokens=MIN_TOKENS, max_tokens=MAX_TOKENS):
    chunks = []
    cur, cur_tokens, section = [], 0, None
    cur_section = None

    def flush():
        nonlocal cur, cur_tokens
        if cur:
            pages = [p for _, p in cur if p is not None]
            text = "\n\n".join(t for t, _ in cur)
            chunks.append({
                "text": text,
                "section": cur_section,
                "page_start": min(pages) if pages else None,
                "page_end": max(pages) if pages else None,
                "n_tokens": count_tokens(text),
            })
        cur, cur_tokens = [], 0

    for b in blocks:
        if b["heading"]:
            if cur_tokens >= min_tokens * 0.5:  # a new section deserves a new chunk
                flush()
            section = b["text"]
            if not cur:
                cur_section = section
            cur.append((b["text"], b["page"]))
            cur_tokens += count_tokens(b["text"])
            continue

        for piece in _split_long(b["text"], max_tokens):
            n = count_tokens(piece)
            if cur and cur_tokens + n > max_tokens:
                flush()
            if not cur:
                cur_section = section
            cur.append((piece, b["page"]))
            cur_tokens += n
            if cur_tokens >= min_tokens and cur_tokens >= max_tokens * 0.9:
                flush()
    flush()

    # Drop chunks that are only a heading with nothing under it.
    return [c for c in chunks if c["n_tokens"] > 8 or len(chunks) == 1]


def _split_long(text, max_tokens):
    if count_tokens(text) <= max_tokens:
        return [text]
    sentences = re.split(r"(?<=[.!?])\s+", text)
    out, buf = [], ""
    for s in sentences:
        if buf and count_tokens(buf + " " + s) > max_tokens:
            out.append(buf)
            buf = s
        else:
            buf = f"{buf} {s}".strip()
        while count_tokens(buf) > max_tokens:  # one giant "sentence": hard cut on words
            words = buf.split()
            cut = int(max_tokens / 1.3)
            out.append(" ".join(words[:cut]))
            buf = " ".join(words[cut:])
    if buf:
        out.append(buf)
    return out
