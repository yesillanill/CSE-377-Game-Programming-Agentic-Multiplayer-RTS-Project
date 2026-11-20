"""Deterministic guard rails around the LLM: language detection, topic / cheat / prompt-injection checks and
canned localized replies. These run in code, so they hold even when the model ignores its system prompt."""

from __future__ import annotations

import re

_FOLD = str.maketrans({"ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u"})
_TR_CHARS = set("çğıöşüÇĞİÖŞÜ")

_TR_WORDS = {
    "ve", "bir", "bu", "su", "ne", "nasil", "neden", "nicin", "mi", "mu", "var", "yok", "icin", "ile", "gibi", "kac",
    "hangi", "nerede", "merhaba", "selam", "tesekkurler", "tesekkur", "sagol", "yapmaliyim", "yapayim", "miyim",
    "misin", "musun", "midir", "nedir", "olur", "olsun", "ben", "benim", "sen", "bana", "simdi", "daha", "cok",
    "az", "eger", "ama", "fakat", "lazim", "gerek", "gerekli", "uretebilir", "yapabilir", "saldirmali", "kim",
    "hangisi", "durum", "iyi", "kotu", "evet", "hayir", "karsi", "ordum", "kaynaklarim", "yardim", "et", "ya",
}
_EN_WORDS = {
    "the", "and", "is", "are", "what", "how", "why", "can", "should", "i", "my", "me", "do", "does", "to", "of",
    "against", "with", "now", "you", "which", "where", "hello", "hi", "thanks", "thank", "please", "help", "will",
    "would", "could", "attack", "defend", "train", "build", "a", "an", "it", "this", "that", "be", "have",
}


def fold(text: str) -> str:
    return (text or "").replace("İ", "i").lower().translate(_FOLD)


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z]+", fold(text))


def language_scores(text: str) -> tuple[int, int]:
    words = _words(text)
    tr = sum(1 for w in words if w in _TR_WORDS) + 2 * sum(1 for ch in (text or "") if ch in _TR_CHARS)
    en = sum(1 for w in words if w in _EN_WORDS)
    return tr, en


def detect_language(text: str, fallback: str = "en") -> str:
    """Returns "tr" or "en". Turkish letters / Turkish function words win; ties fall back to the UI language."""
    tr, en = language_scores(text)
    if tr > en:
        return "tr"
    if en > tr:
        return "en"
    return fallback if fallback in ("tr", "en") else "en"


# --------------------------------------------------------------------------------------------- cheat / injection
_INJECTION_PATTERNS = [
    r"ignore (all |any |the |your )?(previous |prior |above )?(rules|instructions|prompt)",
    r"disregard (the |all |your )?(rules|instructions)",
    r"system prompt", r"developer mode", r"jailbreak", r"you are now", r"act as",
    r"(kurallari|talimatlari|kurallarini|talimatlarini) (unut|yok say|gormezden gel|cigne|bosver)",
    r"(onceki|tum) (talimat|kural)", r"sistem (mesaj|istem|prompt)",
]
_ENEMY = r"(enemy|enemies|opponent|opponents|rival|other player|rakip|rakib|dusman|karsi(daki)? oyuncu|oteki oyuncu)\w*"
# Information the player cannot see in the game: opponent economy / technology / hidden units.
_SECRET = (r"(gold|wood|food|resources?|economy|tech|technology|upgrades?|population|hidden|exact (position|location)|"
           r"altin|odun|yiyecek|kaynak|ekonomi|teknoloji|yukseltme|nufus|gizli|tam (yer|konum)|koordinat)")
_CHEAT_PATTERNS = [
    # "enemy's gold", "rakibin kaynakları", "opponent hidden units"
    _ENEMY + r"('s|s')?\W+(\w+\W+){0,2}" + _SECRET,
    # "how much gold does the enemy have", "rakip kaç altına sahip" (question form only, to avoid false positives)
    r"(how much|how many|ne kadar|kac)\W+(\w+\W+){0,1}" + _SECRET + r"\w*\W+(\w+\W+){0,3}" + _ENEMY,
    r"(what|which|hangi)\W+" + _SECRET + r"\w*\W+(\w+\W+){0,2}" + _ENEMY,
    r"(where is|where are|where's|location of|find) (the )?" + _ENEMY + r"('s)?\W+(\w+\W+){0,1}(base|town center|army|units|towncenter)",
    r"(dusman|rakip|rakib)\w*\W+(\w+\W+){0,1}(us|ussu|ussunun|sehir merkezi|ordu)\w*\W+(\w+\W+){0,1}(nerede|nerde|konum)",
    r"(fog of war|under the fog|hidden (units?|enemies|base)|behind the fog|reveal (the )?map|map ?hack|wallhack|see everything)",
    r"(sis(in)? (altinda|arkasinda)|savas sisi|gizli (birim|dusman|us)|gorunmeyen|haritayi (ac|goster)|her seyi gor)",
]

