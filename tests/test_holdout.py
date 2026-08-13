"""Protected holdout — PRD 04 FR-10, FR-11, FR-12.

As with the trial counter, most of these are adversarial. The failure mode a
holdout guards against is rarely a decision to cheat; it is drift — one peek to
sanity-check the pipeline, another to compare two variants, and by the tenth the
holdout is in-sample data everyone still calls out-of-sample. No step in that
sequence feels wrong at the time, which is why the mechanism has to refuse
rather than advise.

So these tests try to move the holdout after seeing results, evaluate without a
prediction, reuse a registration, edit a recorded evaluation, and delete the
history that drives the exhaustion count.
"""
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.research_integrity.holdout import (  # noqa: E402
    HoldoutViolation,
    ProtectedHoldout,
)

VALID = dict(strategy_family="momentum",
             hypothesis="20-day momentum survives out of sample",
             expected_result="annualised Sharpe between 0.4 and 0.8")


@pytest.fixture()
def holdout(tmp_path) -> ProtectedHoldout:
    h = ProtectedHoldout(tmp_path / "research.db")
    h.define("sp500", start="2023-01-01", end="2024-12-31")
    return h


# --- FR-10: ordinary backtests cannot reach it -----------------------------

@pytest.mark.parametrize("start,end", [
    ("2020-01-01", "2023-06-30"),   # runs into the holdout
    ("2023-06-01", "2023-07-01"),   # entirely inside
    ("2024-06-01", "2025-06-30"),   # runs out of it
    ("2019-01-01", "2026-01-01"),   # straddles it completely
])
def test_ordinary_access_overlapping_the_holdout_is_refused(holdout, start, end):
    with pytest.raises(HoldoutViolation, match="holdout"):
        holdout.assert_ordinary_access("sp500", start, end)


def test_ordinary_access_outside_the_holdout_is_allowed(holdout):
    holdout.assert_ordinary_access("sp500", "2015-01-01", "2022-12-31")


def test_a_dataset_with_no_holdout_is_unrestricted(holdout):
    holdout.assert_ordinary_access("russell2000", "2015-01-01", "2025-01-01")


def test_the_holdout_period_cannot_be_moved(holdout):
    """A holdout you can redefine after seeing results is not a holdout — you
    would simply move it off the period that disagreed with you."""
    with pytest.raises(HoldoutViolation, match="cannot be redefined"):
        holdout.define("sp500", start="2024-01-01", end="2024-06-30")


def test_redefining_identically_is_idempotent_not_an_error(holdout):
    result = holdout.define("sp500", start="2023-01-01", end="2024-12-31")
    assert result["already_defined"] is True


