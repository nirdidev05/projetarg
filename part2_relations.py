"""Leakage-aware baselines for Kialo relation classification and discovery."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (accuracy_score, average_precision_score, confusion_matrix,
                             f1_score, roc_auc_score)
from sklearn.pipeline import Pipeline


@dataclass
class Split:
    train: pd.DataFrame
    validation: pd.DataFrame
    test: pd.DataFrame
    train_ids: frozenset[str] = frozenset()
    validation_ids: frozenset[str] = frozenset()
    test_ids: frozenset[str] = frozenset()


def make_discussion_split(discussion_ids: Iterable[str], train_fraction: float = .70,
                          validation_fraction: float = .15, seed: int = 42) -> dict[str, frozenset[str]]:
    identifiers = np.array(sorted({str(identifier) for identifier in discussion_ids}))
    generator = np.random.default_rng(seed)
    generator.shuffle(identifiers)
    train_end = int(len(identifiers) * train_fraction)
    validation_end = train_end + int(len(identifiers) * validation_fraction)
    return {
        "train": frozenset(identifiers[:train_end]),
        "validation": frozenset(identifiers[train_end:validation_end]),
        "test": frozenset(identifiers[validation_end:]),
    }


def apply_discussion_split(frame: pd.DataFrame, split_ids: dict[str, frozenset[str]],
                           remove_text_overlap: bool = True) -> Split:
    identifiers = frame["discussion_id"].astype(str)
    train = frame[identifiers.isin(split_ids["train"])].copy()
    validation = frame[identifiers.isin(split_ids["validation"])].copy()
    test = frame[identifiers.isin(split_ids["test"])].copy()
    if remove_text_overlap and not train.empty:
        train_texts = set(train.get("child_text", pd.Series(dtype=str)).fillna("")) | set(train.get("parent_text", pd.Series(dtype=str)).fillna(""))
        if not validation.empty:
            validation = validation[~validation["child_text"].fillna("").isin(train_texts) & ~validation["parent_text"].fillna("").isin(train_texts)]
        if not test.empty:
            test = test[~test["child_text"].fillna("").isin(train_texts) & ~test["parent_text"].fillna("").isin(train_texts)]
    return Split(train, validation, test, split_ids["train"], split_ids["validation"], split_ids["test"])


def split_by_discussion(pairs: pd.DataFrame, train_fraction: float = .70,
                        validation_fraction: float = .15, seed: int = 42,
                        split_ids: dict[str, frozenset[str]] | None = None) -> Split:
    """Split whole debates, never individual pairs, to prevent topic leakage."""
    split_ids = split_ids or make_discussion_split(pairs["discussion_id"], train_fraction, validation_fraction, seed)
    return apply_discussion_split(pairs, split_ids)


def pair_text(frame: pd.DataFrame) -> pd.Series:
    return ("child: " + frame["child_text"].fillna("").astype(str) + " parent: " +
            frame["parent_text"].fillna("").astype(str))


def balanced_pairs(pairs: pd.DataFrame, seed: int = 42) -> pd.DataFrame:
    """Keep one positive/negative pair count when a binary none dataset is supplied."""
    if "relation" not in pairs.columns:
        return pairs.copy()
    counts = pairs["relation"].value_counts()
    if len(counts) < 2:
        return pairs.copy()
    target = counts.min()
    return pd.concat([
        group.sample(target, random_state=seed)
        for _, group in pairs.groupby("relation", sort=False)
    ], ignore_index=True).sample(frac=1, random_state=seed).reset_index(drop=True)


def majority_baseline(train: pd.DataFrame, test: pd.DataFrame, label_column: str = "label") -> dict:
    majority = train[label_column].mode().iloc[0]
    predictions = np.repeat(majority, len(test))
    return classification_metrics(test[label_column], predictions, model="B0 majority")


def train_tfidf(train: pd.DataFrame, label_column: str = "label") -> Pipeline:
    model = Pipeline([
        ("tfidf", TfidfVectorizer(ngram_range=(1, 2), min_df=1, sublinear_tf=True)),
        ("classifier", LogisticRegression(max_iter=1000, class_weight="balanced", random_state=42)),
    ])
    model.fit(pair_text(train), train[label_column])
    return model


def classification_metrics(labels: Iterable[str], predictions: Iterable[str], model: str = "model",
                            scores: Iterable[float] | None = None, label_order: Iterable[str] | None = None,
                            positive_label: str | None = None) -> dict:
    labels = list(labels)
    predictions = list(predictions)
    order = list(label_order or sorted(set(labels) | set(predictions)))
    result = {
        "model": model,
        "accuracy": accuracy_score(labels, predictions),
        "macro_f1": f1_score(labels, predictions, average="macro", zero_division=0),
        "confusion_matrix": confusion_matrix(labels, predictions, labels=order).tolist(),
    }
    for label in order:
        result[f"f1_{label}"] = f1_score(labels, predictions, labels=[label], average="macro", zero_division=0)
    if scores is not None and len(order) == 2:
        positive = positive_label or order[1]
        binary_labels = [1 if label == positive else 0 for label in labels]
        result["roc_auc"] = roc_auc_score(binary_labels, list(scores))
        result["pr_auc"] = average_precision_score(binary_labels, list(scores))
    return result


def evaluate_tfidf(model: Pipeline, test: pd.DataFrame, label_column: str = "label") -> dict:
    predictions = model.predict(pair_text(test))
    order = list(model.classes_)
    scores = model.predict_proba(pair_text(test))[:, order.index("support")] if len(order) == 2 else None
    return classification_metrics(test[label_column], predictions, model="B1 TF-IDF + logistic regression", scores=scores, label_order=order, positive_label="support")


class SentenceEmbeddingPairModel:
    """Frozen Sentence-BERT pair features followed by logistic regression (B2)."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise ImportError("Install sentence-transformers to use B2") from exc
        self.encoder = SentenceTransformer(model_name)
        self.classifier = LogisticRegression(max_iter=1000, class_weight="balanced", random_state=42)

    def _features(self, frame: pd.DataFrame) -> np.ndarray:
        child_vectors = self.encoder.encode(frame["child_text"].fillna("").tolist(), show_progress_bar=False)
        parent_vectors = self.encoder.encode(frame["parent_text"].fillna("").tolist(), show_progress_bar=False)
        return np.hstack([child_vectors, parent_vectors,
                          np.abs(child_vectors - parent_vectors), child_vectors * parent_vectors])

    def fit(self, frame: pd.DataFrame, label_column: str = "label"):
        self.classifier.fit(self._features(frame), frame[label_column])
        return self

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        return self.classifier.predict(self._features(frame))

    def predict_proba(self, frame: pd.DataFrame) -> np.ndarray:
        return self.classifier.predict_proba(self._features(frame))


