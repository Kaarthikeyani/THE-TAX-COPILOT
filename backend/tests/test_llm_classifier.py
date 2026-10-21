"""Tier 3: language-model answer fused with the ML probabilities. Off by default; provider calls are mocked."""
import pytest

from app import llm_classifier, ml_classifier


def test_off_by_default_changes_nothing(monkeypatch):
    monkeypatch.delenv("COPILOT_LLM_CLASSIFY", raising=False)
    called = []
    monkeypatch.setattr(llm_classifier, "_complete", lambda p: called.append(p) or "travel")
    r = ml_classifier.ml_classify("ABHIBUS", "debit")
    assert not called and r["source"] != "tier3_llm_fused"


def test_fusion_math():
    p = {"shopping": 0.40, "travel": 0.35, "uncategorized": 0.25}
    assert llm_classifier.fuse(p, "travel")[0] == "travel"           # LLM weight 0.8 overturns a close ML call
    assert llm_classifier.fuse(p, "uncategorized")[0] == "shopping"  # an abstention (weight 0.1) does not
    assert llm_classifier.fuse(p, None)[0] == "shopping"             # no answer: ML alone
    assert llm_classifier.fuse({"travel": 0.95, "shopping": 0.05}, "shopping")[0] == "travel"  # a confident ML call stands


def test_llm_answer_is_used_cached_and_only_merchant_is_sent(monkeypatch):
    monkeypatch.setenv("COPILOT_LLM_CLASSIFY", "1")
    llm_classifier._cache.clear()
    seen = []
    monkeypatch.setattr(llm_classifier, "_complete", lambda prompt: seen.append(prompt) or "travel")
    a = llm_classifier.llm_answer("ZZQ BUS TRIPS", "debit")
    b = llm_classifier.llm_answer("zzq bus trips", "debit")
    assert a == b == "travel" and len(seen) == 1                      # second call served from the cache
    assert "ZZQ BUS TRIPS" in seen[0] and "Rs" not in seen[0] and "balance" not in seen[0].lower()


def test_provider_failure_never_blocks(monkeypatch):
    monkeypatch.setenv("COPILOT_LLM_CLASSIFY", "1")
    llm_classifier._cache.clear()
    monkeypatch.setattr(llm_classifier, "_complete", lambda p: (_ for _ in ()).throw(RuntimeError("down")))
    assert llm_classifier.llm_answer("SOME NEW SHOP", "debit") is None
    r = ml_classifier.ml_classify("SOME NEW SHOP", "debit")
    assert r["category"] and r["source"] != "tier3_llm_fused"


def test_ml_classify_uses_fused_answer(monkeypatch):
    monkeypatch.setenv("COPILOT_LLM_CLASSIFY", "1")
    llm_classifier._cache.clear()
    monkeypatch.setattr(llm_classifier, "_complete", lambda p: "travel")
    r = ml_classifier.ml_classify("QQXV UNKNOWN HOLIDAYS", "debit")
    assert r["category"] == "travel" and r["source"] == "tier3_llm_fused"
