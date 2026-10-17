"""Turn an uploaded file into a list of text blocks, each with its page number.

Block = {"text": str, "page": int | None, "heading": bool}
PDF pages are 1-based. MD/TXT have no pages (page=None).
"""

import re
from pathlib import Path

SUPPORTED = {".pdf", ".md", ".markdown", ".txt"}


class UnsupportedFile(ValueError):
    pass


def extract_blocks(path):
    ext = Path(path).suffix.lower()
    if ext == ".pdf":
        return _pdf_blocks(path)
    if ext in (".md", ".markdown"):
        return _text_blocks(_read_text(path), markdown=True)
    if ext == ".txt":
        return _text_blocks(_read_text(path), markdown=False)
    raise UnsupportedFile(f"Unsupported file type '{ext}'. Supported: {', '.join(sorted(SUPPORTED))}")


def pdf_page_count(path):
    import pymupdf
    with pymupdf.open(path) as doc:
        return doc.page_count


def _read_text(path):
    raw = Path(path).read_bytes()
    for enc in ("utf-8-sig", "utf-16", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _text_blocks(text, markdown):
    blocks = []
    for para in re.split(r"\n\s*\n", text):
        para = para.strip()
        if not para:
            continue
        # A markdown heading line can sit right above its paragraph with no blank line.
        lines = para.split("\n")
        if markdown and re.match(r"^#{1,6}\s", lines[0]):
            blocks.append({"text": lines[0].lstrip("#").strip(), "page": None, "heading": True})
            para = "\n".join(lines[1:]).strip()
            if not para:
                continue
        blocks.append({"text": _clean(para), "page": None, "heading": False})
    return blocks


def _pdf_blocks(path):
    import pymupdf
    blocks = []
    with pymupdf.open(path) as doc:
        pages = []
        for pno, page in enumerate(doc, start=1):
            d = page.get_text("dict")
            for b in d["blocks"]:
                if b.get("type") != 0:  # 0 = text, 1 = image
                    continue
                spans = [s for line in b["lines"] for s in line["spans"] if s["text"].strip()]
                if not spans:
                    continue
                text = " ".join(" ".join(s["text"] for s in line["spans"]) for line in b["lines"])
                size = max(s["size"] for s in spans)
                bold = all("bold" in s["font"].lower() or (s["flags"] & 16) for s in spans)
                pages.append((pno, _clean(text), size, bold))
    if not pages:
        return []
    # Body text size = the font size used by the most characters.
    weight = {}
    for _, text, size, _ in pages:
        weight[round(size)] = weight.get(round(size), 0) + len(text)
    body = max(weight, key=weight.get)
    for pno, text, size, bold in pages:
        short = len(text) < 120 and not text.endswith(".")
        is_heading = short and (size >= body * 1.15 or bold)
        blocks.append({"text": text, "page": pno, "heading": is_heading})
    return blocks


def _clean(text):
    text = re.sub(r"-\n(\w)", r"\1", text)       # join hyphenated line breaks
    text = re.sub(r"[ \t]*\n[ \t]*", " ", text)   # single newlines -> spaces
    return re.sub(r"\s{2,}", " ", text).strip()
