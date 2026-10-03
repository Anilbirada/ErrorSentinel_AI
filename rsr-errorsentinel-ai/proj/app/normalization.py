"""Deterministic, configurable error-code normalization."""
from __future__ import annotations

import re
import unicodedata

DEFAULT_PREFIX_ALIASES = {"ERROR": "ERR", "ERRNO": "ERR"}
_DASHES = dict.fromkeys(map(ord, "\u2010\u2011\u2012\u2013\u2014\u2015\u2212\ufe58\ufe63\uff0d"), "-")
_PREFIX_NUM = re.compile(r"([A-Z]+)[ _\-:#]*(\d+)")


class Normalizer:
    def __init__(self, prefix_aliases: dict[str, str] | None = None) -> None:
        aliases = DEFAULT_PREFIX_ALIASES if prefix_aliases is None else prefix_aliases
        self.aliases = {k.upper(): v.upper() for k, v in aliases.items()}

    def normalize(self, raw: str) -> str:
        """err-5021, ' Error-5021', 'ERR–5021' -> 'ERR-5021'. The raw value is kept elsewhere."""
        s = unicodedata.normalize("NFKC", raw or "").translate(_DASHES)
        s = re.sub(r"\s+", " ", s.strip().upper())
        m = _PREFIX_NUM.fullmatch(s)
        if m:
            return f"{self.aliases.get(m.group(1), m.group(1))}-{m.group(2)}"
        s = re.sub(r"[\s_]+", "-", s)
        s = re.sub(r"-{2,}", "-", s)
        return s.strip("-.:,;[]()")