def evaluate_sentence_embeddings(model: SentenceEmbeddingPairModel, test: pd.DataFrame,
                                 label_column: str = "label") -> dict:
    predictions = model.predict(test)
    probabilities = model.predict_proba(test)
    scores = probabilities[:, list(model.classifier.classes_).index("support")]
    return classification_metrics(test[label_column], predictions, model="B2 frozen Sentence-BERT + logistic regression", scores=scores)


class TfidfInteractionModel:
    """Sparse lexical interaction baseline for pair-specific discovery scores."""

    def __init__(self):
        self.vectorizer = TfidfVectorizer(ngram_range=(1, 2), min_df=1, sublinear_tf=True)
        self.classifier = LogisticRegression(max_iter=1000, class_weight="balanced", random_state=42)

    def _features(self, frame: pd.DataFrame, fit: bool = False) -> np.ndarray:
        texts = pd.concat([frame["child_text"].fillna(""), frame["parent_text"].fillna("")], ignore_index=True)
        vectors = self.vectorizer.fit_transform(texts) if fit else self.vectorizer.transform(texts)
        half = len(frame)
        child = vectors[:half]
        parent = vectors[half:]
        dot = np.asarray(child.multiply(parent).sum(axis=1)).ravel()
        child_norm = np.sqrt(np.asarray(child.multiply(child).sum(axis=1)).ravel())
        parent_norm = np.sqrt(np.asarray(parent.multiply(parent).sum(axis=1)).ravel())
        cosine = dot / np.maximum(child_norm * parent_norm, 1e-12)
        child_tokens = frame["child_text"].fillna("").str.lower().str.split()
        parent_tokens = frame["parent_text"].fillna("").str.lower().str.split()
        overlap = np.array([
            len(set(left) & set(right)) / max(1, len(set(left) | set(right)))
            for left, right in zip(child_tokens, parent_tokens)
        ])
        lengths = np.array([
            [len(left), len(right), abs(len(left) - len(right))]
            for left, right in zip(child_tokens, parent_tokens)
        ])
        return np.column_stack([cosine, overlap, lengths])

    def fit(self, frame: pd.DataFrame, label_column: str = "relation"):
        self.classifier.fit(self._features(frame, fit=True), frame[label_column])
        return self

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        return self.classifier.predict(self._features(frame))

    def predict_proba(self, frame: pd.DataFrame) -> np.ndarray:
        return self.classifier.predict_proba(self._features(frame))


