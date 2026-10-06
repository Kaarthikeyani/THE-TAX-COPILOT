"""Merchant memory: what the user has taught the app, with tolerance for spelling variants.

Used by the app (rules learned from corrections) and by experiments/hitl_simulation.py, so the simulation measures
the same code that runs in production. Matching: exact normalised key first; otherwise the closest learned key of the
same direction whose character-level similarity (difflib ratio) is at least `cutoff`.
"""
from difflib import SequenceMatcher, get_close_matches
from typing import Dict, Optional, Tuple

DEFAULT_CUTOFF = 0.88
_NOISE = {"PVT", "LTD", "LLP", "INDIA", "ONLINE", "PAYMENTS", "SERVICES", "IN", "LIMITED", "PRIVATE"}


def canon(key: str) -> str:
    """Drop store/ref numbers and generic corporate suffixes so 'SWIGGY 4417' and 'SWIGGY PVT LTD' compare equal."""
    toks = [t for t in key.split() if not t.isdigit() and t not in _NOISE]
    return " ".join(toks) or key


class MerchantMemory:
    def __init__(self, cutoff: float = DEFAULT_CUTOFF):
        self.cutoff = cutoff
        self._by_type: Dict[str, Dict[str, str]] = {"debit": {}, "credit": {}}
        self._canon: Dict[str, Dict[str, str]] = {"debit": {}, "credit": {}}  # canonical form -> stored key

    def learn(self, key: str, txn_type: str, category: str):
        if key:
            self._by_type.setdefault(txn_type, {})[key] = category
            self._canon.setdefault(txn_type, {})[canon(key)] = key

    def lookup(self, key: str, txn_type: str) -> Optional[Tuple[str, str, float]]:
        """Return (category, matched_key, similarity) or None."""
        d, cn = self._by_type.get(txn_type, {}), self._canon.get(txn_type, {})
        if not key or not d:
            return None
        if key in d:
            return d[key], key, 1.0
        ck = canon(key)
        if ck in cn:
            return d[cn[ck]], cn[ck], 1.0
        m = get_close_matches(ck, list(cn), n=1, cutoff=self.cutoff)
        if m:
            return d[cn[m[0]]], cn[m[0]], SequenceMatcher(None, ck, m[0]).ratio()
        return None

    def __len__(self):
        return sum(len(v) for v in self._by_type.values())
