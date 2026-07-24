"""
Kelly Criterion implementation for optimal portfolio allocation.

Imported from finGuard (migration_inbox/finGuard/src/finguard/kelly.py).
"""

import numpy as np
from typing import Dict, List, Tuple


class KellyCriterion:
    """Implements Kelly Criterion for optimal bet sizing."""

    def __init__(self):
        self.risk_free_rate = 0.02  # Default 2% risk-free rate

    def calculate_kelly_fraction(self, win_prob: float, win_loss_ratio: float) -> float:
        """
        Calculate optimal Kelly fraction for a single bet.

        Args:
            win_prob: Probability of winning (0 to 1)
            win_loss_ratio: Ratio of win amount to loss amount

        Returns:
            Optimal fraction of capital to bet
        """
        if not 0 <= win_prob <= 1:
            raise ValueError("win_prob must be between 0 and 1")

        if win_loss_ratio <= 0:
            raise ValueError("win_loss_ratio must be positive")

        # Kelly formula: f = (bp - q) / b
        # where b = win_loss_ratio, p = win_prob, q = 1 - p
        kelly_fraction = (win_prob * win_loss_ratio - (1 - win_prob)) / win_loss_ratio

        # Cap at 100% of capital (no leverage)
        return max(0, min(kelly_fraction, 1.0))

    def calculate_portfolio_kelly(self, returns: np.ndarray,
                                  covariance: np.ndarray) -> np.ndarray:
        """
        Calculate Kelly-optimal portfolio weights.

        Args:
            returns: Expected returns for each asset
            covariance: Covariance matrix of returns

        Returns:
            Optimal portfolio weights
        """
        if returns.shape[0] != covariance.shape[0]:
            raise ValueError("Returns and covariance dimensions must match")

        # Kelly formula for portfolio: w = Σ^(-1) * μ
        try:
            inv_cov = np.linalg.inv(covariance)
            weights = inv_cov @ returns

            # Normalize weights to sum to 1
            weights = weights / np.sum(weights)

            # Ensure no negative weights (no short selling)
            weights = np.maximum(weights, 0)
            weights = weights / np.sum(weights)

            return weights
        except np.linalg.LinAlgError:
            # Fallback to equal weights if matrix is singular
            n_assets = len(returns)
            return np.ones(n_assets) / n_assets

    def kelly_leverage_adjustment(self, kelly_fraction: float,
                                  max_leverage: float = 2.0) -> float:
        """
        Adjust Kelly fraction to limit leverage.

        Args:
            kelly_fraction: Raw Kelly fraction
            max_leverage: Maximum allowed leverage

        Returns:
            Adjusted Kelly fraction
        """
        return min(kelly_fraction, max_leverage)

    def calculate_growth_rate(self, kelly_fraction: float,
                               win_prob: float, win_loss_ratio: float) -> float:
        """
        Calculate expected growth rate using Kelly fraction.

        Args:
            kelly_fraction: Fraction of capital to bet
            win_prob: Probability of winning
            win_loss_ratio: Ratio of win to loss

        Returns:
            Expected growth rate per bet
        """
        q = 1 - win_prob
        growth_rate = win_prob * np.log(1 + kelly_fraction * win_loss_ratio) + \
                      q * np.log(1 - kelly_fraction)
        return growth_rate