def evaluate_discovery_binary(model: TfidfInteractionModel, test: pd.DataFrame) -> dict:
    predictions = model.predict(test)
    order = list(model.classifier.classes_)
    scores = model.predict_proba(test)[:, order.index("linked")] if len(order) == 2 else None
    return classification_metrics(test["relation"], predictions, model="B1 interaction discovery", scores=scores, label_order=order, positive_label="linked")


def make_discovery_negatives(claims: pd.DataFrame, positive_pairs: pd.DataFrame,
                             seed: int = 42) -> pd.DataFrame:
    """Build linked/non-linked pairs at the three protocol difficulty levels."""
    rng = np.random.default_rng(seed)
    positives = positive_pairs[["discussion_id", "child_id", "parent_id", "child_text", "parent_text"]].copy()
    claim_lookup = claims.set_index(["discussion_id", "node_id"])["text"].to_dict()
    if "parent_id" in claims.columns:
        parent_lookup = claims.set_index(["discussion_id", "node_id"])["parent_id"].to_dict()
    else:
        parent_lookup = positive_pairs.set_index(["discussion_id", "child_id"])["parent_id"].to_dict()
    working_claims = claims.copy()
    if "parent_id" not in working_claims.columns:
        working_claims["parent_id"] = [parent_lookup.get((row.discussion_id, row.node_id)) for row in working_claims.itertuples()]
    positives["context_text"] = [
        claim_lookup.get((discussion_id, parent_lookup.get((discussion_id, parent_id))), "")
        for discussion_id, parent_id in zip(positives["discussion_id"], positives["parent_id"])
    ]
    positives["relation"] = "linked"
    positives["difficulty"] = "positive"
    positive_keys = set(zip(positives["discussion_id"], positives["child_id"], positives["parent_id"]))
    negative_rows = []
    for child in working_claims.itertuples():
        same_debate = working_claims[working_claims["discussion_id"].eq(child.discussion_id) & working_claims["node_id"].ne(child.node_id)]
        same_debate = same_debate[~same_debate["node_id"].map(lambda value: (child.discussion_id, child.node_id, value) in positive_keys)]
        parent_id = parent_lookup.get((child.discussion_id, child.node_id))
        parent_parent = parent_lookup.get((child.discussion_id, parent_id))
        candidate_groups = {
            "same_debate": same_debate[same_debate["parent_id"].notna() & ~same_debate["node_id"].isin([parent_id, parent_parent])],
            "local": same_debate[(same_debate["parent_id"] == parent_id) | (same_debate["parent_id"] == child.node_id) | (same_debate["node_id"] == parent_parent)],
        }
        other_debate = working_claims[~working_claims["discussion_id"].eq(child.discussion_id)]
        candidate_groups["cross_debate"] = other_debate
        for difficulty, candidates in candidate_groups.items():
            if candidates.empty:
                continue
            candidate = candidates.iloc[int(rng.integers(len(candidates)))]
            negative_rows.append({
                "discussion_id": child.discussion_id, "child_id": child.node_id,
                "parent_id": candidate["node_id"], "child_text": child.text,
                "parent_text": candidate["text"], "relation": "not_linked",
                "context_text": claim_lookup.get((child.discussion_id, parent_lookup.get((child.discussion_id, candidate["node_id"]))), ""),
                "difficulty": difficulty,
            })
    return pd.concat([positives, pd.DataFrame(negative_rows)], ignore_index=True)


class ContextTfidfInteractionModel(TfidfInteractionModel):
    """GraphNLI-inspired extension with the parent's parent as context."""

    def _features(self, frame: pd.DataFrame, fit: bool = False) -> np.ndarray:
        base = super()._features(frame, fit=fit)
        context = frame.get("context_text", pd.Series("", index=frame.index)).fillna("")
        child = frame["child_text"].fillna("").str.lower().str.split()
        context_tokens = context.str.lower().str.split()
        context_overlap = np.array([
            len(set(left) & set(right)) / max(1, len(set(left) | set(right)))
            for left, right in zip(child, context_tokens)
        ])
        return np.column_stack([base, context_overlap, context.str.len().to_numpy()])


