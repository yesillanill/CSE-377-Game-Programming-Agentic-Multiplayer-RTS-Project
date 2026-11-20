"""Local, dependency-free retrieval index for the RTS knowledge base.

Pipeline (documented in docs/architecture.md):
    knowledge/*.json + rules.md -> chunk (one record / one "##" section = one chunk)
    -> normalize (lower-case, Turkish ASCII folding, TR->EN synonym + suffix stripping)
    -> BM25 lexical index (persisted to index/index.json by build_index.py)
    -> search(query, top_k) -> [{source_id, score, text}]

BM25 is used instead of neural embeddings so the index is reproducible, explainable and needs no extra model
download. Turkish questions are mapped onto the English game vocabulary before scoring.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

RAG_DIR = Path(__file__).resolve().parent
KNOWLEDGE_DIR = RAG_DIR / "knowledge"
INDEX_PATH = RAG_DIR / "index" / "index.json"

_FOLD = str.maketrans({"ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u", "â": "a", "î": "i", "û": "u"})

# Turkish (ASCII folded) stems -> English game vocabulary. Matched as token prefix when the stem has >= 4 chars.
SYNONYMS: dict[str, str] = {
    "suvari": "cavalry", "atli": "cavalry", "sovalye": "cavalry", "tank": "cavalry",
    "mizrakci": "spearman", "mizrak": "spearman", "piyade": "spearman", "marine": "spearman",
    "okcu": "archer", "keskin": "archer", "nisanci": "archer", "sniper": "archer",
    "isci": "worker", "koylu": "worker", "muhendis": "worker", "engineer": "worker", "villager": "worker",
    "kisla": "barracks", "cephanelik": "barracks", "armory": "barracks",
    "ahir": "stable", "hangar": "stable",
    "demirci": "blacksmith", "lab": "blacksmith",
    "maden": "mine", "rafineri": "mine", "refinery": "mine",
    "kule": "tower", "taret": "tower", "turret": "tower",
    "duvar": "wall", "sur": "wall",
    "saglik": "healthcenter", "revir": "healthcenter", "hastane": "healthcenter", "sifahane": "healthcenter",
    "iyiles": "healing", "tedavi": "healing", "yarali": "wounded",
    "tarla": "farm", "ciftlik": "farm",
    "ev": "house", "habitat": "house",
    "merkez": "towncenter", "us": "towncenter",
    "odun": "wood", "kereste": "wood", "agac": "wood",
    "yiyecek": "food", "yemek": "food", "besin": "food",
    "altin": "gold",
    "kaynak": "resources", "ekonomi": "economy",
    "nufus": "population",
    "zirh": "armor", "armour": "armor",
    "silah": "weapon", "hasar": "damage",
    "yukselt": "upgrade", "gelistir": "upgrade",
    "arastir": "research", "teknoloji": "technology",
    "saldir": "attack", "hucum": "attack",
    "savun": "defense", "defend": "defense", "defence": "defense",
    "karsi": "counter", "guclu": "strong", "zayif": "weak",
    "maliyet": "cost", "fiyat": "cost", "ucret": "cost",
    "sis": "fog", "gorus": "vision",
    "kazan": "win", "kaybet": "lose",
    "yangin": "fire", "salgin": "plague", "yagmur": "rain",
    "tamir": "repair", "onar": "repair", "restore": "repair", "fix": "repair",
    "yikim": "demolish", "yikma": "demolish", "yika": "demolish", "yik": "demolish", "sokum": "demolish",
    "iade": "refund", "refunded": "refund", "bina": "building",
    "egit": "train", "uret": "train",
    "insa": "build", "kur": "build",
    "hiz": "speed", "menzil": "range", "can": "health",
}

STOPWORDS = {
    "the", "a", "an", "is", "are", "what", "which", "how", "do", "does", "i", "my", "me", "to", "of", "and", "or",
    "in", "on", "for", "with", "can", "should", "it", "be", "this", "that", "vs", "against",
    "bir", "ve", "ile", "mi", "mu", "ne", "nasil", "icin", "bu", "su", "o", "da", "de", "ki", "hangi", "neye",
    "nedir", "midir", "ben", "benim", "var", "yok", "gibi", "kac",
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")


def normalize_text(text: str) -> str:
    # Turkish dotted capital I must be handled before lower() (Python lowers "İ" to "i̇")
    return (text or "").replace("İ", "i").lower().translate(_FOLD)


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in _TOKEN_RE.findall(normalize_text(text)):
        if raw in STOPWORDS:
            continue
        mapped = SYNONYMS.get(raw)
        if mapped is None:
            for stem, target in SYNONYMS.items():
                if len(stem) >= 4 and raw.startswith(stem):
                    mapped = target
                    break
        if mapped:
            tokens.append(mapped)
            if mapped != raw:
                tokens.append(raw)  # keep the original token as a weaker extra signal
        else:
            tokens.append(raw)
    return tokens


@dataclass
class Chunk:
    source_id: str
    kind: str
    text: str
    tokens: list[str] = field(default_factory=list)


def _cost_text(cost: dict | None) -> str:
    if not cost:
        return ""
    parts = [f"{v} {k}" for k, v in cost.items() if v]
    return "cost: " + (", ".join(parts) if parts else "free")


def _render_record(rec: dict) -> str:
    """Turns a JSON knowledge record into the plain text chunk that is indexed and returned to the LLM."""
    kind = rec.get("type", "record")
    name = rec.get("display_name") or rec.get("name", "")
    lines = [f"[{kind}] {name}"]
    if rec.get("scifi_name") and rec.get("scifi_name") != name:
        lines[0] += f" (Sci-Fi mode name: {rec['scifi_name']})"
    if kind == "technology":
        lines.append(f"id: {rec.get('name')}; upgrade line: {rec.get('line')} tier {rec.get('level')}")
        lines.append(_cost_text(rec.get("cost")) + f"; research time {rec.get('research_time_s')} s at {rec.get('researched_at')}")
        lines.append(f"prerequisite: {rec.get('prerequisite')}")
        lines.append(f"effect: {rec.get('effect')}")
    elif kind == "unit":
        lines.append(_cost_text(rec.get("cost")) + f"; population {rec.get('population', 1)}; trained at {rec.get('trained_at')}")
        lines.append(
            f"health {rec.get('health')}, damage {rec.get('damage')}, range {rec.get('range')}, "
            f"speed {rec.get('speed')}, vision {rec.get('vision')}"
        )
        if rec.get("strengths"):
            lines.append("strong against (2x damage): " + ", ".join(rec["strengths"]))
        if rec.get("weaknesses"):
            lines.append("weak against: " + ", ".join(rec["weaknesses"]))
    elif kind == "building":
        cost = _cost_text(rec.get("cost"))
        extra = []
        if rec.get("health"):
            extra.append(f"health {rec['health']}")
        if rec.get("population_bonus"):
            extra.append(f"population +{rec['population_bonus']}")
        if rec.get("trains"):
            extra.append("trains " + ", ".join(rec["trains"]))
        lines.append("; ".join([cost] + extra))
    lines.append(rec.get("description", ""))
    return "\n".join(line for line in lines if line)


def _index_text(rec: dict, rendered: str) -> str:
    # Names and aliases are repeated so that "spearman" style lookups rank the record first.
    names = " ".join([rec.get("name", ""), rec.get("display_name", ""), rec.get("scifi_name", "")] + rec.get("aliases", []))
    return f"{names} {names} {rendered}"


def load_chunks(knowledge_dir: Path = KNOWLEDGE_DIR) -> list[Chunk]:
    chunks: list[Chunk] = []
    for json_file in sorted(knowledge_dir.glob("*.json")):
        for rec in json.loads(json_file.read_text(encoding="utf-8")):
            rendered = _render_record(rec)
            chunks.append(Chunk(rec["id"], rec.get("type", "record"), rendered, tokenize(_index_text(rec, rendered))))
    for md_file in sorted(knowledge_dir.glob("*.md")):
        current_id, buf = None, []
        for line in md_file.read_text(encoding="utf-8").splitlines() + ["## __end__"]:
            if line.startswith("## "):
                if current_id and buf:
                    text = " ".join(s.strip() for s in buf if s.strip())
                    kind = "strategy" if current_id.startswith("strategy") else "rule"
                    chunks.append(Chunk(current_id, kind, text, tokenize(current_id.replace("_", " ") + " " + text)))
                current_id, buf = line[3:].strip(), []
            elif current_id:
                buf.append(line)
    ids = [c.source_id for c in chunks]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate knowledge source ids")
    return chunks


class KnowledgeIndex:
    """BM25 index over knowledge chunks."""

    def __init__(self, chunks: list[Chunk], k1: float = 1.5, b: float = 0.75):
        self.chunks = chunks
        self.k1, self.b = k1, b
        self.doc_len = [len(c.tokens) for c in chunks]
        self.avgdl = sum(self.doc_len) / max(1, len(chunks))
        self.tf: list[dict[str, int]] = []
        df: dict[str, int] = {}
        for c in chunks:
            counts: dict[str, int] = {}
            for t in c.tokens:
                counts[t] = counts.get(t, 0) + 1
            self.tf.append(counts)
            for t in counts:
                df[t] = df.get(t, 0) + 1
        n = len(chunks)
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    # ----------------------------------------------------------------- persistence
    def to_json(self) -> dict:
        return {"version": 1, "k1": self.k1, "b": self.b,
                "chunks": [{"source_id": c.source_id, "kind": c.kind, "text": c.text, "tokens": c.tokens} for c in self.chunks]}

    @classmethod
    def from_json(cls, data: dict) -> "KnowledgeIndex":
        chunks = [Chunk(d["source_id"], d["kind"], d["text"], d["tokens"]) for d in data["chunks"]]
        return cls(chunks, data.get("k1", 1.5), data.get("b", 0.75))

    @classmethod
    def load(cls, path: Path = INDEX_PATH) -> "KnowledgeIndex":
        if path.exists():
            return cls.from_json(json.loads(path.read_text(encoding="utf-8")))
        return cls(load_chunks())

    def save(self, path: Path = INDEX_PATH) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_json(), ensure_ascii=False, indent=1), encoding="utf-8")

    # ----------------------------------------------------------------- search
    def search(self, query: str, top_k: int = 3) -> list[dict]:
        q_tokens = list(dict.fromkeys(tokenize(query)))  # unique, order kept
        if not q_tokens:
            return []
        scored = []
        for i, counts in enumerate(self.tf):
            score = 0.0
            dl = self.doc_len[i]
            for t in q_tokens:
                f = counts.get(t)
                if not f:
                    continue
                idf = self.idf.get(t, 0.0)
                score += idf * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avgdl))
            if score > 0:
                scored.append((score, i))
        scored.sort(key=lambda x: (-x[0], self.chunks[x[1]].source_id))
        return [
            {"source_id": self.chunks[i].source_id, "kind": self.chunks[i].kind, "score": round(s, 3), "text": self.chunks[i].text}
            for s, i in scored[:top_k]
        ]

    def get(self, source_id: str) -> Chunk | None:
        return next((c for c in self.chunks if c.source_id == source_id), None)
