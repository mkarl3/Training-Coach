"""Per-question retrieval against the frozen methodology index.

Embeds the question with the stored vocabulary/idf, cosine-similarity against the stored
chunk vectors, returns the top-K passages. The model reads them, answers, forgets them.
Deterministic: same question + same index -> same chunks.
"""
import json
import math
import re
import sqlite3

from .config import DEFAULT

_TOKEN = re.compile(r"(?u)\b\w\w+\b")


class MethodologyIndex:
    def __init__(self, db_path, cfg=DEFAULT):
        self.cfg = cfg
        conn = sqlite3.connect(db_path)
        meta = dict(conn.execute("SELECT key, value FROM meta"))
        self.version = meta["corpus_version"]
        self.vocab = json.loads(meta["vocabulary"])
        self.idf = json.loads(meta["idf"])
        self.chunks = []                          # (doc, seq, text, {idx: w}, norm)
        for doc, seq, text, vec_json in conn.execute("SELECT doc, seq, text, vector FROM chunk"):
            v = {int(k): w for k, w in json.loads(vec_json).items()}
            norm = math.sqrt(sum(w * w for w in v.values())) or 1.0
            self.chunks.append((doc, seq, text, v, norm))
        conn.close()

    def _vectorize_query(self, q):
        toks = [t.lower() for t in _TOKEN.findall(q)]
        # unigrams + bigrams to mirror the index's ngram_range=(1,2)
        grams = toks + [f"{a} {b}" for a, b in zip(toks, toks[1:])]
        tf = {}
        for g in grams:
            j = self.vocab.get(g)
            if j is not None:
                tf[j] = tf.get(j, 0) + 1
        v = {j: (1 + math.log(c)) * self.idf[j] for j, c in tf.items()}
        norm = math.sqrt(sum(w * w for w in v.values())) or 1.0
        return v, norm

    def retrieve(self, question, k=None):
        """Top-K chunks above min_similarity. Empty list = nothing supports the question
        (the coach must then soft-flag any general-knowledge answer)."""
        k = k or self.cfg.methodology_chunks_per_query
        qv, qn = self._vectorize_query(question)
        if not qv:
            return []
        scored = []
        for doc, seq, text, v, norm in self.chunks:
            dot = sum(w * v[j] for j, w in qv.items() if j in v)
            if dot > 0:
                scored.append((dot / (qn * norm), doc, seq, text))
        scored.sort(key=lambda s: -s[0])
        return [{"score": round(s, 4), "doc": d, "seq": q, "text": t}
                for s, d, q, t in scored[:k] if s >= self.cfg.min_similarity]
