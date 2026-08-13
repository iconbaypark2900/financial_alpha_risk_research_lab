"""Purged, embargoed cross-validation — PRD 04 FR-14.

The defining property is checkable directly rather than by inspection: after a
purged split, NO training label may overlap the test window. `assert_no_leakage`
states it, and most tests here are that assertion applied to cases chosen to
break it.

The most informative test is `test_naive_kfold_would_leak_on_this_data`, which
constructs the leak the module exists to prevent and confirms it is really
there. Without it, every passing test below could be satisfied by data where
nothing overlapped in the first place — proving the splitter safe on input that
was never dangerous.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.research_integrity.cross_validation import (  # noqa: E402
    LeakageError,
    PurgedKFold,
    assert_no_leakage,
    leakage_report,
)


def overlapping_labels(n=500, horizon=10):
    """Each observation is labelled by the next `horizon` periods, so any two
    observations within `horizon` of each other share outcome information."""
    start = np.arange(n)
    return start, start + horizon


# --- the leak is real, before we claim to prevent it -----------------------

def test_naive_kfold_would_leak_on_this_data():
    """The discriminating test. If naive k-fold did not leak here, every other
    test in this file would be vacuous — a splitter proven safe on data that
    was never dangerous."""
    t0, t1 = overlapping_labels()
    report = leakage_report(t0, t1, n_splits=5)
    assert report["would_leak_under_naive_kfold"] > 0, (
        "the fixture does not actually produce overlapping labels, so it "
        "cannot demonstrate anything")


def test_purging_removes_the_leak_that_naive_kfold_leaves():
    t0, t1 = overlapping_labels()
    for train_idx, test_idx in PurgedKFold(n_splits=5).split(t0, t1):
        assert_no_leakage(train_idx, test_idx, t0, t1)


def test_the_leakage_report_quantifies_both_sides():
    """'Use purged CV' is advice; a count of leaked observations is a reason."""
    t0, t1 = overlapping_labels(n=1000, horizon=20)
    report = leakage_report(t0, t1, n_splits=5)
    assert report["would_leak_under_naive_kfold"] > 0
    assert report["removed_by_purge_and_embargo"] > 0
    assert report["observations"] == 1000


# --- the defining property --------------------------------------------------

@pytest.mark.parametrize("horizon", [1, 5, 25, 100])
@pytest.mark.parametrize("n_splits", [2, 3, 5])
def test_no_training_label_overlaps_the_test_window(horizon, n_splits):
    t0, t1 = overlapping_labels(n=600, horizon=horizon)
    for train_idx, test_idx in PurgedKFold(n_splits=n_splits).split(t0, t1):
        assert_no_leakage(train_idx, test_idx, t0, t1)


def test_assert_no_leakage_actually_catches_a_leak():
    """The checker must fail on a bad split, or it certifies nothing."""
    t0, t1 = overlapping_labels(n=100, horizon=10)
    test_idx = np.arange(50, 60)
    naive_train = np.setdiff1d(np.arange(100), test_idx)
    with pytest.raises(LeakageError, match="overlapping"):
        assert_no_leakage(naive_train, test_idx, t0, t1)


def test_longer_labels_purge_more():
    """A longer forward horizon overlaps more neighbours, so more must go.
    A splitter whose output did not respond to horizon would not be purging."""
    def kept(horizon):
        t0, t1 = overlapping_labels(n=600, horizon=horizon)
        return sum(len(tr) for tr, _ in PurgedKFold(n_splits=5).split(t0, t1))

    assert kept(50) < kept(20) < kept(5)


# --- test folds partition the data ------------------------------------------

def test_test_folds_are_disjoint_and_cover_everything():
    t0, t1 = overlapping_labels(n=503, horizon=7)   # deliberately not divisible
    seen = []
    for _, test_idx in PurgedKFold(n_splits=5).split(t0, t1):
        seen.append(test_idx)
    all_test = np.concatenate(seen)
    assert np.array_equal(np.sort(all_test), np.arange(503))
    assert len(set(all_test.tolist())) == 503


def test_train_and_test_never_intersect():
    t0, t1 = overlapping_labels()
    for train_idx, test_idx in PurgedKFold(n_splits=5).split(t0, t1):
        assert not set(train_idx.tolist()) & set(test_idx.tolist())


# --- the embargo -------------------------------------------------------------

def test_the_embargo_removes_observations_after_the_test_window():
    """Purging removes overlap; the embargo removes adjacency, which leaks
    through serial correlation even when the label windows do not touch."""
    t0, t1 = overlapping_labels(n=1000, horizon=1)

    def train_size(embargo):
        cv = PurgedKFold(n_splits=5, embargo_pct=embargo)
        return sum(len(tr) for tr, _ in cv.split(t0, t1))

    assert train_size(0.05) < train_size(0.0)


def test_the_embargo_applies_after_the_test_set_not_before():
    """The source is specific about the side: an embargo is added AFTER a test
    set, before the next training fold."""
    n, horizon, embargo_pct = 1000, 1, 0.05
    t0, t1 = overlapping_labels(n=n, horizon=horizon)
    cv = PurgedKFold(n_splits=5, embargo_pct=embargo_pct)
    folds = list(cv.split(t0, t1))

    # Use a middle fold so there is data on both sides.
    train_idx, test_idx = folds[2]
    span = int(n * embargo_pct)
    after = np.arange(test_idx.max() + 1, min(test_idx.max() + 1 + span, n))
    before = np.arange(max(0, test_idx.min() - span), test_idx.min())

    assert not set(after.tolist()) & set(train_idx.tolist()), \
        "observations immediately after the test window survived the embargo"
    # The region before the test set is purged only if it overlaps; with
    # horizon=1 most of it should survive, proving the embargo is one-sided.
    assert set(before.tolist()) & set(train_idx.tolist()), \
        "the embargo appears to be applied before the test set as well"


# --- FR-14: naive k-fold is not on offer ------------------------------------

def test_there_is_no_way_to_disable_purging():
    """A flag to turn purging off would be naive k-fold with an extra step —
    and it would become the path people take when the honest numbers
    disappoint."""
    import inspect

    signature = inspect.signature(PurgedKFold.__init__)
    assert set(signature.parameters) == {"self", "n_splits", "embargo_pct"}
    assert not hasattr(PurgedKFold, "purge")


# --- refusals ----------------------------------------------------------------

def test_unsorted_labels_are_refused():
    t0 = np.array([5, 1, 3, 9, 2, 7])
    with pytest.raises(ValueError, match="sorted"):
        list(PurgedKFold(n_splits=2).split(t0, t0 + 1))


def test_a_label_resolving_before_it_starts_is_refused():
    t0 = np.arange(100)
    t1 = t0 - 5
    with pytest.raises(ValueError, match="before"):
        list(PurgedKFold(n_splits=2).split(t0, t1))


def test_labels_too_long_for_the_sample_are_refused():
    """If purging leaves no training data, this dataset cannot support this
    many folds honestly — say so rather than train on nothing."""
    t0, t1 = overlapping_labels(n=100, horizon=100)
    with pytest.raises(ValueError, match="entire training set"):
        list(PurgedKFold(n_splits=5).split(t0, t1))


def test_mismatched_label_arrays_are_refused():
    with pytest.raises(ValueError, match="differ in length"):
        list(PurgedKFold(n_splits=2).split(np.arange(10), np.arange(11)))


@pytest.mark.parametrize("bad", [0, 1, -3, 2.5])
def test_invalid_split_counts_are_refused(bad):
    with pytest.raises(ValueError, match="n_splits"):
        PurgedKFold(n_splits=bad)


@pytest.mark.parametrize("bad", [-0.1, 0.5, 1.0])
def test_invalid_embargo_is_refused(bad):
    with pytest.raises(ValueError, match="embargo_pct"):
        PurgedKFold(embargo_pct=bad)