# Questions about the opponent's units / buildings / walls / army size / standing ("rakibin kaç okçusu var?",
# "rakip duvarları ördü mü?", "does the enemy have tanks?", "who is ahead?"). The Commander never answers these, even
# from visible units: a count or a yes/no would either leak or invent opponent state. Tactical questions about enemies
# ("düşman süvarilerine karşı ne yapmalıyım?", "enemy cavalry is attacking my base") stay allowed.
_ENEMY_TR = r"\b(rakibin|rakiplerin|rakipte|rakiplerde|rakipler|rakip|dusmanin|dusmanlarin|dusmanda|dusmanlar|dusman)\b"
_ENEMY_EN = r"\b(the |my |your )?(enemy|enemies|opponent|opponents|rival|other player)\b"
_INTEL_OBJ_TR = (r"(okcu|mizrakci|piyade|suvari|tank|keskin nisanci|isci|muhendis|asker|birlik|birim|ordu|kisla|ahir|"
                 r"demirci|kule|duvar|ev|maden|tarla|bina|us|sehir merkez|saglik merkez|revir|hastane|sifahane|yukseltme|savunma)\w*")
_INTEL_OBJ_EN = (r"(archers?|spearm[ae]n|cavalry|tanks?|snipers?|marines?|knights?|workers?|villagers?|engineers?|soldiers?|"
                 r"troops?|units?|army|armies|barracks|stables?|blacksmiths?|towers?|turrets?|walls?|houses?|mines?|farms?|"
                 r"buildings?|armory|vehicle bay|tech lab|health cent(er|re)s?|med ?bays?|hospitals?|defen[cs]es?)")
_INTEL_PATTERNS = [
    # TR count: "rakibin kaç okçusu var", "düşmanın ordusu ne kadar büyük" (not "rakibe karşı kaç mızrakçı üreteyim")
    _ENEMY_TR + r"\W+(?!karsi)(\w+\W+){0,2}(kac|ne kadar|sayisi|sayi)\b",
    # TR count, question word first: "kaç tane düşman okçusu var"
    r"\b(kac|ne kadar)\W+(tane\W+)?" + _ENEMY_TR + r"\W+" + _INTEL_OBJ_TR,
    # TR yes/no about opponent state: "rakibin tankı var mı", "rakip duvarları ördü mü", "düşman kışla kurdu mu"
    _ENEMY_TR + r"\W+(\w+\W+){0,2}" + _INTEL_OBJ_TR + r"\W+(\w+\W+){0,2}(var ?m[iu]|yok ?m[iu]|\w*[dt][iu] ?m[iu]|\w*yor ?m[iu])\b",
    # TR standing: "rakip mi önde ben mi", "düşman benden güçlü mü", "kim kazanıyor"
    _ENEMY_TR + r"\W+(mi\W+)?(\w+\W+){0,1}(onde|geride|guclu|zayif|kazaniyor|kaybediyor)\w*",
    r"\b(kim|hangimiz) (onde|kazaniyor|daha guclu)",
    # EN count: "how many archers does the enemy have", "how many units has the opponent got"
    r"\bhow (many|much)\W+(\w+\W+){0,3}(does|do|did|has|have|is|are)\W+" + _ENEMY_EN,
    # EN yes/no: "does the enemy have tanks", "did the opponent build walls", "has the enemy built a barracks"
    r"\b(does|do|did|has|have|is|are)\W+" + _ENEMY_EN + r"\W+(\w+\W+){0,1}(have|has|got|own|build|built|building|make|made|"
    r"train|trained|training|research|researched|wall|walled)\b",
    # EN: "enemy's army size", "opponent's archer count"
    _ENEMY_EN + r"('s|s')?\W+(\w+\W+){0,1}(army size|unit count|" + _INTEL_OBJ_EN + r"\W*(count|number|size))",
    r"\b(number|count|amount) of\W+(\w+\W+){0,1}" + _ENEMY_EN,
    # EN standing: "is the enemy ahead", "who is winning", "is my opponent stronger than me"
    r"\b(is|are)\W+" + _ENEMY_EN + r"\W+(\w+\W+){0,1}(ahead|winning|losing|stronger|weaker|behind)\b",
    r"\bwho('s| is) (ahead|winning|stronger)",
]


