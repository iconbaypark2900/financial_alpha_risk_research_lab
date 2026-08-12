import math
from statistics import NormalDist as _NormalDist
import json
import sys

class NormalDistribution:
    """
    A minimal implementation of the standard normal distribution
    using only the math module.
    """
    @staticmethod
    def cdf(x: float) -> float:
        """Standard normal cumulative distribution function."""
        return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))

    @staticmethod
    def ppf(p: float) -> float:
        """
        Standard normal percent point function (inverse CDF).

        Uses statistics.NormalDist from the standard library. A hand-rolled
        Newton iteration was here and diverged: ppf(0.95) returned -32.81
        instead of +1.6449, with the sign inverted and the magnitude wrong by a
        factor of twenty. Both the deflated Sharpe and the minimum backtest
        length depend on this value, so the error propagated into every result
        while the monotonicity and bounds invariants still held.
        """
        if p <= 0 or p >= 1:
            raise ValueError("p must be in (0, 1)")
        return _NormalDist().inv_cdf(p)

def deflated_sharpe_ratio(
    observed_sharpe: float,
    n_trials: int,
    sample_length: int,
    skewness: float,
    kurtosis: float
) -> float:
    """
    Computes the Deflated Sharpe Ratio (DSR).

    Source: Bailey & López de Prado (2014), "The Deflated Sharpe Ratio: Correcting for
    Selection Bias, Backtest Overfitting and Non-Normality."

    Formula:
    DSR = Phi((SR_obs - SR_benchmark) / sigma_SR)

    Where:
    - SR_obs: observed Sharpe ratio
    - SR_benchmark: expected maximum Sharpe ratio among n_trials (approximated)
    - sigma_SR: standard deviation of the estimated Sharpe ratio (Cornish-Fisher expansion)
    - Phi: standard normal CDF

    The benchmark SR_benchmark is approximated as:
    SR_benchmark = sqrt(2 * ln(n_trials) / sample_length)

    The standard deviation sigma_SR (adjusted for skewness and kurtosis) is:
    sigma_SR = sqrt(1/T * (1 + (gamma3/6)*SR_obs + ((gamma4-3)/24)*SR_obs^2 + (gamma3^2/36)*SR_obs^3))

    Args:
        observed_sharpe: The observed Sharpe ratio.
        n_trials: Number of independent trials conducted.
        sample_length: Number of observations in the sample (T).
        skewness: Skewness of the returns (gamma3).
        kurtosis: Kurtosis of the returns (gamma4).

    Returns:
        The Deflated Sharpe Ratio as a probability in [0, 1].

    Raises:
        ValueError: If n_trials <= 0, sample_length <= 1, or any input is non-finite.
        TypeError: If any input is not a numeric type.
    """
    # Type checking
    for name, val in [
        ("observed_sharpe", observed_sharpe),
        ("n_trials", n_trials),
        ("sample_length", sample_length),
        ("skewness", skewness),
        ("kurtosis", kurtosis),
    ]:
        if not isinstance(val, (int, float)):
            raise TypeError(f"{name} must be a numeric type, got {type(val).__name__}")
        if not math.isfinite(val):
            raise ValueError(f"{name} must be a finite number")

    # Value validation
    if n_trials <= 0:
        raise ValueError("n_trials must be greater than 0")
    if sample_length <= 1:
        raise ValueError("sample_length must be greater than 1")

    # Special case: n_trials = 1
    if n_trials == 1:
        sr_benchmark = 0.0
    else:
        sr_benchmark = math.sqrt(2 * math.log(n_trials) / sample_length)

    # Cornish-Fisher adjusted standard deviation
    term1 = 1.0
    term2 = (skewness / 6.0) * observed_sharpe
    term3 = ((kurtosis - 3.0) / 24.0) * (observed_sharpe ** 2)
    term4 = ((skewness ** 2) / 36.0) * (observed_sharpe ** 3)
    
    variance_adjustment = term1 + term2 + term3 + term4
    
    if variance_adjustment <= 0:
        sigma_sr = 1.0 / math.sqrt(sample_length)
    else:
        sigma_sr = math.sqrt(variance_adjustment / sample_length)

    if sigma_sr < 1e-12:
        return 1.0 if observed_sharpe > sr_benchmark else 0.0

    dsr = NormalDistribution.cdf((observed_sharpe - sr_benchmark) / sigma_sr)
    
    return float(dsr)


