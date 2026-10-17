"""Fake versions of the retrieval functions.

Same signatures and return shapes as the real ones, so other parts can build
against them before ingestion works. Turn on with RETRIEVAL_STUB=1.
"""

import uuid

_FAKE = [
    {"text": "Gradient descent updates each weight by a small step against the gradient of the loss.",
     "filename": "ml_notes.pdf", "page": 3},
    {"text": "The learning rate controls the step size. Too large and the loss diverges; too small and training is slow.",
     "filename": "ml_notes.pdf", "page": 4},
    {"text": "Overfitting: the model fits noise in the training set and does worse on new data.",
     "filename": "lecture2.md", "page": None},
]


def ingest_file(user_id, file_path):
    return "file_" + uuid.uuid4().hex[:8]


def match_file_to_concepts(user_id, file_id):
    return {
        "matched": [{"concept_id": "c_gradient_descent", "chunk_ids": ["chunk_stub_0"], "score": 0.71}],
        "suggested": [{"id": "sug_stub", "name": "Regularization", "chunk_ids": ["chunk_stub_2"]}],
        "conflicts": [],
    }


def get_chunks(concept_id, k=5):
    return [dict(c, score=round(0.9 - 0.1 * i, 2)) for i, c in enumerate(_FAKE[:k])]


def search(user_id, query, k=5):
    return [dict(c, concept_id="c_gradient_descent", score=round(0.85 - 0.1 * i, 2))
            for i, c in enumerate(_FAKE[:k])]


def get_file_coverage(user_id):
    return [
        {"concept_id": "c_gradient_descent", "verified": True,
         "files": [{"file_id": "file_stub", "filename": "ml_notes.pdf", "chunks": 2}]},
        {"concept_id": "c_backprop", "verified": False, "files": []},
    ]
