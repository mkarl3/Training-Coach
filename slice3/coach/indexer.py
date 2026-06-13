"""One-time methodology indexing job (the frozen, versioned knowledge base).

Reads the webinar transcripts/articles in `Model Training/`, chunks them into passages,
vectorizes (TF-IDF — local, deterministic, no external embedding vendor; the corpus is
small and frozen so 'deliberately dumb' wins), and stores text + sparse vectors + the
vocabulary in SQLite. Re-run ONLY on deliberate corpus updates; bump corpus_version.

The model never ingests this corpus — retrieval hands it passages per question.
"""
import glob
import json
import os
import re
import sqlite3

from .config import DEFAULT

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS chunk (
    id        INTEGER PRIMARY KEY,
    doc       TEXT NOT NULL,           -- source filename
    seq       INTEGER NOT NULL,        -- chunk order within the doc
    text      TEXT NOT NULL,
    n_words   INTEGER NOT NULL,
    vector    TEXT NOT NULL            -- sparse TF-IDF as JSON {term_idx: weight}
);
"""


# --------------------------------------------------------------------------- #
# Text extraction
# --------------------------------------------------------------------------- #
def _docx_paragraphs(path):
    import docx
    d = docx.Document(path)
    return [p.text.strip() for p in d.paragraphs if p.text.strip()]


def _pdf_paragraphs(path):
    from pypdf import PdfReader
    out = []
    for page in PdfReader(path).pages:
        t = page.extract_text() or ""
        for para in re.split(r"\n\s*\n", t):
            para = " ".join(para.split())
            if para:
                out.append(para)
    return out


def _stem(name):
    s = os.path.splitext(name)[0].lower()
    return re.sub(r"[^a-z0-9]+", "", s)


def corpus_files(corpus_dir):
    """Prefer .docx; include a .pdf only when no near-identical docx stem exists."""
    docx_files = sorted(glob.glob(os.path.join(corpus_dir, "*.docx")))
    pdf_files = sorted(glob.glob(os.path.join(corpus_dir, "*.pdf")))
    docx_stems = {_stem(os.path.basename(f)) for f in docx_files}
    keep_pdfs = [f for f in pdf_files if _stem(os.path.basename(f)) not in docx_stems]
    return docx_files, keep_pdfs


def chunk_paragraphs(paras, target_words, min_words):
    """Greedy paragraph packing to ~target_words, one-paragraph overlap between chunks."""
    chunks, cur, cur_words = [], [], 0
    for p in paras:
        w = len(p.split())
        if cur and cur_words + w > target_words:
            chunks.append(" ".join(cur))
            cur, cur_words = [cur[-1]], len(cur[-1].split())   # overlap last paragraph
        cur.append(p)
        cur_words += w
    if cur:
        tail = " ".join(cur)
        if chunks and len(tail.split()) < min_words:
            chunks[-1] += " " + tail
        else:
            chunks.append(tail)
    return chunks


# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #
def build_index(corpus_dir, db_path, cfg=DEFAULT):
    from sklearn.feature_extraction.text import TfidfVectorizer

    docx_files, pdf_files = corpus_files(corpus_dir)
    docs = []                                     # (filename, [chunks])
    skipped = []
    for path in docx_files + pdf_files:
        name = os.path.basename(path)
        try:
            paras = _docx_paragraphs(path) if path.endswith(".docx") else _pdf_paragraphs(path)
        except Exception as e:                    # a corrupt file shouldn't sink the index
            skipped.append((name, str(e)))
            continue
        chunks = chunk_paragraphs(paras, cfg.chunk_target_words, cfg.chunk_min_words)
        if chunks:
            docs.append((name, chunks))
        else:
            skipped.append((name, "no extractable text"))

    texts = [c for _, cs in docs for c in cs]
    vec = TfidfVectorizer(stop_words="english", sublinear_tf=True, ngram_range=(1, 2),
                          min_df=2, max_df=0.6)
    X = vec.fit_transform(texts)                  # sparse [n_chunks x vocab]

    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO meta VALUES ('corpus_version', ?)", (cfg.corpus_version,))
    conn.execute("INSERT INTO meta VALUES ('vocabulary', ?)",
                 (json.dumps({t: int(i) for t, i in vec.vocabulary_.items()}),))
    conn.execute("INSERT INTO meta VALUES ('idf', ?)", (json.dumps(vec.idf_.tolist()),))

    i = 0
    rows = []
    for name, chunks in docs:
        for seq, text in enumerate(chunks):
            r = X.getrow(i)
            sparse = {int(j): round(float(v), 6) for j, v in zip(r.indices, r.data)}
            rows.append((name, seq, text, len(text.split()), json.dumps(sparse)))
            i += 1
    conn.executemany("INSERT INTO chunk (doc, seq, text, n_words, vector) VALUES (?,?,?,?,?)", rows)
    conn.commit()
    conn.close()
    return {"docs": len(docs), "chunks": len(texts), "vocab": len(vec.vocabulary_),
            "skipped": skipped, "version": cfg.corpus_version}
