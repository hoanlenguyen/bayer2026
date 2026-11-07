"""Which places a request names, including countries the catalog has no data for.

The catalog holds a few markets. Without this list a request for any other country loses its country when the intent
is cleaned, and then reads as "no country mentioned", so a report for somewhere else can look like a fit.
"""
from __future__ import annotations

import re

from . import catalog as cat
from .datapack import REGION_ALIASES

COUNTRIES = """Afghanistan, Albania, Algeria, Andorra, Angola, Argentina, Armenia, Austria, Azerbaijan, Bahamas, Bahrain,
Bangladesh, Barbados, Belarus, Belgium, Belize, Benin, Bhutan, Bolivia, Bosnia, Botswana, Brunei, Bulgaria, Burkina Faso,
Burundi, Cambodia, Cameroon, Cape Verde, Chad, Chile, Colombia, Comoros, Congo, Costa Rica, Croatia, Cuba, Cyprus, Czechia,
Czech Republic, Denmark, Djibouti, Dominican Republic, Ecuador, Egypt, El Salvador, Eritrea, Estonia, Eswatini, Ethiopia, Fiji,
Gabon, Gambia, Georgia, Ghana, Greece, Guatemala, Guinea, Guyana, Haiti, Honduras, Hong Kong, Hungary, Iceland, India, Indonesia,
Iran, Iraq, Ireland, Israel, Ivory Coast, Jamaica, Jordan, Kazakhstan, Kenya, Kosovo, Kuwait, Kyrgyzstan, Laos, Latvia, Lebanon,
Lesotho, Liberia, Libya, Liechtenstein, Lithuania, Luxembourg, Madagascar, Malawi, Malaysia, Maldives, Mali, Malta, Mauritania,
Mauritius, Moldova, Monaco, Mongolia, Montenegro, Morocco, Mozambique, Myanmar, Namibia, Nepal, Netherlands, New Zealand,
Nicaragua, Niger, Nigeria, North Korea, North Macedonia, Norway, Oman, Pakistan, Panama, Papua New Guinea, Paraguay, Peru,
Philippines, Poland, Portugal, Qatar, Romania, Russia, Rwanda, Saudi Arabia, Senegal, Serbia, Sierra Leone, Singapore, Slovakia,
Slovenia, Somalia, South Africa, South Korea, South Sudan, Sri Lanka, Sudan, Suriname, Switzerland, Syria, Taiwan, Tajikistan,
Tanzania, Thailand, Togo, Trinidad and Tobago, Tunisia, Turkey, Turkmenistan, Uganda, Ukraine, United Arab Emirates, Uruguay,
Uzbekistan, Venezuela, Vietnam, Yemen, Zambia, Zimbabwe"""
_COUNTRIES = [c.strip() for c in COUNTRIES.replace("\n", " ").split(",")]
_ALIASES = {"viet nam": "Vietnam", "korea": "South Korea", "holland": "Netherlands", "uae": "United Arab Emirates"}
# Longest first, so "South Sudan" is not also read as "Sudan".
_NAMES = sorted([*((c.lower(), c) for c in _COUNTRIES), *_ALIASES.items()], key=lambda kv: -len(kv[0]))


def _has(name: str, text: str) -> bool:
    return bool(re.search(rf"\b{re.escape(name)}\b", text))


def other_markets(text: str) -> list[str]:
    """Countries named in the text that the catalog does not hold."""
    low, found = (text or "").lower(), []
    for name, country in _NAMES:
        if _has(name, low):
            found.append(country)
            low = re.sub(rf"\b{re.escape(name)}\b", " ", low)
    return list(dict.fromkeys(found))


def split_other_markets(said: str, unmatched_terms: list[str]) -> tuple[list[str], list[str]]:
    """The countries outside the catalog, and the unmatched terms without them: a country is not a missing KPI."""
    others = other_markets(" ".join([said, *unmatched_terms]))
    return others, [t for t in unmatched_terms if not other_markets(t)]


def _places(text: str) -> tuple[set[str], set[str], set[str]]:
    low = (text or "").lower()
    markets = {k for k, m in cat.CATALOG["markets"].items() if _has(m["name"].lower(), low)}
    regions = {v for k, v in REGION_ALIASES.items() if _has(k, low)}
    return markets, regions, set(other_markets(low))


def same_place(a: str, b: str) -> bool:
    """False only when both texts name places and those places do not overlap. A country counts as inside its region."""
    (ma, ra, oa), (mb, rb, ob) = _places(a), _places(b)
    if not (ma or ra or oa) or not (mb or rb or ob):
        return True
    region_of = {k: m.get("region") for k, m in cat.CATALOG["markets"].items()}
    return bool(ma & mb or ra & rb or oa & ob or {region_of.get(m) for m in ma} & rb or {region_of.get(m) for m in mb} & ra)
