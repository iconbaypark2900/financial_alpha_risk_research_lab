"""
Unit tests for Kelly Criterion module.

Ported from finGuard (migration_inbox/finGuard/tests/test_kelly.py).
"""

import pytest
import numpy as np
from src.portfolio_risk_service.kelly import KellyCriterion


class TestKellyCriterion:
    """Test cases for KellyCriterion class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.kelly = KellyCriterion()

    def test_calculate_kelly_fraction_valid_inputs(self):
        """Test Kelly fraction calculation with valid inputs."""
        kelly_fraction = self.kelly.calculate_kelly_fraction(0.6, 2.0)
        expected = (0.6 * 2.0 - 0.4) / 2.0
        assert abs(kelly_fraction - expected) < 1e-10

    def test_calculate_kelly_fraction_edge_cases(self):
        """Test Kelly fraction calculation with edge cases."""
        kelly_fraction = self.kelly.calculate_kelly_fraction(1.0, 1.0)
        assert kelly_fraction == 1.0

        kelly_fraction = self.kelly.calculate_kelly_fraction(0.0, 1.0)
        assert kelly_fraction == 0.0

        kelly_fraction = self.kelly.calculate_kelly_fraction(0.5, 1.0)
        assert abs(kelly_fraction) < 1e-10

    def test_calculate_kelly_fraction_invalid_inputs(self):
        """Test Kelly fraction calculation with invalid inputs."""
        with pytest.raises(ValueError):
            self.kelly.calculate_kelly_fraction(1.5, 1.0)

        with pytest.raises(ValueError):
            self.kelly.calculate_kelly_fraction(-0.1, 1.0)

        with pytest.raises(ValueError):
            self.kelly.calculate_kelly_fraction(0.6, 0.0)

        with pytest.raises(ValueError):
            self.kelly.calculate_kelly_fraction(0.6, -1.0)

    def test_calculate_portfolio_kelly_valid_inputs(self):
        """Test portfolio Kelly calculation with valid inputs."""
        returns = np.array([0.05, 0.08, 0.12])
        covariance = np.array([
            [0.04, 0.01, 0.02],
            [0.01, 0.09, 0.03],
            [0.02, 0.03, 0.16]
        ])

        weights = self.kelly.calculate_portfolio_kelly(returns, covariance)

        assert abs(np.sum(weights) - 1.0) < 1e-10
        assert np.all(weights >= 0)
        assert np.all(weights <= 1.0)

    def test_calculate_portfolio_kelly_singular_matrix(self):
        """Test portfolio Kelly calculation with singular covariance matrix."""
        returns = np.array([0.05, 0.08])
        covariance = np.array([[1.0, 1.0], [1.0, 1.0]])

        weights = self.kelly.calculate_portfolio_kelly(returns, covariance)

        expected_weights = np.array([0.5, 0.5])
        assert np.allclose(weights, expected_weights)

    def test_calculate_portfolio_kelly_dimension_mismatch(self):
        """Test portfolio Kelly calculation with dimension mismatch."""
        returns = np.array([0.05, 0.08])
        covariance = np.array([[0.04, 0.01], [0.01, 0.09], [0.02, 0.03]])

        with pytest.raises(ValueError):
            self.kelly.calculate_portfolio_kelly(returns, covariance)

    def test_kelly_leverage_adjustment(self):
        """Test Kelly leverage adjustment."""
        adjusted = self.kelly.kelly_leverage_adjustment(0.8, max_leverage=2.0)
        assert adjusted == 0.8

        adjusted = self.kelly.kelly_leverage_adjustment(2.5, max_leverage=2.0)
        assert adjusted == 2.0

    def test_calculate_growth_rate(self):
        """Test growth rate calculation."""
        kelly_fraction = 0.5
        win_prob = 0.6
        win_loss_ratio = 2.0

        growth_rate = self.kelly.calculate_growth_rate(kelly_fraction, win_prob, win_loss_ratio)

        assert growth_rate > 0

        growth_rate_zero = self.kelly.calculate_growth_rate(0.0, win_prob, win_loss_ratio)
        assert growth_rate_zero == 0.0


if __name__ == "__main__":
    pytest.main([__file__])
