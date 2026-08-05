from __future__ import annotations

import json
import re
import threading
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# These aliases ship with the application and are never rewritten. Identities
# learned from provider fixtures are layered on top from team_identity.json.
SEED_TEAM_ALIASES: dict[str, tuple[str, ...]] = {
    "荷兰": ("netherlands", "holland"),
    "瑞典": ("sweden",),
    "德国": ("germany",),
    "科特迪瓦": ("ivory coast", "cote d ivoire", "côte d'ivoire"),
    "突尼斯": ("tunisia",),
    "日本": ("japan",),
    "西班牙": ("spain",),
    "沙特": ("saudi arabia", "saudi"),
    "乌拉圭": ("uruguay",),
    "佛得角": ("cape verde",),
    "新西兰": ("new zealand",),
    "埃及": ("egypt",),
    "阿根廷": ("argentina",),
    "奥地利": ("austria",),
    "法国": ("france",),
    "伊拉克": ("iraq",),
    "挪威": ("norway",),
    "塞内加尔": ("senegal",),
    "约旦": ("jordan",),
    "阿尔及利亚": ("algeria",),
    "葡萄牙": ("portugal",),
    "乌兹别克": ("uzbekistan",),
    "英格兰": ("england",),
    "加纳": ("ghana",),
    "巴拿马": ("panama",),
    "克罗地亚": ("croatia",),
    "哥伦比亚": ("colombia",),
    "民主刚果": ("dr congo", "congo dr", "democratic republic of congo"),
    "曼城": ("manchester city", "man city"),
    "热刺": ("tottenham hotspur", "tottenham", "spurs"),
    "皇家社会": ("real sociedad",),
    "比利亚雷亚尔": ("villarreal",),
    "多特蒙德": ("borussia dortmund", "dortmund"),
    "法兰克福": ("eintracht frankfurt", "frankfurt"),
    "赫根": ("häcken", "hacken", "bk häcken", "bk hacken"),
    "卡尔马": ("kalmar", "kalmar ff"),
    "腓特烈斯塔": ("fredrikstad", "fredrikstad fk"),
    "桑德菲杰": ("sandefjord", "sandefjord fotball"),
    "斯达": ("start", "ik start"),
    "维京": ("viking", "viking fk"),
    "拉赫蒂": ("lahti", "fc lahti"),
    "查路": ("jaro", "ff jaro"),
    "格尼斯坦": ("gnistan", "if gnistan"),
    "古比斯": ("kups", "kuopion palloseura"),
    "达伽马": ("vasco da gama", "vasco"),
    "弗鲁米嫩塞": ("fluminense",),
    "桑托斯": ("santos", "santos fc"),
    "雷莫": ("remo", "clube do remo"),
    "辛辛那提": ("fc cincinnati", "cincinnati"),
    "圣何塞地震": ("san jose earthquakes", "sj earthquakes"),
    "华盛顿联": ("dc united", "d.c. united"),
    "纳什维尔": ("nashville sc", "nashville"),
    "迈阿密国际": ("inter miami", "inter miami cf"),
    "哥伦布机员": ("columbus", "columbus crew"),
    "蒙特利尔": ("cf montreal", "cf montréal", "montreal impact"),
    "新英格兰": ("new england revolution", "new england"),
    "温哥华白浪": ("vancouver whitecaps", "vancouver whitecaps fc"),
    "洛杉矶FC": ("los angeles fc", "lafc"),
    "芝加哥火焰": ("chicago fire", "chicago fire fc"),
    "夏洛特FC": ("charlotte fc", "charlotte"),
    "圣路易斯城": ("st louis city", "st. louis city", "st louis city sc"),
    "皇家盐湖城": ("real salt lake", "salt lake"),
    # Frequently used Chinese lottery abbreviations. These were verified
    # against the provider fixture, competition and kickoff time together.
    "亚拉腊": ("ararat armenia",),
    "采列": ("nk celje", "celje"),
    "米亚尔比": ("mjällby", "mjallby"),
    "布拉迪斯拉发": ("slovan bratislava",),
    "索非亚列夫斯": ("levski sofia",),
    "阿拉木图": ("kairat almaty",),
    "奥林匹亚科斯": ("olympiacos",),
    "奈梅亨": ("nec nijmegen",),
    "布斯巴达": ("sparta prague",),
    "里昂": ("lyon",),
    "圣吉联合": ("union st gilloise", "union st.gilloise"),
    "博德": ("bodø/glimt", "bodo glimt"),
    "奥胡斯": ("agf",),
    "萨巴赫": ("sabah fk",),
    "费内巴切": ("fenerbahçe", "fenerbahce"),
    "格拉茨风暴": ("sturm graz",),
    "库奥皮奥": ("kups",),
    "克拉瓦约": ("universitatea craiova",),
    "比亚韦斯托克": ("jagiellonia białystok", "jagiellonia bialystok"),
    "流浪者": ("rangers",),
    "萨尔茨堡": ("salzburg",),
    "帕福斯FC": ("pafos fc",),
    "塞萨洛": ("paok thessaloniki", "paok"),
    "安德莱赫特": ("anderlecht",),
    "图恩": ("thun",),
    "维京古": ("vikingur reykjavik",),
    "本菲卡": ("benfica",),
    "哈茨": ("hearts",),
}

