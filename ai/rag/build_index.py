"""Builds the retrieval index from ai/rag/knowledge into ai/rag/index/index.json.

Usage (from the ai/ folder):
    python -m rag.build_index            # build + save
    python -m rag.build_index --query "counter cavalry"   # build, save and run a test query
"""

from __future__ import annotations

import argparse
import json
import sys

from rag.retriever import INDEX_PATH, KnowledgeIndex, load_chunks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", help="optional test query after building")
    parser.add_argument("--top-k", type=int, default=3)
    args = parser.parse_args()

    chunks = load_chunks()
    index = KnowledgeIndex(chunks)
    index.save(INDEX_PATH)
    kinds: dict[str, int] = {}
    for c in chunks:
        kinds[c.kind] = kinds.get(c.kind, 0) + 1
    print(f"Indexed {len(chunks)} chunks {kinds} -> {INDEX_PATH}")

    if args.query:
        for hit in index.search(args.query, args.top_k):
            print(json.dumps({k: hit[k] for k in ("source_id", "score")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
