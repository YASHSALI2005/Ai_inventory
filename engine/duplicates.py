"""
Duplicate material detection — the Alcoa/Alba problem.

Two masters describing the same physical part, entered by different people at
different times, so the consumption history splits across both and neither line
looks anomalous on its own.

Shape of the solution, which is the standard one for MRO master data:

1. **Normalise.** Uppercase, strip punctuation, expand an abbreviation dictionary,
   drop the noise suffixes people add when superseding a record. A matcher without
   an abbreviation table cannot see that BRG and BEARING are the same word, and
   every MDM product ships one — PiLog's is part of what Ma'aden already licenses.

2. **Block.** Comparing 20,000 masters pairwise is 200 million comparisons. TF-IDF
   over character n-grams plus a nearest-neighbour search cuts that to a handful of
   candidates each, and exact manufacturer-part-number matches are added directly
   because they are the strongest single signal there is.

3. **Score.** A list of independent scorers, combined by weight. Keeping them
   separate is what lets a miss be attributed later — and it is where an embedding
   scorer drops in without restructuring, if one is ever justified.

Two things this has to survive, both deliberate in the generator:
  * a copy that lost its manufacturer part number — the MPN scorer must return
    "no evidence" rather than "they disagree";
  * split history, where the copy carries part of the original's issues.

`engine/` sees only the source tables. Nothing here reads the answer key.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import numpy as np
import pandas as pd
from rapidfuzz import fuzz
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.neighbors import NearestNeighbors

# Standard MRO short forms. This is domain knowledge a matcher is entitled to have
# — every MDM product ships an equivalent table — not knowledge of how the test
# data was built.
ABBREVIATIONS = {
    "BRG": "BEARING", "BRGS": "BEARING", "ASSY": "ASSEMBLY", "ASSM": "ASSEMBLY",
    "CYL": "CYLINDER", "HYD": "HYDRAULIC", "HYDR": "HYDRAULIC",
    "XMTR": "TRANSMITTER", "TX": "TRANSMITTER", "TEMP": "TEMPERATURE",
    "PRESS": "PRESSURE", "PRESS.": "PRESSURE", "ELEC": "ELECTRIC",
    "MV": "MEDIUM VOLTAGE", "LV": "LOW VOLTAGE", "HV": "HIGH VOLTAGE",
    "SS": "STAINLESS", "STNLS": "STAINLESS", "MECH": "MECHANICAL",
    "CENTRIF": "CENTRIFUGAL", "CONV": "CONVEYOR", "PROT": "PROTECTIVE",
    "LUBE": "LUBRICATING", "LUB": "LUBRICATING", "HEX": "HEXAGON",
    "GSKT": "GASKET", "VLV": "VALVE", "MTR": "MOTOR", "GBX": "GEARBOX",
    "REFRAC": "REFRACTORY", "GEN": "GENERAL", "ELEM": "ELEMENT",
}

# Suffixes people append when superseding a record rather than deleting it.
_NOISE = re.compile(r"\b(OLD|DUP|DUPLICATE|OBSOLETE|DO\s*NOT\s*USE|SUPERSEDED|NEW)\b")
_PUNCT = re.compile(r"[^A-Z0-9 ]+")
_SPACE = re.compile(r"\s+")


def normalise(text: str) -> str:
    """Canonical form of a description, for comparison only."""
    s = _PUNCT.sub(" ", str(text).upper())
    s = _NOISE.sub(" ", s)
    words = [ABBREVIATIONS.get(w, w) for w in s.split()]
    return _SPACE.sub(" ", " ".join(words)).strip()


def normalise_maker(text: str) -> str:
    """SKF, S.K.F. and SKF AB are one manufacturer."""
    s = _PUNCT.sub("", str(text).upper())
    for tail in ("LTD", "AG", "GROUP", "CORP", "INC", "AB", "SA", "GMBH", "MINERALS",
                 "ENERGY", "PROCESS", "AUTOMATION", "HANNIFIN", "OUTOTEC", "ELEC"):
        if s.endswith(tail) and len(s) > len(tail) + 1:
            s = s[: -len(tail)]
    return s.strip()


def normalise_mpn(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(text).upper())


# ── scorers ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Scorer:
    """
    One piece of evidence about a candidate pair.

    `weight` is how much it counts; a scorer returning NaN means "no evidence
    here", and its weight is redistributed rather than counted as disagreement.
    That distinction is what stops a blank manufacturer part number — which is
    exactly what a re-keyed duplicate loses — from being read as proof that two
    records are different parts.
    """

    name: str
    weight: float
    fn: object


def _score_description(left: pd.DataFrame, right: pd.DataFrame) -> np.ndarray:
    """
    Order-insensitive text similarity that still notices a missing part.

    `token_sort_ratio`, not `token_set_ratio`. The set variant compares only the
    tokens the two strings share and ignores whatever the longer one has extra, so
    it scored "CHOCK, ROLL, 375MM" against "CHOCK ROLL" at a perfect 1.00 — and the
    extra token is precisely the thing that identifies the variant. Sorting keeps
    the reordered-token mangle matching while a dropped token still costs.
    """
    return np.array(
        [
            fuzz.token_sort_ratio(a, b) / 100.0
            for a, b in zip(left["norm_desc"], right["norm_desc"], strict=True)
        ]
    )


# Characteristics are what is left of a description once the noun and modifier are
# taken away: "OIL, GEAR LUBRICATING, ISO VG 100, GRADE B" leaves {ISO, VG, 100,
# GRADE, B}. They are what distinguishes one variant of a part from another, so
# they carry most of the decision — and `noun` and `modifier` are real columns in
# the master, so no guessing is needed about where the description stops naming the
# part and starts describing it.


def characteristics(norm_desc: str, noun: str, modifier: str) -> frozenset[str]:
    base = set(normalise(noun).split()) | set(normalise(modifier).split())
    return frozenset(w for w in norm_desc.split() if w not in base)


def characteristic_vocabulary(m: pd.DataFrame) -> dict[str, int]:
    """
    How often each characteristic token appears across the whole master.

    This is the signal that separates a typo from a real difference, and the two
    are otherwise identical: "DN65" against "KN65" and "GRADE A" against "GRADE B"
    are both one character apart. But KN65 occurs once in twenty thousand rows and
    GRADE A occurs thousands of times, so the first is a mis-key and the second is
    a different product. Any master-data tool worth using knows its own value sets.
    """
    counts: dict[str, int] = {}
    for tokens in m["characteristics"]:
        for t in tokens:
            counts[t] = counts.get(t, 0) + 1
    return counts


def _score_characteristics(left: pd.DataFrame, right: pd.DataFrame) -> np.ndarray:
    """
    Set overlap of the characteristics, forgiving tokens that look like mis-keys.

    A token present on one side only is normally evidence the two are different
    variants. It is forgiven when it is rare in the catalogue AND closely resembles
    a token on the other side — which is exactly what a typo looks like and what a
    genuine variant does not.
    """
    vocab = left.attrs.get("vocab") or {}
    rare_at = left.attrs.get("rare_at", 3)
    out = np.empty(len(left))

    for i, (a, b) in enumerate(zip(left["characteristics"], right["characteristics"],
                                   strict=True)):
        if not a and not b:
            out[i] = 1.0
            continue

        shared = a & b
        only_a, only_b = list(a - b), list(b - a)

        # Pair off leftovers that look like the same value mis-keyed: one side rare
        # in the catalogue, and the two strings nearly identical. Both halves of the
        # pair are consumed, so the token stops counting against the match at all —
        # excusing only the rare half still left the union too large and dragged a
        # genuine pair down to a half score.
        matched = 0
        for token in list(only_a):
            partner = next(
                (
                    other
                    for other in only_b
                    if (vocab.get(token, 0) < rare_at or vocab.get(other, 0) < rare_at)
                    and fuzz.ratio(token, other) >= 75
                ),
                None,
            )
            if partner is not None:
                only_a.remove(token)
                only_b.remove(partner)
                matched += 1

        union = len(shared) + matched + len(only_a) + len(only_b)
        out[i] = (len(shared) + matched) / max(union, 1)
    return np.clip(out, 0.0, 1.0)


def _score_mpn(left: pd.DataFrame, right: pd.DataFrame) -> np.ndarray:
    """
    Part numbers are near-binary evidence, and treating them as a gradient was
    quietly wrong.

    Two different numbers from the same maker share a prefix and a lot of digits, so
    a plain character ratio scored unrelated parts at 0.67 — which propped up every
    sibling pair in the catalogue. Two different part numbers mean two different
    parts; there is no "partly the same part". Only a near-identical string is
    treated as a possible mis-key rather than a different item.

    NaN when either side is blank, which is exactly what a re-keyed duplicate loses:
    absence of a part number is absence of evidence, not evidence of difference.
    """
    out = np.full(len(left), np.nan)
    for i, (a, b) in enumerate(zip(left["norm_mpn"], right["norm_mpn"], strict=True)):
        if not a or not b:
            continue
        if a == b:
            out[i] = 1.0
        else:
            r = fuzz.ratio(a, b) / 100.0
            out[i] = 0.75 if r >= 0.90 else 0.0      # one slip, or a different part
    return out


def _score_manufacturer(left: pd.DataFrame, right: pd.DataFrame) -> np.ndarray:
    out = np.full(len(left), np.nan)
    for i, (a, b) in enumerate(zip(left["norm_maker"], right["norm_maker"], strict=True)):
        if not a or not b:
            continue
        out[i] = 1.0 if a == b else fuzz.ratio(a, b) / 100.0
    return out


def _score_attributes(left: pd.DataFrame, right: pd.DataFrame) -> np.ndarray:
    """
    Same material group, same unit, and a price within a factor of two.

    Weak on its own — thousands of parts share a group — but it is what separates a
    genuine pair from two different sizes of the same thing.
    """
    same_group = (left["material_group"].to_numpy() == right["material_group"].to_numpy())
    same_uom = (left["uom"].to_numpy() == right["uom"].to_numpy())
    lp = np.maximum(left["unit_price_sar"].to_numpy(), 1.0)
    rp = np.maximum(right["unit_price_sar"].to_numpy(), 1.0)
    close_price = np.abs(np.log(lp / rp)) < np.log(2.0)
    return (0.5 * same_group + 0.25 * same_uom + 0.25 * close_price).astype(float)


# Weights reflect what actually separates a duplicate from a sibling variant. Text
# similarity is necessary but nowhere near sufficient — every variant in a family
# shares its noun and modifier — so the value token and the part number, the two
# signals that are specific to one physical item, carry most of the decision.
SCORERS: tuple[Scorer, ...] = (
    Scorer("characteristics", 0.42, _score_characteristics),
    Scorer("mpn", 0.30, _score_mpn),
    Scorer("description", 0.12, _score_description),
    Scorer("manufacturer", 0.06, _score_manufacturer),
    Scorer("attributes", 0.10, _score_attributes),
)


# ── candidate generation ─────────────────────────────────────────────────────


def _prepare(materials: pd.DataFrame) -> pd.DataFrame:
    m = materials.copy()
    m["norm_desc"] = [normalise(d) for d in m["description"]]
    m["norm_maker"] = [normalise_maker(x) for x in m["manufacturer"]]
    m["norm_mpn"] = [normalise_mpn(x) for x in m["mpn"]]
    # noun and modifier carry the identity of the part; the size token distinguishes
    # variants, so it is kept separate and weighted through the description scorers
    m["key_text"] = (
        m["noun"].astype(str) + " " + m["modifier"].astype(str) + " " + m["norm_desc"]
    )
    m["characteristics"] = [
        characteristics(d, n, mo)
        for d, n, mo in zip(m["norm_desc"], m["noun"], m["modifier"], strict=True)
    ]
    m.attrs["vocab"] = characteristic_vocabulary(m)
    return m


def candidate_pairs(m: pd.DataFrame, *, neighbours: int = 6) -> np.ndarray:
    """
    Pairs worth scoring. Two sources, unioned:

    * TF-IDF over character n-grams, nearest neighbours by cosine. Character grams
      rather than words because the mangling attacks word boundaries — BRG,BALL,6205
      and BEARING BALL 6205 share almost no whole words.
    * Exact normalised part-number matches, added directly. The strongest signal
      available, and cheap.
    """
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 4), min_df=2, sublinear_tf=True)
    x = vec.fit_transform(m["key_text"])

    k = min(neighbours + 1, len(m))
    nn = NearestNeighbors(n_neighbors=k, metric="cosine", algorithm="brute").fit(x)
    _dist, idx = nn.kneighbors(x)

    left = np.repeat(np.arange(len(m)), idx.shape[1])
    right = idx.ravel()
    pairs = np.stack([left, right], axis=1)
    pairs = pairs[pairs[:, 0] != pairs[:, 1]]

    mpn = m["norm_mpn"].to_numpy()
    by_mpn: dict[str, list[int]] = {}
    for i, v in enumerate(mpn):
        if v:
            by_mpn.setdefault(v, []).append(i)
    extra = [
        (a, b)
        for group in by_mpn.values()
        if len(group) > 1
        for a in group
        for b in group
        if a < b
    ]
    if extra:
        pairs = np.concatenate([pairs, np.array(extra)], axis=0)

    # one row per unordered pair
    pairs = np.sort(pairs, axis=1)
    return np.unique(pairs, axis=0)


def score_pairs(m: pd.DataFrame, pairs: np.ndarray) -> pd.DataFrame:
    """Run every scorer over the candidate pairs and combine by weight."""
    left = m.iloc[pairs[:, 0]].reset_index(drop=True)
    right = m.iloc[pairs[:, 1]].reset_index(drop=True)
    left.attrs = dict(m.attrs)          # .iloc does not carry attrs through
    right.attrs = dict(m.attrs)

    parts, weights = [], []
    for s in SCORERS:
        parts.append(s.fn(left, right))
        weights.append(s.weight)

    values = np.vstack(parts)                       # (n_scorers, n_pairs)
    w = np.array(weights)[:, None]
    present = ~np.isnan(values)
    # redistribute the weight of any scorer with nothing to say, so a missing part
    # number lowers confidence rather than acting as evidence against
    total_w = (w * present).sum(axis=0)
    combined = np.nansum(np.nan_to_num(values) * w * present, axis=0) / np.maximum(total_w, 1e-9)

    out = pd.DataFrame(
        {
            "left_id": left["material_id"].to_numpy(),
            "right_id": right["material_id"].to_numpy(),
            "score": combined,
        }
    )
    for s, row in zip(SCORERS, values, strict=True):
        out[f"s_{s.name}"] = row
    return out


def find(materials: pd.DataFrame, *, threshold: float = 0.86, neighbours: int = 6):
    """Return scored pairs above the threshold, best first."""
    m = _prepare(materials)
    pairs = candidate_pairs(m, neighbours=neighbours)
    scored = score_pairs(m, pairs)
    hits = scored[scored["score"] >= threshold].sort_values("score", ascending=False)
    return hits.reset_index(drop=True), scored
