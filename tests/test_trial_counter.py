"""Global trial counter — PRD 04 FR-08, FR-15.

Most of these tests are adversarial rather than functional. A counter that
counts correctly when used correctly is easy; the requirement is a counter that
cannot be quietly avoided, because the researcher it is protecting against is
the one holding the keyboard.

FR-08 puts it explicitly: the count includes "runs whose results were
discarded". So the tests below try to discard, delete, rewrite and abandon
trials, and require the count to survive all four.
"""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.research_integrity.trial_counter import (  # noqa: E402
    TrialCounter,
    TrialCounterError,
)


@pytest.fixture()
def counter(tmp_path) -> TrialCounter:
    return TrialCounter(tmp_path / "trials.db")


# --- FR-08: the count survives every way of avoiding it --------------------

def test_a_trial_counts_before_its_result_exists(counter):
    """The ordering that makes the whole thing work. If a trial only counted
    once it reported a Sharpe, a researcher could look first and register
    second."""
    counter.start_trial("sp500", strategy="momentum")
    assert counter.trial_count("sp500") == 1


def test_a_trial_with_no_outcome_still_counts(counter):
    """The literal words of FR-08: runs whose results were discarded."""
    counter.start_trial("sp500")
    counter.start_trial("sp500")
    t = counter.start_trial("sp500")
    counter.record_outcome(t, sharpe=0.05)
    assert counter.trial_count("sp500") == 3
    assert counter.deflation_inputs("sp500")["trials_without_outcome"] == 2


def test_a_crashed_trial_still_counts(counter):
    """A backtest that raises has still consumed a look at the data."""
    with pytest.raises(ZeroDivisionError):
        with counter.trial("sp500", strategy="broken"):
            1 / 0
    assert counter.trial_count("sp500") == 1


