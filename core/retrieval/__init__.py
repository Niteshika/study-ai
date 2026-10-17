"""Files & retrieval.

    from core.retrieval import ingest_file, match_file_to_concepts, get_chunks, search, get_file_coverage

Set RETRIEVAL_STUB=1 to get the fake versions (no API key, no database).
"""

import os

if os.getenv("RETRIEVAL_STUB") == "1":
    from .stubs import get_chunks, get_file_coverage, ingest_file, match_file_to_concepts, search
else:
    from .service import get_chunks, get_file_coverage, ingest_file, match_file_to_concepts, search

__all__ = ["ingest_file", "match_file_to_concepts", "get_chunks", "search", "get_file_coverage"]
