import pytest
import math
import json
from src.research_integrity.core import (
    deflated_sharpe_ratio,
    minimum_backtest_length,
    evaluate
)

# --- Test Data ---

NORMAL_PARAMS = {
    "observed_sharpe": 1.5,
    "n_trials": 10,
    "sample_length": 500,
    "skewness": 0.0,
    "kurtosis": 3.0
}

# --- R1: deflated_sharpe_ratio Tests ---

def test_dsr_normal_case():
    # With normal distribution, skew=0, kurtosis=3
    # sigma_sr = sqrt(1/500 * (1 + 0 + 0 + 0)) = sqrt(1/500)
    # sr_benchmark = sqrt(2 * ln(10) / 500) = sqrt(2 * 2.3025 / 500) = sqrt(4.605 / 500) = sqrt(0.00921) = 0.09597
    # sigma_sr = 1 / sqrt(500) = 1 / 22.36 = 0.04472
    # z = (1.5 - 0.09597) / 0.04472 = 1.40403 / 0.04472 = 31.39
    # Phi(31.39) should be ~1.0
    dsr = deflated_sharpe_ratio(**NORMAL_PARAMS)
    assert 0.0 <= dsr <= 1.0
    assert dsr > 0.99

def test_dsr_n_trials_1():
    # n_trials = 1 should be accepted and sr_benchmark = 0
    params = NORMAL_PARAMS.copy()
    params["n_trials"] = 1
    dsr = deflated_sharpe_ratio(**params)
    assert 0.0 <= dsr <= 1.0
    # With SR=1.5 and benchmark=0, DSR should be high
    assert dsr > 0.5

def test_dsr_negative_sharpe():
    params = NORMAL_PARAMS.copy()
    params["observed_sharpe"] = -1.0
    dsr = deflated_sharpe_ratio(**params)
    assert 0.0 <= dsr <= 1.0
    assert dsr < 0.5

def test_dsr_edge_cases_raises():
    # n_trials <= 0
    with pytest.raises(ValueError, match="n_trials must be greater than 0"):
        deflated_sharpe_ratio(1.5, 0, 500, 0, 3)
    
    # sample_length <= 1
    with pytest.raises(ValueError, match="sample_length must be greater than 1"):
        deflated_sharpe_ratio(1.5, 10, 1, 0, 3)

    # Non-finite inputs
    with pytest.raises(ValueError, match="must be a finite number"):
        deflated_sharpe_ratio(float('nan'), 10, 500, 0, 3)
    with pytest.raises(ValueError, match="must be a finite number"):
        deflated_sharpe_ratio(1.5, 10, float('inf'), 0, 3)

    # Invalid types
    with pytest.raises(TypeError, match="must be a numeric type"):
        deflated_sharpe_ratio("1.5", 10, 500, 0, 3)
    with pytest.raises(TypeError, match="must be a numeric type"):
        deflated_sharpe_ratio(1.5, None, 500, 0, 3)

# --- R2: minimum_backtest_length Tests ---

def test_min_length_normal_case():
    # T_min = ((sqrt(2 * ln(10)) + 1.645) / 1.5)^2
    # = ((sqrt(4.605) + 1.645) / 1.5)^2
    # = ((2.146 + 1.645) / 1.5)^2 = (3.791 / 1.5)^2 = (2.527)^2 = 6.38
    t_min = minimum_backtest_length(1.5, 10)
    assert t_min > 0
    assert math.isclose(t_min, 6.38, rel_tol=1e-2)

def test_min_length_raises():
    # n_trials <= 0
    with pytest.raises(ValueError, match="n_trials must be greater than 0"):
        minimum_backtest_length(1.5, 0)
    
    # observed_sharpe <= 0
    with pytest.raises(ValueError, match="observed_sharpe must be positive"):
        minimum_backtest_length(0, 10)
    with pytest.raises(ValueError, match="observed_sharpe must be positive"):
        minimum_backtest_length(-1.0, 10)

# --- R3: evaluate Tests ---

def test_evaluate_verdict():
    # Case: sample is too short
    # T_min is ~6.38, so sample_length 5 should be too short
    res = evaluate(observed_sharpe=1.5, n_trials=10, sample_length=5, skewness=0, kurtosis=3)
    assert res["sample_too_short"] is True
    assert res["sample_length"] == 5
    assert "deflated_sharpe" in res
    assert "min_backtest_length" in res

    # Case: sample is long enough
    res = evaluate(observed_sharpe=1.5, n_trials=10, sample_length=10, skewness=0, kurtosis=3)
    assert res["sample_too_short"] is False

# --- Properties P1-P5 Tests ---

def test_p1_monotonic_in_trials():
    # Increasing n_trials MUST NOT increase DSR
    dsr_low = deflated_sharpe_ratio(1.5, 10, 500, 0, 3)
    dsr_high = deflated_sharpe_ratio(1.5, 100, 500, 0, 3)
    assert dsr_high <= dsr_low

def test_p2_monotonic_in_observed_sharpe():
    # Increasing observed Sharpe MUST NOT decrease DSR
    dsr_low = deflated_sharpe_ratio(1.0, 10, 500, 0, 3)
    dsr_high = deflated_sharpe_ratio(2.0, 10, 500, 0, 3)
    assert dsr_high >= dsr_low

def test_p3_bounded():
    # DSR in [0, 1]
    assert 0.0 <= deflated_sharpe_ratio(1.5, 10, 500, 0, 3) <= 1.0
    assert 0.0 <= deflated_sharpe_ratio(-1.5, 10, 500, 0, 3) <= 1.0

def test_p4_trials_raise_the_bar():
    # Increasing n_trials MUST NOT decrease min_backtest_length
    t_min_low = minimum_backtest_length(1.5, 10)
    t_min_high = minimum_backtest_length(1.5, 100)
    assert t_min_high >= t_min_low

def test_p5_deterministic():
    # Identical inputs produce identical outputs
    params = (1.5, 10, 500, 0.1, 3.5)
    assert deflated_sharpe_ratio(*params) == deflated_sharpe_ratio(*params)
    assert minimum_backtest_length(1.5, 10) == minimum_backtest_length(1.5, 10)