def precheck(text: str) -> dict:
    """Code-level classification of the raw player message (independent from the model)."""
    t = fold(text)
    injection = any(re.search(p, t) for p in _INJECTION_PATTERNS)
    cheat = any(re.search(p, t) for p in _CHEAT_PATTERNS)
    intel = any(re.search(p, t) for p in _INTEL_PATTERNS)
    words = _words(text)
    greeting_words = {"merhaba", "selam", "selamlar", "hello", "hi", "hey", "thanks", "thank", "tesekkurler",
                      "tesekkur", "sagol", "sagolun", "gunaydin", "iyi", "aksamlar", "naber", "nasilsin"}
    greeting = 0 < len(words) <= 4 and any(w in greeting_words for w in words)
    return {"injection": injection, "cheat": cheat or intel or injection, "opponent_intel": intel, "greeting": greeting,
            "too_long": len(text or "") > 400}


# ----------------------------------------------------------------------------------------------- canned replies
def canned(kind: str, lang: str, **kw) -> str:
    tr = lang == "tr"
    if kind == "off_topic":
        return ("Ben yalnızca bu strateji oyunu hakkında yardımcı olabilirim: ekonomi, birimler, binalar, "
                "yükseltmeler ve görünen tehditler. Oyunla ilgili bir soru sorabilirsin."
                if tr else
                "I can only help with this strategy game: economy, units, buildings, upgrades and visible threats. "
                "Please ask a question about the game.")
    if kind == "greeting":
        return ("Merhaba Komutan! Kaynakların, ordun, görünen düşmanlar ve oyun kuralları hakkında soru sorabilirsin. "
                "Örneğin: \"Kuzeydeki süvarilere karşı ne yapmalıyım?\""
                if tr else
                "Hello Commander! Ask me about your resources, army, visible enemies or the game rules. "
                "For example: \"What should I do against the cavalry in the north?\"")
    if kind == "cheat":
        # Never lists or counts enemy units/buildings: any number here would answer the question it refuses.
        if tr:
            return ("Rakip hakkındaki sorulara cevap veremem: rakibin birlik sayılarını, binalarını, duvarlarını, "
                    "kaynaklarını, teknolojisini veya üssünün yerini paylaşmam. Rakibi görmek için keşif birimi "
                    "gönderebilirsin. Kendi ordun, ekonomin, oyun kuralları ya da gördüğün düşmanlara karşı ne yapman "
                    "gerektiği hakkında soru sorabilirsin.")
        return ("I can't answer questions about the opponent: I don't share their unit counts, buildings, walls, "
                "resources, technology or base location. Send a scout if you want to see them. You can ask about your "
                "own army and economy, the game rules, or how to deal with enemies you can see.")
    if kind == "llm_down":
        return ("AI Komutan şu an yanıt veremiyor (yerel dil modeli çalışmıyor). Ollama'nın açık olduğundan emin ol."
                if tr else
                "The AI Commander cannot answer right now (the local language model is not running). Make sure Ollama is started.")
    if kind == "limited":
        return (" (Not: bazı oyun verileri alınamadı, güven düşük.)" if tr else " (Note: some game data could not be read, confidence is limited.)")
    raise KeyError(kind)


_TAG_RE = re.compile(r"<[^>]{0,60}>")


def sanitize_answer(text: str, limit: int = 700) -> str:
    """Strips markup the Unity rich-text renderer would interpret and clamps the length."""
    clean = _TAG_RE.sub("", text or "").replace("\r", "").strip()
    if len(clean) > limit:
        clean = clean[: limit - 1].rstrip() + "…"
    return clean


def answer_matches_language(answer: str, lang: str) -> bool:
    tr, en = language_scores(answer)
    if lang == "tr":
        return tr >= en
    return en >= tr or tr <= 1
