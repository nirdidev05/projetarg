from pathlib import Path
import json

import pandas as pd
import pytest

from part2_kialo import parse_export, parse_exports, slugify, validate_listing
from part2_relations import (build_candidate_pairs, classification_metrics,
                             ranking_metrics, split_by_discussion,
                             TfidfInteractionModel, evaluate_discovery_binary,
                             make_discovery_negatives)


def test_slug_and_listing_validation():
    assert slugify("What's AI: A test?") == "whats-ai-a-test"
    payload = {"discussions": [{"id": 1, "rank": 3}, {"id": 2, "rank": 2}]}
    result = validate_listing(payload, expected_limit=2)
    assert result["count_ok"] and result["unique_ids"] and result["rank_descending"]


def test_export_parser_keeps_thesis_and_continuations():
    text = """Discussion Name:\r\nExample\r\n\r\n1. Thesis:\r\nX should be banned.\r\n\r\n  1.1. Con:\r\n  A counterargument [1]\r\n\r\n  1.2. Pro:\r\n  -> See 1.1.\r\n\r\nSources:\r\n[1] source\r\n"""
    claims, pairs, counters = parse_export(text, "d1", ["topic"])
    assert len(claims) == 2
    assert len(pairs) == 1
    assert set(pairs["label"]) == {"attack"}
    assert counters["citations_removed"] == 1
    assert counters["see_links"] == 1
    assert claims.loc[claims["node_id"] == "1.", "text"].iloc[0] == "X should be banned."
    assert pairs.loc[0, "parent_text"] == "X should be banned."


def sample_data():
    claims = pd.DataFrame([
        {"discussion_id": "d1", "node_id": "1.", "text": "Topic", "depth": 0, "stance": "pro", "tags": ""},
        {"discussion_id": "d1", "node_id": "1.1.", "text": "Good reason", "depth": 1, "stance": "pro", "tags": ""},
        {"discussion_id": "d1", "node_id": "1.2.", "text": "Counter reason", "depth": 1, "stance": "con", "tags": ""},
        {"discussion_id": "d2", "node_id": "1.", "text": "Other topic", "depth": 0, "stance": "pro", "tags": ""},
        {"discussion_id": "d2", "node_id": "1.1.", "text": "Other reason", "depth": 1, "stance": "pro", "tags": ""},
    ])
    pairs = pd.DataFrame([
        {"discussion_id": "d1", "child_id": "1.1.", "parent_id": "1.", "label": "support", "child_text": "Good reason", "parent_text": "Topic"},
        {"discussion_id": "d1", "child_id": "1.2.", "parent_id": "1.", "label": "attack", "child_text": "Counter reason", "parent_text": "Topic"},
        {"discussion_id": "d2", "child_id": "1.1.", "parent_id": "1.", "label": "support", "child_text": "Other reason", "parent_text": "Other topic"},
    ])
    return claims, pairs


def test_debate_split_and_ranking():
    claims, pairs = sample_data()
    split = split_by_discussion(pairs, train_fraction=.5, validation_fraction=0, seed=1)
    assert set(split.train["discussion_id"]).isdisjoint(set(split.test["discussion_id"]))
    candidates = build_candidate_pairs(claims, pairs)
    candidates["score"] = candidates["is_gold"].astype(float)
    metrics = ranking_metrics(candidates)
    assert metrics["hits_at_1"] == 1.0 and metrics["mrr"] == 1.0


def test_classification_metrics():
    result = classification_metrics(["support", "attack"], ["support", "attack"], scores=[.9, .1])
    assert result["accuracy"] == 1.0 and result["macro_f1"] == 1.0


def test_constant_ranking_uses_unbiased_tie_expectation():
    candidates = pd.DataFrame([
        {"discussion_id": "d1", "child_id": "c1", "parent_id": parent,
         "is_gold": parent == "p1", "score": 0.5}
        for parent in ["p1", "p2", "p3", "p4"]
    ])
    metrics = ranking_metrics(candidates)
    assert metrics["hits_at_1"] == 0.25
    assert metrics["hits_at_5"] == 1.0
    assert metrics["mrr"] == pytest.approx((1 + 1 / 2 + 1 / 3 + 1 / 4) / 4)


def test_discovery_model_uses_pair_interactions_and_labels():
    claims, pairs = sample_data()
    discovery = make_discovery_negatives(claims, pairs, seed=2)
    model = TfidfInteractionModel().fit(discovery)
    metrics = evaluate_discovery_binary(model, discovery)
    assert "f1_linked" in metrics and "roc_auc" in metrics
    candidates = build_candidate_pairs(claims, pairs, discussion_ids={"d1"})
    ranked = candidates.copy()
    ranked["score"] = model.predict_proba(ranked)[:, list(model.classifier.classes_).index("linked")]
    assert not ranked.empty


def test_real_parser_targets_when_downloads_are_available():
    targets_path = Path("data/parser_targets.csv")
    listing_path = Path("data/kialo_listing_2026-10-17.json")
    export_dir = Path("data/exports")
    if not (targets_path.exists() and listing_path.exists() and export_dir.exists()):
        pytest.skip("real Kialo exports are not available")
    targets = pd.read_csv(targets_path)
    listing = json.loads(listing_path.read_text(encoding="utf-8"))["discussions"]
    claims, pairs, failures, stats = parse_exports(listing, export_dir)
    per_discussion = claims.groupby("discussion_id").size().rename("parsed").reset_index()
    check = targets.assign(discussion_id=targets["discussion_id"].astype(str)).merge(per_discussion, on="discussion_id", how="left").fillna({"parsed": 0})
    assert failures.empty
    assert (check["api_claimAndThesisCount"] == check["parsed"]).all()
    assert len(claims) == 94707
    assert len(pairs) == 94199
    assert int(stats["see_links"].sum()) == 5504
    assert pairs["label"].value_counts().to_dict() == {"attack": 47642, "support": 46557}
    assert not claims["text"].eq("").any()
    assert not pairs["parent_text"].eq("").any()


def test_discovery_scores_point_to_linked():
    # A perfectly separable toy set: linked pairs share words, not_linked pairs do not.
    # Words must be at least two characters, otherwise TF-IDF drops them (empty vocabulary).
    linked = [
        {"child_text": f"alpha{i} beta{i} gamma", "parent_text": f"alpha{i} beta{i} gamma",
         "relation": "linked"}
        for i in range(10)
    ]
    not_linked = [
        {"child_text": f"delta{i} epsilon{i}", "parent_text": f"omega{i} sigma{i}",
         "relation": "not_linked"}
        for i in range(10)
    ]
    data = pd.DataFrame(linked + not_linked)
    model = TfidfInteractionModel().fit(data)
    metrics = evaluate_discovery_binary(model, data)
    # The score must rank linked pairs above not_linked ones, not the reverse.
    assert metrics["roc_auc"] > 0.5
