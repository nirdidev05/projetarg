"""Collection, parsing, and exploration helpers for Part 2.

The collector is intentionally explicit: it saves the raw listing, validates
every export, and records failures instead of silently dropping discussions.
"""
from __future__ import annotations

import json
import re
import time
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import requests

API_URL = "https://www.kialo.com/api/v1/discussions"
EXPORT_URL = "https://www.kialo.com/export/{slug}-{discussion_id}.txt"
REFERENCE_URL = "https://github.com/4mbroise/ADC"


@dataclass
class ExportResult:
    discussion_id: str
    path: Path | None
    ok: bool
    error: str = ""


def discussion_listing(limit: int = 250, skip: int = 0, session: requests.Session | None = None) -> dict[str, Any]:
    """Fetch the ranked/activity-sorted discussion listing from Kialo."""
    client = session or requests.Session()
    response = client.get(API_URL, params={
        "filter": "tag",
        "sort": "rank_and_latest_activity",
        "limit": limit,
        "skip": skip,
    }, timeout=30)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload.get("discussions"), list):
        raise ValueError("Kialo response does not contain a discussions list")
    return payload


def validate_listing(payload: dict[str, Any], expected_limit: int = 250) -> dict[str, Any]:
    discussions = payload.get("discussions", [])
    identifiers = [str(item.get("id")) for item in discussions]
    ranks = [item.get("rank") for item in discussions if item.get("rank") is not None]
    return {
        "count": len(discussions),
        "expected_count": expected_limit,
        "count_ok": len(discussions) == expected_limit,
        "unique_ids": len(identifiers) == len(set(identifiers)),
        "rank_descending": all(left >= right for left, right in zip(ranks, ranks[1:])),
        "languages": Counter(item.get("language", "unknown") for item in discussions),
    }