def test_the_period_cannot_be_edited_or_deleted_via_raw_sql(holdout):
    with sqlite3.connect(holdout.db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute("UPDATE holdout_periods SET end_date = '2023-02-01'")
        with pytest.raises(sqlite3.IntegrityError, match="cannot be deleted"):
            conn.execute("DELETE FROM holdout_periods")


# --- FR-11: access requires a prediction, made first -----------------------

def test_evaluation_without_a_registration_is_refused(holdout):
    with pytest.raises(HoldoutViolation, match="unknown pre-registration"):
        holdout.evaluate("made-up-id", observed={"sharpe": 0.3})


def test_a_registration_buys_exactly_one_look(holdout):
    """The rule that stops drift. Wanting a second look means writing down a
    second prediction, under your name, before taking it."""
    reg = holdout.preregister("sp500", **VALID)
    holdout.evaluate(reg, observed={"sharpe": 0.31})
    with pytest.raises(HoldoutViolation, match="already spent"):
        holdout.evaluate(reg, observed={"sharpe": 0.31})


@pytest.mark.parametrize("field", ["strategy_family", "hypothesis", "expected_result"])
def test_an_empty_prediction_is_refused(holdout, field):
    kwargs = {**VALID, field: "   "}
    with pytest.raises(ValueError, match=field):
        holdout.preregister("sp500", **kwargs)


def test_a_vacuous_expected_result_is_refused(holdout):
    """'we will see' constrains nothing at evaluation time, which is the entire
    function of writing it down beforehand."""
    with pytest.raises(ValueError, match="falsifiable"):
        holdout.preregister("sp500", **{**VALID, "expected_result": "good"})


def test_a_registration_is_immutable(holdout):
    reg = holdout.preregister("sp500", **VALID)
    with sqlite3.connect(holdout.db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            conn.execute(
                "UPDATE preregistrations SET expected_result = 'Sharpe above 2.0' "
                "WHERE registration_id = ?", (reg,))


def test_registrations_cannot_be_deleted(holdout):
    """Deleting one would hide a look at the holdout."""
    holdout.preregister("sp500", **VALID)
    with sqlite3.connect(holdout.db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="permanent"):
            conn.execute("DELETE FROM preregistrations")


def test_the_registration_is_content_hashed(holdout):
    reg = holdout.preregister("sp500", **VALID)
    record = holdout.registration(reg)
    assert len(record["content_hash"]) == 64
    assert record["registered_at"]


# --- FR-12: permanent record and exhaustion flagging -----------------------

def test_first_evaluation_carries_no_warning(holdout):
    reg = holdout.preregister("sp500", **VALID)
    result = holdout.evaluate(reg, observed={"sharpe": 0.31})
    assert result["evaluations"] == 1
    assert result["exhausted"] is False
    assert result["warning"] is None


def test_a_second_look_at_the_same_family_is_flagged(holdout):
    for _ in range(2):
        reg = holdout.preregister("sp500", **VALID)
        result = holdout.evaluate(reg, observed={"sharpe": 0.3})
    assert result["exhausted"] is True
    assert "EXHAUSTION" in result["warning"]


def test_the_warning_escalates_with_repeated_looks(holdout):
    """A second look is a caveat; a tenth means the holdout is in-sample data
    still being described as out-of-sample. The warning should say so."""
    for _ in range(5):
        reg = holdout.preregister("sp500", **VALID)
        result = holdout.evaluate(reg, observed={"sharpe": 0.3})
    assert "EXHAUSTED" in result["warning"]
    assert "in-sample" in result["warning"]


def test_different_families_do_not_exhaust_each_other(holdout):
    for family in ("momentum", "mean_reversion", "carry"):
        reg = holdout.preregister("sp500", **{**VALID, "strategy_family": family})
        result = holdout.evaluate(reg, observed={"sharpe": 0.2})
        assert result["exhausted"] is False


def test_the_result_cannot_be_displayed_without_the_warning(holdout):
    """The warning travels with the result rather than needing a second call —
    a caller rendering the Sharpe necessarily has the exhaustion status too."""
    for _ in range(2):
        reg = holdout.preregister("sp500", **VALID)
        result = holdout.evaluate(reg, observed={"sharpe": 0.3})
    assert "observed" in result and "warning" in result


def test_evaluations_are_permanent(holdout):
    """Deleting one would reset the exhaustion count, which is the number the
    whole requirement turns on."""
    reg = holdout.preregister("sp500", **VALID)
    holdout.evaluate(reg, observed={"sharpe": 0.31})
    with sqlite3.connect(holdout.db_path) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="permanent"):
            conn.execute("DELETE FROM holdout_evaluations")
        with pytest.raises(sqlite3.IntegrityError, match="permanent"):
            conn.execute("UPDATE holdout_evaluations SET observed_json = '{}'")


def test_the_prediction_is_recorded_alongside_the_outcome(holdout):
    """So a reader can compare what was predicted with what happened, which is
    the only thing that makes pre-registration worth the friction."""
    reg = holdout.preregister("sp500", **VALID)
    result = holdout.evaluate(reg, observed={"sharpe": 0.12})
    assert result["expected_result"] == VALID["expected_result"]
    assert result["observed"] == {"sharpe": 0.12}


def test_history_survives_reopening(holdout):
    reg = holdout.preregister("sp500", **VALID)
    holdout.evaluate(reg, observed={"sharpe": 0.31})
    reopened = ProtectedHoldout(holdout.db_path)
    assert len(reopened.evaluations("sp500")) == 1
    assert reopened.holdout_period("sp500") == ("2023-01-01", "2024-12-31")


def test_empty_observations_are_refused(holdout):
    reg = holdout.preregister("sp500", **VALID)
    with pytest.raises(ValueError, match="observed"):
        holdout.evaluate(reg, observed={})


def test_a_backwards_period_is_refused(tmp_path):
    h = ProtectedHoldout(tmp_path / "x.db")
    with pytest.raises(ValueError, match="start < end"):
        h.define("ds", start="2024-12-31", end="2023-01-01")