def minimum_backtest_length(
    observed_sharpe: float,
    n_trials: int
) -> float:
    """
    Computes the minimum sample length required for an observed Sharpe to be 
    statistically distinguishable from zero given the number of trials.

    Source: Bailey, Borwein, López de Prado & Zhu (2014), "Pseudo-Mathematics 
    and Financial Charlatanism" / "The Probability of Backtest Overfitting."

    Formula (assuming normality for the length requirement):
    T_min = ((sqrt(2 * ln(n_trials)) + z_{1-alpha}) / SR_obs)^2

    We use alpha = 0.05, so z_{1-alpha} is approximately 1.645.

    Args:
        observed_sharpe: The observed Sharpe ratio.
        n_trials: Number of independent trials conducted.

    Returns:
        The minimum sample length (T_min) as a float.

    Raises:
        ValueError: If n_trials <= 0, observed_sharpe <= 0, or any input is non-finite.
        TypeError: If any input is not a numeric type.
    """
    # Type checking
    for name, val in [("observed_sharpe", observed_sharpe), ("n_trials", n_trials)]:
        if not isinstance(val, (int, float)):
            raise TypeError(f"{name} must be a numeric type, got {type(val).__name__}")
        if not math.isfinite(val):
            raise ValueError(f"{name} must be a finite number")

    # Value validation
    if n_trials <= 0:
        raise ValueError("n_trials must be greater than 0")
    if observed_sharpe <= 0:
        raise ValueError("observed_sharpe must be positive to calculate minimum length for a positive signal")

    # alpha = 0.05 => z_{0.95} ~ 1.64485
    z_alpha = NormalDistribution.ppf(0.95)

    # T_min = ((sqrt(2 * ln(N)) + z_{1-alpha}) / SR_obs)^2   [docstring formula]
    # Monotonic in n_trials because ln is increasing: satisfies P4.
    numerator = math.sqrt(2.0 * math.log(n_trials)) + z_alpha
    return (numerator / observed_sharpe) ** 2


def evaluate(
    observed_sharpe: float,
    n_trials: int,
    sample_length: int,
    skewness: float,
    kurtosis: float
) -> dict:
    """
    Provides a comprehensive verdict on the observed Sharpe ratio.

    Args:
        observed_sharpe: The observed Sharpe ratio.
        n_trials: Number of independent trials conducted.
        sample_length: Number of observations in the sample.
        skewness: Skewness of the returns.
        kurtosis: Kurtosis of the returns.

    Returns:
        A JSON-serializable dictionary containing the deflated Sharpe, 
        minimum backtest length, and a verdict on whether the sample is too short.
    """
    dsr = deflated_sharpe_ratio(observed_sharpe, n_trials, sample_length, skewness, kurtosis)
    t_min = minimum_backtest_length(observed_sharpe, n_trials)

    return {
        "deflated_sharpe": dsr,
        "min_backtest_length": t_min,
        "sample_length": sample_length,
        "sample_too_short": sample_length < t_min,
        "n_trials": n_trials
    }

if __name__ == "__main__":
    # Example usage for inspection
    example_params = {
        "observed_sharpe": 1.5,
        "n_trials": 10,
        "sample_length": 250,
        "skewness": 0.1,
        "kurtosis": 3.5
    }
    try:
        result = evaluate(**example_params)
        print(json.dumps(result, indent=2))
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