def save_listing(payload: dict[str, Any], path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return destination


def slugify(title: str) -> str:
    """Build the reference export slug while normalising Unicode safely."""
    normalized = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    normalized = normalized.lower().replace("?", "").replace("'", "")
    normalized = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return normalized


def export_url(discussion: dict[str, Any]) -> str:
    return EXPORT_URL.format(slug=slugify(str(discussion.get("title", "discussion"))),
                             discussion_id=discussion["id"])


def validate_export(path: str | Path) -> tuple[bool, str]:
    candidate = Path(path)
    if not candidate.exists():
        return False, "file does not exist"
    if candidate.stat().st_size == 0:
        return False, "file is empty"
    first_line = candidate.read_text(encoding="utf-8", errors="replace").splitlines()[0]
    header = first_line.rstrip(":").strip().lower()
    if header not in {"discussion name", "discussion title", "nombre del debate",
                      "diskussionsname", "nom du débat", "nom du debat"}:
        return False, "first line is not a supported discussion header"
    return True, ""


def download_exports(discussions: Iterable[dict[str, Any]], output_dir: str | Path,
                     delay_seconds: float = 1.5, session: requests.Session | None = None) -> list[ExportResult]:
    """Download official text exports with a caller-provided authenticated session.

    Kialo exports require login. Authentication is intentionally not automated
    here: create the session through the official browser flow and pass it in.
    """
    if session is None:
        raise ValueError("An authenticated requests.Session is required for Kialo exports")
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    client = session
    results = []
    for discussion in discussions:
        discussion_id = str(discussion["id"])
        output_path = destination / f"{discussion_id}.txt"
        try:
            response = client.get(export_url(discussion), timeout=60)
            response.raise_for_status()
            output_path.write_bytes(response.content)
            valid, error = validate_export(output_path)
            if not valid:
                results.append(ExportResult(discussion_id, output_path, False, error))
                continue
            results.append(ExportResult(discussion_id, output_path, True))
        except Exception as exc:  # record the failure; never silently skip it
            results.append(ExportResult(discussion_id, None, False, str(exc)))
        time.sleep(delay_seconds)
    return results


NODE_LINE = re.compile(r"^\s*(?P<node>\d+(?:\.\d+)*\.)\s+(?P<label>[^:]+):\s*$", re.I)
SEE_LINK = re.compile(r"^\s*->\s*(?:See|Siehe|Voir|Ver|Véase)\s+(?P<node>\d+(?:\.\d+)*\.)\s*$", re.I)
CITATION = re.compile(r"\s*\[\d+\]")
DISCUSSION_LINK = re.compile(r"^\s*->\s*See\s+discussion\s+#(?P<discussion_id>\d+):\s*", re.I)
SOURCE_HEADER = re.compile(r"^\s*[^\d\s].*:\s*$")
LABELS = {
    "pro": "pro", "pour": "pro",
    "con": "con", "contra": "con", "contre": "con",
    "thesis": "thesis", "these": "thesis", "tesis": "thesis", "thèse": "thesis", "these": "thesis",
    "question": "question", "frage": "question",
}


def _parent_id(node_id: str) -> str | None:
    parts = node_id.rstrip(".").split(".")
    return None if len(parts) <= 1 else ".".join(parts[:-1]) + "."


def _depth(node_id: str) -> int:
    return max(0, len(node_id.rstrip(".").split(".")) - 1)


def _clean_citations(value: str) -> str:
    previous = None
    cleaned = value
    while cleaned != previous:
        previous = cleaned
        cleaned = CITATION.sub("", cleaned).strip()
    return cleaned


def parse_export(text: str, discussion_id: str, tags: list[str] | None = None) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, int]]:
    """Parse the two-line, localized-label Kialo export format."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    title = lines[1].strip() if len(lines) > 1 else ""
    records: dict[str, dict[str, Any]] = {}
    current: dict[str, Any] | None = None
    counters = Counter({"citations_removed": 0, "see_links": 0, "source_lines": 0})
    source_mode = False

    def finish_current() -> None:
        nonlocal current
        if current is None:
            return
        text_value = _clean_citations(" ".join(current.pop("text_lines")))
        external_link = DISCUSSION_LINK.match(text_value)
        if external_link:
            current["external_discussion_id"] = external_link.group("discussion_id")
            text_value = _clean_citations(text_value[external_link.end():])
        current["text"] = text_value
        if text_value and not SEE_LINK.fullmatch(text_value):
            records[current["node_id"]] = current
        current = None

    for index, raw_line in enumerate(lines):
        line = raw_line.strip()
        next_line = lines[index + 1].strip() if index + 1 < len(lines) else ""
        if source_mode:
            continue
        if not line:
            finish_current()
            continue
        if SOURCE_HEADER.match(line) and re.match(r"^\[\d+\]", next_line):
            finish_current()
            counters["source_lines"] += 1
            source_mode = True
            continue
        match = NODE_LINE.match(raw_line)
        if match:
            finish_current()
            node_id = match.group("node")
            label = LABELS.get(match.group("label").strip().lower(), match.group("label").strip().lower())
            current = {
                "discussion_id": str(discussion_id),
                "node_id": node_id,
                "parent_id": _parent_id(node_id),
                "depth": _depth(node_id),
                "stance": label,
                "title": title,
                "tags": ";".join(tags or []),
                "external_discussion_id": "",
                "text_lines": [],
            }
            continue
        if current:
            if SEE_LINK.fullmatch(line):
                counters["see_links"] += 1
                current["text_lines"] = [line]
            else:
                counters["citations_removed"] += len(CITATION.findall(line))
                current["text_lines"].append(line)
    finish_current()
    claims = pd.DataFrame(records.values(), columns=[
        "discussion_id", "node_id", "parent_id", "depth", "stance", "text", "title", "tags", "external_discussion_id"
    ])
    if claims.empty:
        pairs = pd.DataFrame(columns=["discussion_id", "child_id", "parent_id", "label", "depth"])
    else:
        discussion_claims = claims[claims["discussion_id"].eq(str(discussion_id))]
        text_by_node = discussion_claims.set_index("node_id")["text"].to_dict()
        pair_rows = []
        for row in claims.itertuples():
            if pd.notna(row.parent_id) and row.stance in {"pro", "con"} and row.node_id in text_by_node:
                pair_rows.append({
                    "discussion_id": row.discussion_id,
                    "child_id": row.node_id,
                    "parent_id": row.parent_id,
                    "label": "support" if row.stance == "pro" else "attack",
                    "depth": row.depth,
                    "child_text": row.text,
                    "parent_text": text_by_node.get(row.parent_id, ""),
                })
        pairs = pd.DataFrame(pair_rows)
    return claims, pairs, dict(counters)


def parse_exports(listing: list[dict[str, Any]], export_dir: str | Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    claims_frames, pair_frames, failures = [], [], []
    stats = []
    for discussion in listing:
        path = Path(export_dir) / f"{discussion['id']}.txt"
        valid, error = validate_export(path)
        if not valid:
            failures.append({"discussion_id": str(discussion["id"]), "error": error})
            continue
        claims, pairs, counters = parse_export(path.read_text(encoding="utf-8", errors="replace"), str(discussion["id"]), discussion.get("tags", []))
        claims_frames.append(claims)
        pair_frames.append(pairs)
        stats.append({"discussion_id": str(discussion["id"]), **counters})
    return (
        pd.concat(claims_frames, ignore_index=True) if claims_frames else pd.DataFrame(),
        pd.concat(pair_frames, ignore_index=True) if pair_frames else pd.DataFrame(),
        pd.DataFrame(failures),
        pd.DataFrame(stats),
    )


def exploration_summary(claims: pd.DataFrame, pairs: pd.DataFrame, listing: pd.DataFrame | None = None) -> dict[str, pd.DataFrame]:
    """Return the tables required by the protocol's exploration checklist."""
    by_discussion = claims.groupby("discussion_id").agg(
        claims=("node_id", "nunique"), max_depth=("depth", "max"), mean_depth=("depth", "mean"),
        mean_chars=("text", lambda values: values.str.len().mean()),
    ).reset_index() if not claims.empty else pd.DataFrame()
    by_depth = claims.groupby(["depth", "stance"]).size().rename("count").reset_index() if not claims.empty else pd.DataFrame()
    labels = pairs["label"].value_counts(normalize=True).rename("proportion").reset_index() if not pairs.empty else pd.DataFrame()
    tags = claims.assign(tag=claims["tags"].fillna("").str.split(";")).explode("tag")
    top_tags = tags.loc[tags["tag"].ne("")].drop_duplicates(["discussion_id", "tag"]).groupby("tag").size().sort_values(ascending=False).head(20).rename("discussion_count").reset_index()
    text_lengths = claims.assign(token_count=claims["text"].fillna("").str.split().str.len()).groupby("discussion_id")["token_count"].agg(["mean", "median", "max"]).reset_index()
    duplicate_texts = claims.assign(normalized_text=claims["text"].fillna("").str.lower().str.replace(r"\s+", " ", regex=True).str.strip()).groupby("normalized_text")["discussion_id"].nunique()
    duplicate_summary = pd.DataFrame({"texts_in_multiple_discussions": [int((duplicate_texts > 1).sum())]})
    result = {"by_discussion": by_discussion, "by_depth": by_depth, "labels": labels, "top_tags": top_tags, "text_lengths": text_lengths, "duplicate_summary": duplicate_summary}
    if listing is not None and not listing.empty and "id" in listing:
        activity_columns = [column for column in ["participantCount", "viewCount", "voteCount"] if column in listing]
        meta = listing.rename(columns={"id": "discussion_id"})
        meta["discussion_id"] = meta["discussion_id"].astype(str)
        by_discussion["discussion_id"] = by_discussion["discussion_id"].astype(str)
        result["listing_language"] = meta["language"].value_counts(dropna=False).rename("discussion_count").reset_index() if "language" in meta else pd.DataFrame()
        merged = by_discussion.merge(meta[["discussion_id", *activity_columns]], on="discussion_id", how="left")
        result["activity_spearman"] = merged[["claims", *activity_columns]].corr(method="spearman").reset_index() if activity_columns else pd.DataFrame()
        if "claimAndThesisCount" in meta:
            result["api_count_check"] = by_discussion.merge(meta[["discussion_id", "claimAndThesisCount"]], on="discussion_id", how="left").assign(delta=lambda frame: frame["claims"] - frame["claimAndThesisCount"])
    return result