"""Purged, embargoed cross-validation — PRD 04 §5.2, FR-14.

    FR-14: "Cross-validation MUST use purged, embargoed splits appropriate to
    overlapping-label financial data. Naive k-fold MUST NOT be offered."

WHY NAIVE K-FOLD FAILS HERE, CONCRETELY

A financial label usually resolves in the future: the observation made at time
t is labelled by what the price did over [t, t+h]. Two observations less than h
apart therefore share outcome information — they are not independent draws.

Standard k-fold shuffles or slices without regard to that, so a training
observation whose label window overlaps the test window has already seen part
of the test set's answer. The model does not need to generalise; it needs to
remember. The resulting score is optimistic in a way no amount of repetition
detects, because every fold has the same leak.

THE FIX, from López de Prado, Advances in Financial Machine Learning, ch. 7

  PURGING   Drop from the training set every observation whose label interval
            [t0, t1] overlaps the test set's interval. This is the defining
            property, and `assert_no_leakage` below checks it directly.

  EMBARGO   After purging, additionally drop training observations that begin
            shortly AFTER the test set ends. Purging handles overlap; the
            embargo handles serial correlation, which leaks through even
            non-overlapping windows that sit adjacent to each other.

The embargo is described in the source as "small" without a canonical size, so
it is a parameter here rather than a hard-coded fraction, defaulting to 1% of
the sample — a common choice, not a derived one, and labelled as such.

WHAT THIS MODULE REFUSES TO DO

It offers no unpurged splitter. FR-14 says naive k-fold must not be offered,
and a convenience flag to disable purging would be exactly that with an extra
step: the leaky path would become the one people reach for when the purged one
gives disappointing numbers.
"""
from __future__ import annotations

from typing import Iterator, Sequence

import numpy as np


class LeakageError(AssertionError):
    """Raised when a split would let test-set information into training."""


class PurgedKFold:
    """K-fold cross-validation with purging and an embargo.

        cv = PurgedKFold(n_splits=5, embargo_pct=0.01)
        for train_idx, test_idx in cv.split(label_start, label_end):
            ...

    `label_start[i]` is when observation i's information becomes available and
    `label_end[i]` is when its label resolves. For a 10-day forward return,
    label_end = label_start + 10 days. Both must be sorted ascending by
    label_start, which is how time series arrive and what makes contiguous test
    folds meaningful.
    """

    def __init__(self, n_splits: int = 5, embargo_pct: float = 0.01) -> None:
        if not isinstance(n_splits, int) or n_splits < 2:
            raise ValueError(f"n_splits must be an integer >= 2, got {n_splits!r}")
        if not 0.0 <= embargo_pct < 0.5:
            raise ValueError(
                f"embargo_pct must be in [0, 0.5), got {embargo_pct!r}. An "
                "embargo approaching half the sample would leave nothing to "
                "train on.")
        self.n_splits = n_splits
        self.embargo_pct = float(embargo_pct)

    def split(self, label_start: Sequence, label_end: Sequence
              ) -> Iterator[tuple[np.ndarray, np.ndarray]]:
        """Yield (train_idx, test_idx) with training purged and embargoed."""
        t0 = np.asarray(label_start)
        t1 = np.asarray(label_end)
        if t0.shape != t1.shape:
            raise ValueError(f"label_start and label_end differ in length: "
                             f"{t0.shape} vs {t1.shape}")
        n = t0.size
        if n < self.n_splits:
            raise ValueError(f"cannot make {self.n_splits} folds from {n} observations")
        if np.any(t1 < t0):
            bad = int(np.argmax(t1 < t0))
            raise ValueError(
                f"observation {bad} has label_end before label_start; a label "
                "cannot resolve before the information that produced it")
        if np.any(np.diff(t0) < 0):
            raise ValueError(
                "label_start must be sorted ascending. Contiguous test folds "
                "over unsorted times would carve arbitrary slices of history, "
                "and the purge would then be computed against the wrong window.")

        indices = np.arange(n)
        embargo_span = int(n * self.embargo_pct)

        for test_idx in np.array_split(indices, self.n_splits):
            if test_idx.size == 0:
                continue
            test_start = t0[test_idx].min()
            # The test window runs to the LAST label resolution inside it, not
            # to the last observation. A label that resolves beyond the fold
            # still carries that information.
            test_end = t1[test_idx].max()

            # PURGE: any training label whose interval overlaps the test window.
            overlaps = (t0 <= test_end) & (t1 >= test_start)
            train_mask = ~overlaps

            # EMBARGO: drop training observations starting just after the test
            # window closes. Purging removes overlap; this removes adjacency.
            if embargo_span > 0:
                after = indices[indices > test_idx.max()]
                if after.size:
                    train_mask[after[:embargo_span]] = False

            train_idx = indices[train_mask]
            if train_idx.size == 0:
                raise ValueError(
                    "purging and embargo removed the entire training set for a "
                    "fold. Labels are long relative to the sample, or there are "
                    "too many folds; both mean this data cannot support "
                    f"{self.n_splits}-fold validation honestly.")
            yield train_idx, test_idx

    def get_n_splits(self, *args, **kwargs) -> int:
        return self.n_splits


def assert_no_leakage(train_idx: np.ndarray, test_idx: np.ndarray,
                      label_start: Sequence, label_end: Sequence) -> None:
    """The defining property of a purged split, checked directly.

    No training label may overlap the test window. This is deliberately a
    separate function rather than an internal assertion: it lets a caller verify
    splits produced by ANY splitter, including one from a library, rather than
    trusting that purging was applied.
    """
    t0 = np.asarray(label_start)
    t1 = np.asarray(label_end)
    test_start = t0[test_idx].min()
    test_end = t1[test_idx].max()

    overlapping = train_idx[(t0[train_idx] <= test_end) & (t1[train_idx] >= test_start)]
    if overlapping.size:
        raise LeakageError(
            f"{overlapping.size} training observations have labels overlapping "
            f"the test window [{test_start}, {test_end}] — for example index "
            f"{int(overlapping[0])} with label "
            f"[{t0[overlapping[0]]}, {t1[overlapping[0]]}]. Those observations "
            "already contain part of the test set's answer.")


def leakage_report(label_start: Sequence, label_end: Sequence,
                   n_splits: int = 5, embargo_pct: float = 0.01) -> dict:
    """Quantify what purging removes, and what naive k-fold would have leaked.

    Exists because "use purged CV" is advice, while "naive k-fold would have
    leaked 412 observations into your training set" is a reason.
    """
    t0 = np.asarray(label_start)
    t1 = np.asarray(label_end)
    n = t0.size
    indices = np.arange(n)

    purged_total = 0
    leaked_total = 0
    for test_idx in np.array_split(indices, n_splits):
        if test_idx.size == 0:
            continue
        test_start, test_end = t0[test_idx].min(), t1[test_idx].max()
        naive_train = indices[~np.isin(indices, test_idx)]
        leaked = naive_train[(t0[naive_train] <= test_end)
                             & (t1[naive_train] >= test_start)]
        leaked_total += leaked.size

    cv = PurgedKFold(n_splits=n_splits, embargo_pct=embargo_pct)
    for train_idx, test_idx in cv.split(t0, t1):
        purged_total += n - test_idx.size - train_idx.size

    return {
        "observations": int(n),
        "n_splits": n_splits,
        "embargo_pct": embargo_pct,
        "would_leak_under_naive_kfold": int(leaked_total),
        "removed_by_purge_and_embargo": int(purged_total),
        "leak_rate_naive": leaked_total / (n * n_splits) if n else 0.0,
    }
