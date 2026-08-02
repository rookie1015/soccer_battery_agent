from __future__ import annotations

import re


# One shared identity table is used by strength, media, foreign-odds and
# prediction-market matching. Keeping separate copies previously meant that a
# team could match one provider but silently fail every other provider.
TEAM_ALIASES: dict[str, tuple[str, ...]] = {
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
    "乌兹别克": ("uzbekistan", "uzbekistan u20"),
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
    # 26098 and the same leagues' commonly returned provider names.
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
}


def normalize_team_name(value: str) -> str:
    """Normalize provider names without deleting CJK team names."""
    value = value.casefold().replace("＆", "&")
    value = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def team_match_score(local_name: str, candidate_name: str) -> float:
    candidate = normalize_team_name(candidate_name)
    if not candidate:
        return 0.0
    best = 0.0
    for alias in (local_name, *TEAM_ALIASES.get(local_name, ())):
        normalized = normalize_team_name(alias)
        if not normalized:
            continue
        if normalized == candidate:
            return 1.0
        if normalized in candidate or candidate in normalized:
            best = max(best, 0.8)
    return best


def register_team_alias(local_name: str, candidate_name: str) -> bool:
    """Register a provider name learned from an unambiguous fixture pairing."""
    normalized = normalize_team_name(candidate_name)
    if not local_name.strip() or not normalized or team_match_score(local_name, candidate_name) > 0:
        return False
    aliases = list(TEAM_ALIASES.get(local_name, ()))
    if all(normalize_team_name(alias) != normalized for alias in aliases):
        aliases.append(candidate_name.strip())
        TEAM_ALIASES[local_name] = tuple(aliases)
        return True
    return False