# Keep this object stable: collectors and other modules import it by reference.
TEAM_ALIASES: dict[str, tuple[str, ...]] = dict(SEED_TEAM_ALIASES)

_IDENTITY_LOCK = threading.RLock()
_IDENTITY_PATH: Path | None = None
_IDENTITY_DATA: dict[str, Any] = {"schema_version": 1, "teams": {}}
_SAFE_CLUB_SUFFIXES = {"afc", "bk", "cf", "club", "fc", "ff", "fk", "football", "if", "sc"}
_LATIN_TRANSLATION = str.maketrans({"ø": "o", "ł": "l", "đ": "d", "ð": "d", "þ": "th", "æ": "ae", "œ": "oe"})


def identity_path_for_cache(cache_dir: str | Path) -> Path:
    """Return an app-writable identity file next to the runtime cache."""
    return Path(cache_dir).parent / "team_identity.json"


def configure_team_identity(path: str | Path | None) -> None:
    """Load persisted aliases and provider IDs into the shared registry."""
    global _IDENTITY_PATH, _IDENTITY_DATA
    with _IDENTITY_LOCK:
        _IDENTITY_PATH = Path(path) if path is not None else None
        _IDENTITY_DATA = {"schema_version": 1, "teams": {}}
        TEAM_ALIASES.clear()
        TEAM_ALIASES.update(SEED_TEAM_ALIASES)
        if _IDENTITY_PATH is None or not _IDENTITY_PATH.exists():
            return
        try:
            raw = json.loads(_IDENTITY_PATH.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return
        if not isinstance(raw, dict) or not isinstance(raw.get("teams"), dict):
            return
        _IDENTITY_DATA = {"schema_version": 1, "teams": raw["teams"]}
        for canonical, record in raw["teams"].items():
            if not isinstance(canonical, str) or not isinstance(record, dict):
                continue
            aliases = list(TEAM_ALIASES.get(canonical, ()))
            for item in record.get("aliases", ()):
                name = item.get("name") if isinstance(item, dict) else item
                if isinstance(name, str) and name.strip() and not _contains_normalized(aliases, name):
                    aliases.append(name.strip())
            TEAM_ALIASES[canonical] = tuple(aliases)


def normalize_team_name(value: str) -> str:
    """Normalize accents and punctuation without deleting CJK team names."""
    value = unicodedata.normalize("NFKD", value.casefold().translate(_LATIN_TRANSLATION))
    value = "".join(character for character in value if not unicodedata.combining(character))
    value = value.replace("＆", "&")
    value = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def team_aliases(local_name: str) -> tuple[str, ...]:
    canonical = _canonical_name(local_name)
    return (canonical, *TEAM_ALIASES.get(canonical, ()))


def team_match_score(local_name: str, candidate_name: str) -> float:
    candidate = normalize_team_name(candidate_name)
    if not candidate:
        return 0.0
    best = 0.0
    for alias in team_aliases(local_name):
        normalized = normalize_team_name(alias)
        if not normalized:
            continue
        if normalized == candidate:
            return 1.0
        if _safe_suffix_variant(normalized, candidate):
            best = max(best, 0.8)
    return best


def provider_team_match_score(
    local_name: str,
    candidate_name: str,
    provider: str,
    candidate_id: object = None,
) -> float:
    """Prefer a previously confirmed provider ID, then fall back to aliases."""
    canonical = _canonical_name(local_name)
    record = _team_record(canonical, create=False)
    provider_ids = record.get("provider_ids", {}) if record else {}
    saved_id = str(provider_ids.get(provider, "")).strip()
    incoming_id = str(candidate_id).strip() if candidate_id is not None else ""
    if saved_id and incoming_id:
        return 1.0 if saved_id == incoming_id else 0.0
    return team_match_score(canonical, candidate_name)


def register_team_alias(
    local_name: str,
    candidate_name: str,
    *,
    provider: str = "",
    provider_id: object = None,
    confidence: float = 1.0,
    source: str = "fixture_pair",
) -> bool:
    """Persist an identity learned from an unambiguous provider fixture."""
    canonical = _canonical_name(local_name)
    candidate = candidate_name.strip()
    normalized = normalize_team_name(candidate)
    if not canonical.strip() or not normalized:
        return False
    with _IDENTITY_LOCK:
        incoming_id = str(provider_id).strip() if provider_id is not None else ""
        if provider and incoming_id:
            existing = _team_record(canonical, create=False)
            existing_id = str(existing.get("provider_ids", {}).get(provider, "")) if existing else ""
            if existing_id and existing_id != incoming_id:
                return False
            owner = _provider_id_owner(provider, incoming_id)
            if owner and owner != canonical:
                return False
        record = _team_record(canonical, create=True)
        changed = False
        aliases = list(TEAM_ALIASES.get(canonical, ()))
        if normalize_team_name(canonical) != normalized and not _contains_normalized(aliases, candidate):
            aliases.append(candidate)
            TEAM_ALIASES[canonical] = tuple(aliases)
            record.setdefault("aliases", []).append(
                {
                    "name": candidate,
                    "provider": provider,
                    "confidence": round(float(confidence), 3),
                    "source": source,
                    "updated_at": _now(),
                }
            )
            changed = True

        if provider and incoming_id:
            provider_ids = record.setdefault("provider_ids", {})
            if str(provider_ids.get(provider, "")) != incoming_id:
                provider_ids[provider] = incoming_id
                changed = True
        if changed:
            record["updated_at"] = _now()
            _save_identity_data()
        return changed


def identity_summary(local_name: str) -> dict[str, Any]:
    """Return non-sensitive identity details for collection diagnostics."""
    canonical = _canonical_name(local_name)
    record = _team_record(canonical, create=False)
    return {
        "canonical_name": canonical,
        "aliases": list(TEAM_ALIASES.get(canonical, ())),
        "provider_ids": dict(record.get("provider_ids", {})) if record else {},
    }


def _canonical_name(value: str) -> str:
    normalized = normalize_team_name(value)
    if value in TEAM_ALIASES:
        return value
    for canonical, aliases in TEAM_ALIASES.items():
        if normalized == normalize_team_name(canonical):
            return canonical
        if any(normalized == normalize_team_name(alias) for alias in aliases):
            return canonical
    return value.strip()


def _safe_suffix_variant(first: str, second: str) -> bool:
    first_tokens = first.split()
    second_tokens = second.split()
    shorter, longer = (first_tokens, second_tokens) if len(first_tokens) <= len(second_tokens) else (second_tokens, first_tokens)
    if not shorter or shorter != longer[: len(shorter)]:
        return False
    extras = longer[len(shorter) :]
    return bool(extras) and all(token in _SAFE_CLUB_SUFFIXES for token in extras)


def _contains_normalized(values: list[str], candidate: str) -> bool:
    normalized = normalize_team_name(candidate)
    return any(normalize_team_name(value) == normalized for value in values)


def _team_record(canonical: str, *, create: bool) -> dict[str, Any]:
    teams = _IDENTITY_DATA.setdefault("teams", {})
    if create:
        return teams.setdefault(canonical, {"aliases": [], "provider_ids": {}})
    record = teams.get(canonical)
    return record if isinstance(record, dict) else {}


def _provider_id_owner(provider: str, provider_id: str) -> str:
    for canonical, record in _IDENTITY_DATA.get("teams", {}).items():
        if isinstance(record, dict) and str(record.get("provider_ids", {}).get(provider, "")) == provider_id:
            return str(canonical)
    return ""


def _save_identity_data() -> None:
    if _IDENTITY_PATH is None:
        return
    _IDENTITY_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = _IDENTITY_PATH.with_suffix(f"{_IDENTITY_PATH.suffix}.tmp")
    temporary.write_text(json.dumps(_IDENTITY_DATA, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(_IDENTITY_PATH)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
