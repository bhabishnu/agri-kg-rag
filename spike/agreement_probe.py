"""
spike/agreement_probe.py — feasibility probe for cross-source fact agreement.

Standalone. Does NOT import the project; it only reuses the same embedding
model the project uses (sentence-transformers/all-MiniLM-L6-v2) so the numbers
are comparable.

Question it answers: if two independent sources (ICAR and TNAU) describe the
SAME agronomic fact, are their texts measurably closer in embedding space than
an ICAR text is to some UNRELATED TNAU fact? If yes, an "Agreement" signal built
on embedding similarity is viable.

Layout expected in this folder:
    {fact}_icar.txt   and   {fact}_tnau.txt
e.g. rice_nitrogen_icar.txt / rice_nitrogen_tnau.txt

Run:
    python spike/agreement_probe.py
"""

import os
import glob

import numpy as np

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
SOURCES = ("icar", "tnau")
HERE = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# Discover {fact}_{source}.txt files and pair them up by fact name.
# ---------------------------------------------------------------------------
def discover_pairs():
    """Return (pairs, skipped).

    pairs   = {fact: {"icar": text, "tnau": text}}  only facts with BOTH sides
    skipped = {fact: [present_source, ...]}          facts missing a side
    """
    found = {}  # fact -> {source: text}
    for path in sorted(glob.glob(os.path.join(HERE, "*.txt"))):
        stem = os.path.splitext(os.path.basename(path))[0]
        # split off the trailing _icar / _tnau; the rest is the fact name
        source = None
        for src in SOURCES:
            if stem.endswith("_" + src):
                source = src
                fact = stem[: -(len(src) + 1)]
                break
        if source is None:
            continue  # not a probe file, ignore
        with open(path, "r", encoding="utf-8") as f:
            text = f.read().strip()
        found.setdefault(fact, {})[source] = text

    pairs, skipped = {}, {}
    for fact, bysrc in sorted(found.items()):
        if all(src in bysrc and bysrc[src] for src in SOURCES):
            pairs[fact] = bysrc
        else:
            skipped[fact] = sorted(bysrc.keys())
    return pairs, skipped


# ---------------------------------------------------------------------------
# Embedding + cosine helpers
# ---------------------------------------------------------------------------
def embed(texts):
    """Encode texts to L2-normalized vectors so cosine == dot product."""
    from sentence_transformers import SentenceTransformer

    print(f"  (loading {MODEL_NAME} — first run downloads it)")
    model = SentenceTransformer(MODEL_NAME)
    vecs = model.encode(list(texts), show_progress_bar=False)
    vecs = np.asarray(vecs, dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return vecs / norms


# ---------------------------------------------------------------------------
# Main probe
# ---------------------------------------------------------------------------
def main():
    pairs, skipped = discover_pairs()

    for fact, present in skipped.items():
        print(f"[skip] '{fact}': only have {present}, need both {list(SOURCES)}")

    if not pairs:
        print(
            "\nNo complete {fact}_icar.txt / {fact}_tnau.txt pairs found in "
            f"{HERE}.\nAdd some files (e.g. rice_nitrogen_icar.txt and "
            "rice_nitrogen_tnau.txt) and re-run."
        )
        return

    facts = list(pairs.keys())

    # Embed everything in one batch, keep index maps back to (fact, source).
    texts, index = [], []
    for fact in facts:
        for src in SOURCES:
            index.append((fact, src))
            texts.append(pairs[fact][src])
    vecs = embed(texts)
    vec_of = {key: vecs[i] for i, key in enumerate(index)}

    icar = {f: vec_of[(f, "icar")] for f in facts}
    tnau = {f: vec_of[(f, "tnau")] for f in facts}

    # --- Matched similarities: icar_f vs tnau_f -----------------------------
    matched = {f: float(np.dot(icar[f], tnau[f])) for f in facts}

    # --- Mismatched baseline: icar_f vs tnau_other --------------------------
    mismatched_vals = []
    for f in facts:
        for g in facts:
            if g == f:
                continue
            mismatched_vals.append(float(np.dot(icar[f], tnau[g])))

    # --- Top-1 retrieval: nearest tnau neighbour of each icar text ----------
    retrieval = {}
    for f in facts:
        sims = {g: float(np.dot(icar[f], tnau[g])) for g in facts}
        best = max(sims, key=sims.get)
        retrieval[f] = (best, best == f, sims[best], matched[f])

    # --- Report -------------------------------------------------------------
    width = max(len(f) for f in facts)

    print("\n" + "=" * 60)
    print("MATCHED PAIRS  (icar vs its own tnau)")
    print("=" * 60)
    print(f"{'fact'.ljust(width)}   cos_sim")
    print(f"{'-' * width}   -------")
    for f in facts:
        print(f"{f.ljust(width)}   {matched[f]:.4f}")

    avg_matched = sum(matched.values()) / len(matched)
    avg_mismatched = (
        sum(mismatched_vals) / len(mismatched_vals) if mismatched_vals else float("nan")
    )
    gap = avg_matched - avg_mismatched

    print("\n" + "=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"avg matched similarity      : {avg_matched:.4f}")
    if mismatched_vals:
        print(f"avg mismatched similarity   : {avg_mismatched:.4f}   "
              f"(control, {len(mismatched_vals)} cross pairs)")
        print(f"GAP (matched - mismatched)  : {gap:+.4f}")
    else:
        print("avg mismatched similarity   : n/a (need >=2 facts for a control)")

    print("\n" + "=" * 60)
    print("TOP-1 RETRIEVAL  (nearest tnau neighbour of each icar text)")
    print("=" * 60)
    print(f"{'fact'.ljust(width)}   hit?  nearest_tnau{' ' * max(0, width - 12)}  sim")
    print(f"{'-' * width}   ----  {'-' * max(12, width)}  -----")
    hits = 0
    for f in facts:
        best, ok, best_sim, _ = retrieval[f]
        hits += int(ok)
        mark = "OK " if ok else "MISS"
        print(f"{f.ljust(width)}   {mark}  {best.ljust(max(12, width))}  {best_sim:.4f}")

    print(f"\ntop-1 accuracy: {hits}/{len(facts)} = {hits / len(facts):.0%}")

    verdict = "VIABLE" if gap > 0.10 and hits == len(facts) else "WEAK / inconclusive"
    print(f"\nverdict: agreement-by-embedding looks {verdict} on this sample.")


if __name__ == "__main__":
    main()
