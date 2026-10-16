"""Long-term memory: notes from past courses, reused before searching again.

A plain JSONL file with keyword-overlap recall. Swap in a vector store
(pgvector, etc.) later without changing the interface.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from coursegen.models import Note

_WORD = re.compile(r"[a-z0-9]+")
_STOP = set("a an and are as at be by for from how in is it of on or the to what with your you".split())


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 2}


class Memory:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text().splitlines() if line.strip()]

    def save(self, topic: str, notes: list[Note]) -> None:
        known = {(r["claim"], r["source_url"]) for r in self._load()}
        with self.path.open("a") as f:
            for n in notes:
                if n.from_memory or (n.claim, n.source_url) in known:
                    continue
                f.write(json.dumps({"topic": topic, **n.model_dump(exclude={"id", "from_memory"})}) + "\n")

    def recall(self, query_text: str, limit: int = 40, min_overlap: int = 2) -> list[Note]:
        want = _words(query_text)
        scored = []
        for r in self._load():
            have = _words(" ".join([r["topic"], r["claim"], " ".join(r["concepts"])]))
            score = len(want & have)
            if score >= min_overlap:
                scored.append((score, r))
        scored.sort(key=lambda s: -s[0])
        return [
            Note(id=f"m{i}", from_memory=True, **{k: v for k, v in r.items() if k != "topic"})
            for i, (_, r) in enumerate(scored[:limit])
        ]