def rank_candidates(model: Any, candidates: pd.DataFrame) -> pd.DataFrame:
    """Rank parent candidates per child using the classifier's support score."""
    ranked = candidates.copy()
    if isinstance(model, TfidfInteractionModel):
        ranked["score"] = model.predict_proba(ranked)[:, list(model.classifier.classes_).index("linked")]
    else:
        classes = list(model.classes_)
        ranked["score"] = model.predict_proba(pair_text(ranked))[:, classes.index("support")]
    return ranked.sort_values(["discussion_id", "child_id", "score"], ascending=[True, True, False])


def ranking_metrics(ranked: pd.DataFrame, child_column: str = "child_id", parent_column: str = "parent_id") -> dict:
    reciprocal_ranks, hits_at_1, hits_at_5, candidate_counts = [], [], [], []
    for _, group in ranked.groupby(["discussion_id", child_column], sort=False):
        ordered = group.sort_values("score", ascending=False, kind="mergesort").reset_index(drop=True)
        gold = ordered.loc[ordered["is_gold"].astype(bool), parent_column].astype(str).tolist()
        if not gold:
            continue
        true_parent = gold[0]
        true_score = ordered.loc[ordered[parent_column].astype(str).eq(true_parent), "score"].iloc[0]
        greater = int((ordered["score"] > true_score).sum())
        ties = int(((ordered["score"] == true_score) & ~ordered[parent_column].astype(str).eq(true_parent)).sum())
        hits_at_1.append(0.0 if 1 <= greater else min(1.0, (1 - greater) / (ties + 1)))
        hits_at_5.append(0.0 if 5 <= greater else min(1.0, (5 - greater) / (ties + 1)))
        reciprocal_ranks.append(sum(1 / (greater + 1 + offset) for offset in range(ties + 1)) / (ties + 1))
        candidate_counts.append(len(ordered))
    return {
        "groups": len(reciprocal_ranks),
        "mean_candidates": float(np.mean(candidate_counts)) if candidate_counts else 0.0,
        "hits_at_1": float(np.mean(hits_at_1)) if hits_at_1 else 0.0,
        "hits_at_5": float(np.mean(hits_at_5)) if hits_at_5 else 0.0,
        "mrr": float(np.mean(reciprocal_ranks)) if reciprocal_ranks else 0.0,
    }


def build_candidate_pairs(claims: pd.DataFrame, positive_pairs: pd.DataFrame,
                          discussion_ids: Iterable[str] | None = None) -> pd.DataFrame:
    """Create candidates only for requested debates, rather than materializing all debates."""
    claim_lookup = claims.set_index(["discussion_id", "node_id"])["text"].to_dict()
    if "parent_id" in claims.columns:
        parent_lookup = claims.set_index(["discussion_id", "node_id"])["parent_id"].to_dict()
    else:
        parent_lookup = positive_pairs.set_index(["discussion_id", "child_id"])["parent_id"].to_dict()
    positive_keys = set(zip(positive_pairs["discussion_id"], positive_pairs["child_id"], positive_pairs["parent_id"]))
    rows = []
    allowed = set(str(value) for value in discussion_ids) if discussion_ids is not None else set(claims["discussion_id"].astype(str).unique())
    scoped_claims = claims[claims["discussion_id"].astype(str).isin(allowed)]
    for (discussion_id, child_id), child_group in scoped_claims.groupby(["discussion_id", "node_id"]):
        child_text = child_group.iloc[0]["text"]
        candidates = scoped_claims[scoped_claims["discussion_id"].eq(discussion_id) & scoped_claims["node_id"].ne(child_id)]
        for candidate in candidates.itertuples():
            key = (discussion_id, child_id, candidate.node_id)
            rows.append({
                "discussion_id": discussion_id,
                "child_id": child_id,
                "parent_id": candidate.node_id,
                "child_text": child_text,
                "parent_text": claim_lookup[(discussion_id, candidate.node_id)],
                "context_text": claim_lookup.get((discussion_id, parent_lookup.get((discussion_id, candidate.node_id))), ""),
                "is_gold": key in positive_keys,
            })
    return pd.DataFrame(rows)