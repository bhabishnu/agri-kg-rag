"""
Verification scoring — the "is this retrieved fact trustworthy?" layer.

This implements the project's core verification score:

    S(f) = w1*Agreement + w2*Reliability + w3*Recency + w4*Confidence

Each term is a number in [0, 1]; the weighted sum is also in [0, 1] because the
weights are normalized to sum to 1. `verification_score` returns both the final
score AND a per-term breakdown (raw value + weighted contribution) so callers
can show *why* a chunk scored the way it did.

Which terms use REAL data vs a placeholder:

    reliability  REAL  — metadata["reliability"], attached at ingestion from
                         config.SOURCES (see ingest.py). Higher = more trusted.
    recency      REAL  — metadata["ingested_at"] (ISO timestamp), decayed with a
                         half-life. Older data scores lower.
    confidence   REAL  — derived from the Chroma vector distance for this chunk.
                         Closer match = higher confidence.
    agreement    PLACEHOLDER — fixed at 0.5. Real agreement needs a SECOND
                         independent source corroborating the fact; we don't
                         have cross-source lookup yet, so we do NOT fabricate it.
"""

from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# Weights for S(f) = w1*Agreement + w2*Reliability + w3*Recency + w4*Confidence
# Tune these freely — they are normalized below so they need not sum to 1.
# ---------------------------------------------------------------------------
W_AGREEMENT = 0.15      # w1
W_RELIABILITY = 0.35    # w2
W_RECENCY = 0.20        # w3
W_CONFIDENCE = 0.30     # w4

_WEIGHT_SUM = W_AGREEMENT + W_RELIABILITY + W_RECENCY + W_CONFIDENCE

# Normalized weights (sum to exactly 1.0), so the final score stays in [0, 1]
# regardless of how the raw weights above are tuned.
NW_AGREEMENT = W_AGREEMENT / _WEIGHT_SUM
NW_RELIABILITY = W_RELIABILITY / _WEIGHT_SUM
NW_RECENCY = W_RECENCY / _WEIGHT_SUM
NW_CONFIDENCE = W_CONFIDENCE / _WEIGHT_SUM

# ---------------------------------------------------------------------------
# Recency decay: score = 0.5 ** (age_days / HALF_LIFE_DAYS).
# A fact scores 1.0 the instant it is ingested, 0.5 after one half-life,
# 0.25 after two, and so on. 365 days = "a year-old fact is worth half".
# ---------------------------------------------------------------------------
HALF_LIFE_DAYS = 365

# Neutral fallback used when a term's input data is missing/unusable, so a
# gap degrades gracefully to "no opinion" rather than crashing or scoring 0.
_NEUTRAL = 0.5


def _clamp01(x):
    """Clamp a number into [0, 1]."""
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def reliability_term(metadata):
    """REAL. Source trust weight, attached at ingestion (already in [0, 1])."""
    val = metadata.get("reliability")
    if val is None:
        return _NEUTRAL
    try:
        return _clamp01(float(val))
    except (TypeError, ValueError):
        return _NEUTRAL


def recency_term(metadata, now=None):
    """REAL. Exponential decay of metadata["ingested_at"] with HALF_LIFE_DAYS.

    Missing or unparseable timestamps fall back to a neutral 0.5 rather than
    penalizing the fact for a data-plumbing gap.
    """
    raw = metadata.get("ingested_at")
    if not raw:
        return _NEUTRAL
    try:
        ts = datetime.fromisoformat(raw)
    except (TypeError, ValueError):
        return _NEUTRAL

    now = now or datetime.now(timezone.utc)
    # A naive stored timestamp is assumed to be UTC so the subtraction works.
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)

    age_days = (now - ts).total_seconds() / 86400.0
    if age_days <= 0:
        # Just-ingested (or minor clock skew putting it slightly in the future).
        return 1.0
    return _clamp01(0.5 ** (age_days / HALF_LIFE_DAYS))


def confidence_term(distance):
    """REAL. Vector-match confidence from the Chroma distance (lower = better).

    1 / (1 + distance): distance 0 -> 1.0, growing distance -> toward 0.
    A missing/non-numeric distance falls back to neutral 0.5.
    """
    if not isinstance(distance, (int, float)):
        return _NEUTRAL
    if distance < 0:
        distance = 0.0
    return _clamp01(1.0 / (1.0 + distance))


def agreement_term(metadata):
    """PLACEHOLDER. Neutral 0.5 — we do NOT fabricate cross-source agreement.

    Real agreement requires a SECOND independent source corroborating this
    fact (e.g. cross-checking an Agmarknet price against another price feed,
    or an ICAR advisory against TNAU guidance). That lookup does not exist
    yet, so returning anything but a neutral value here would be inventing
    evidence.
    """
    # TODO: requires a second independent source — see TNAU spike.
    return _NEUTRAL


def verification_score(metadata, distance):
    """Compute S(f) for one retrieved chunk.

    Args:
        metadata: the chunk's stored metadata dict (source, reliability,
                  ingested_at, type, ...).
        distance: the Chroma vector distance for this chunk (lower = closer).

    Returns:
        (score, breakdown) where `score` is the final weighted value in [0, 1]
        and `breakdown` maps each term name -> {"raw", "weight", "contribution"},
        plus "score". `raw` is the term's value in [0, 1]; `contribution` is
        raw * normalized_weight (the terms' contributions sum to `score`).
    """
    metadata = metadata or {}

    terms = {
        # name: (raw_value, normalized_weight, is_real)
        "agreement": (agreement_term(metadata), NW_AGREEMENT, False),
        "reliability": (reliability_term(metadata), NW_RELIABILITY, True),
        "recency": (recency_term(metadata), NW_RECENCY, True),
        "confidence": (confidence_term(distance), NW_CONFIDENCE, True),
    }

    breakdown = {}
    score = 0.0
    for name, (raw, weight, is_real) in terms.items():
        contribution = raw * weight
        score += contribution
        breakdown[name] = {
            "raw": raw,
            "weight": weight,
            "contribution": contribution,
            "real": is_real,        # False => placeholder, not real evidence
        }

    breakdown["score"] = score
    return score, breakdown