def test_trials_cannot_be_deleted_even_via_raw_sql(counter):
    """The control has to hold against someone who opens the database, not
    just against someone who uses this API politely."""
    counter.start_trial("sp500")
    with sqlite3.connect(counter.db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute("DELETE FROM trials")
    assert counter.trial_count("sp500") == 1


def test_a_recorded_sharpe_cannot_be_rewritten(counter):
    t = counter.start_trial("sp500")
    counter.record_outcome(t, sharpe=0.10)
    with pytest.raises(TrialCounterError, match="already has an outcome"):
        counter.record_outcome(t, sharpe=0.90)
    with sqlite3.connect(counter.db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="cannot be rewritten"):
            conn.execute("UPDATE trials SET sharpe = 0.9 WHERE trial_id = ?", (t,))


def test_a_trial_cannot_be_moved_to_another_dataset(counter):
    """Re-parenting would let a researcher park inconvenient trials against a
    dataset nobody is reporting on."""
    t = counter.start_trial("sp500")
    with sqlite3.connect(counter.db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute("UPDATE trials SET dataset_id = 'other' WHERE trial_id = ?", (t,))


def test_outcome_for_an_unregistered_trial_is_refused(counter):
    """Reporting a result for a trial that was never started would let counting
    happen after the fact, which is the bias being removed."""
    with pytest.raises(TrialCounterError, match="unknown trial"):
        counter.record_outcome("not-a-real-id", sharpe=0.1)


def test_dataset_id_is_required(counter):
    with pytest.raises(ValueError, match="dataset_id"):
        counter.start_trial("")


# --- the count is global, not per-experiment -------------------------------

def test_count_is_global_across_searches_and_researchers(counter):
    """PRD: 'If the count is per-experiment rather than global, it is
    meaningless.'"""
    for i in range(4):
        counter.start_trial("sp500", search_id="search-A", researcher="alice")
    for i in range(6):
        counter.start_trial("sp500", search_id="search-B", researcher="bob")
    assert counter.trial_count("sp500") == 10


def test_counts_are_separated_by_dataset(counter):
    counter.start_trial("sp500")
    counter.start_trial("sp500")
    counter.start_trial("russell2000")
    assert counter.trial_count("sp500") == 2
    assert counter.trial_count("russell2000") == 1


def test_fr15_a_result_inherits_the_full_search_burden(counter):
    """'Extracting a single strategy from a 5,000-trial search does not reset
    the multiple-testing burden.'"""
    for _ in range(500):
        counter.start_trial("sp500", search_id="sweep-1")
    winner = counter.start_trial("sp500", search_id="sweep-1")
    counter.record_outcome(winner, sharpe=0.25)

    assert counter.search_trial_count("sweep-1") == 501
    # And the global count, which is what deflation uses, is at least that.
    assert counter.trial_count("sp500") >= 501


def test_the_count_persists_across_processes(counter, tmp_path):
    """'across all researchers and all time' means it outlives the session."""
    counter.start_trial("sp500")
    counter.start_trial("sp500")
    reopened = TrialCounter(counter.db_path)
    assert reopened.trial_count("sp500") == 2


# --- feeding the deflated Sharpe -------------------------------------------

def test_deflation_inputs_supply_what_the_dsr_requires(counter):
    for sharpe in (0.02, 0.05, 0.11, 0.07, 0.09):
        t = counter.start_trial("sp500")
        counter.record_outcome(t, sharpe=sharpe)
    inputs = counter.deflation_inputs("sp500")
    assert inputs["n_trials"] == 5
    assert inputs["var_trials"] > 0


def test_variance_is_none_rather_than_a_fabricated_zero(counter):
    """With one data point there is no variance. Returning 0.0 would silently
    remove the selection-bias correction entirely, since SR_0 scales with
    sqrt(V[SR]) — a fabricated zero here means 'no multiple-testing burden'."""
    t = counter.start_trial("sp500")
    counter.record_outcome(t, sharpe=0.1)
    assert counter.sharpe_variance("sp500") is None
    assert counter.deflation_inputs("sp500")["var_trials"] is None


def test_variance_matches_the_sample_variance(counter):
    import statistics

    values = [0.02, 0.05, 0.11, 0.07, 0.09]
    for v in values:
        t = counter.start_trial("sp500")
        counter.record_outcome(t, sharpe=v)
    assert counter.sharpe_variance("sp500") == pytest.approx(statistics.variance(values))


def test_end_to_end_deflation_uses_recorded_history(counter):
    """The join that motivated this module: a deflated Sharpe computed from a
    real trial count and a real variance, neither of them typed in by hand."""
    from src.research_integrity import deflated_sharpe_ratio

    for i in range(200):
        t = counter.start_trial("sp500", search_id="sweep")
        counter.record_outcome(t, sharpe=0.01 + (i % 17) * 0.004)

    best = counter.start_trial("sp500", search_id="sweep")
    counter.record_outcome(best, sharpe=0.14)

    inputs = counter.deflation_inputs("sp500")
    dsr = deflated_sharpe_ratio(
        observed_sharpe=0.14,
        n_trials=inputs["n_trials"],
        sample_length=1250,
        skewness=-0.3,
        kurtosis=4.0,
        var_trials=inputs["var_trials"],
    )
    assert 0.0 <= dsr <= 1.0
    assert inputs["n_trials"] == 201


def test_more_trials_lower_the_deflated_sharpe(counter):
    """The property the whole module exists to produce: searching harder makes
    the same result less impressive, automatically, without anyone choosing to
    be honest about it."""
    from src.research_integrity import deflated_sharpe_ratio

    def dsr_after(n_trials: int) -> float:
        c = TrialCounter(Path(counter.db_path).parent / f"d{n_trials}.db")
        for i in range(n_trials):
            t = c.start_trial("ds")
            c.record_outcome(t, sharpe=0.01 + (i % 13) * 0.005)
        inputs = c.deflation_inputs("ds")
        return deflated_sharpe_ratio(
            observed_sharpe=0.12, n_trials=inputs["n_trials"], sample_length=1250,
            skewness=0.0, kurtosis=3.0, var_trials=inputs["var_trials"])

    assert dsr_after(500) < dsr_after(20)


# --- auditability ----------------------------------------------------------

def test_the_full_record_is_retrievable(counter):
    counter.start_trial("sp500", strategy="momentum", params={"lookback": 20},
                        researcher="alice", dataset_version="v3")
    (row,) = counter.trials("sp500")
    assert row["strategy"] == "momentum"
    assert row["researcher"] == "alice"
    assert row["dataset_version"] == "v3"
    assert '"lookback": 20' in row["params_json"]
    assert row["started_at"]
