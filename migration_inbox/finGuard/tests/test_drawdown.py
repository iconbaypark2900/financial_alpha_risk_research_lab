"""
Unit tests for Drawdown Management module.
"""

import pytest
import numpy as np
from src.finguard.drawdown import DrawdownManager


class TestDrawdownManager:
    """Test cases for DrawdownManager class."""
    
    def setup_method(self):
        """Set up test fixtures."""
        self.drawdown_manager = DrawdownManager(max_drawdown=0.20)
    
    def test_calculate_drawdown_increasing_values(self):
        """Test drawdown calculation with increasing portfolio values."""
        portfolio_values = np.array([100, 110, 120, 130, 140])
        drawdown_series, max_drawdown = self.drawdown_manager.calculate_drawdown(portfolio_values)
        
        # No drawdowns should occur with increasing values
        assert np.all(drawdown_series == 0)
        assert max_drawdown == 0.0
    
    def test_calculate_drawdown_decreasing_values(self):
        """Test drawdown calculation with decreasing portfolio values."""
        portfolio_values = np.array([100, 90, 80, 70, 60])
        drawdown_series, max_drawdown = self.drawdown_manager.calculate_drawdown(portfolio_values)
        
        # Should have 40% maximum drawdown
        expected_max_drawdown = 0.4
        assert abs(max_drawdown - expected_max_drawdown) < 1e-10
        
        # First value should have 0% drawdown
        assert drawdown_series[0] == 0.0
        
        # Last value should have 40% drawdown
        assert abs(drawdown_series[-1] + expected_max_drawdown) < 1e-10
    
    def test_calculate_drawdown_mixed_values(self):
        """Test drawdown calculation with mixed portfolio values."""
        portfolio_values = np.array([100, 120, 110, 130, 125, 140])
        drawdown_series, max_drawdown = self.drawdown_manager.calculate_drawdown(portfolio_values)
        
        # Should have some drawdowns
        assert max_drawdown > 0.0
        
        # First value should have 0% drawdown
        assert drawdown_series[0] == 0.0
        
        # Check that drawdowns are non-positive
        assert np.all(drawdown_series <= 0)
    
    def test_calculate_drawdown_empty_array(self):
        """Test drawdown calculation with empty array."""
        portfolio_values = np.array([])
        drawdown_series, max_drawdown = self.drawdown_manager.calculate_drawdown(portfolio_values)
        
        assert len(drawdown_series) == 0
        assert max_drawdown == 0.0
    
    def test_calculate_drawdown_single_value(self):
        """Test drawdown calculation with single value."""
        portfolio_values = np.array([100])
        drawdown_series, max_drawdown = self.drawdown_manager.calculate_drawdown(portfolio_values)
        
        assert drawdown_series[0] == 0.0
        assert max_drawdown == 0.0
    
    def test_calculate_var_drawdown(self):
        """Test VaR-based drawdown calculation."""
        returns = np.array([0.01, -0.02, 0.03, -0.01, 0.02, -0.03, 0.01])
        var_95 = self.drawdown_manager.calculate_var_drawdown(returns, confidence_level=0.95)
        
        # VaR should be positive
        assert var_95 > 0.0
        
        # VaR should be less than or equal to maximum loss
        assert var_95 <= abs(np.min(returns))
    
    def test_calculate_var_drawdown_empty_returns(self):
        """Test VaR calculation with empty returns array."""
        returns = np.array([])
        var_95 = self.drawdown_manager.calculate_var_drawdown(returns)
        
        assert var_95 == 0.0
    
    def test_apply_drawdown_control_no_violation(self):
        """Test drawdown control when no violation occurs."""
        current_value = 100
        target_allocation = np.array([0.3, 0.4, 0.3])
        current_allocation = np.array([0.3, 0.4, 0.3])
        
        adjusted = self.drawdown_manager.apply_drawdown_control(
            current_value, target_allocation, current_allocation
        )
        
        # Should return original allocation
        assert np.allclose(adjusted, target_allocation)
    
    def test_apply_drawdown_control_with_violation(self):
        """Test drawdown control when violation occurs."""
        # Set up a scenario where drawdown limit is exceeded
        self.drawdown_manager.peak_value = 120
        current_value = 90  # 25% drawdown (exceeds 20% limit)
        
        target_allocation = np.array([0.2, 0.5, 0.3])  # Risk-free, risky, risky
        current_allocation = np.array([0.2, 0.5, 0.3])
        
        adjusted = self.drawdown_manager.apply_drawdown_control(
            current_value, target_allocation, current_allocation
        )
        
        # Should increase allocation to risk-free asset (first asset)
        assert adjusted[0] > target_allocation[0]
        
        # Should reduce allocation to risky assets
        assert np.sum(adjusted[1:]) < np.sum(target_allocation[1:])
        
        # Weights should still sum to 1
        assert abs(np.sum(adjusted) - 1.0) < 1e-10
    
    def test_calculate_recovery_time(self):
        """Test recovery time calculation."""
        drawdown = 0.20  # 20% drawdown
        expected_return = 0.10  # 10% annual return
        
        recovery_time = self.drawdown_manager.calculate_recovery_time(drawdown, expected_return)
        
        # Recovery time should be positive
        assert recovery_time > 0.0
        
        # Recovery time should be reasonable (around 2.3 years for 20% DD, 10% return)
        expected_time = np.log(1.2) / np.log(1.1)
        assert abs(recovery_time - expected_time) < 0.1
    
    def test_calculate_recovery_time_zero_return(self):
        """Test recovery time calculation with zero return."""
        drawdown = 0.20
        expected_return = 0.0
        
        recovery_time = self.drawdown_manager.calculate_recovery_time(drawdown, expected_return)
        
        # Should return infinity for zero return
        assert recovery_time == float('inf')
    
    def test_calculate_ulcer_index(self):
        """Test Ulcer Index calculation."""
        returns = np.array([0.01, -0.02, 0.03, -0.01, 0.02, -0.03, 0.01])
        ulcer_index = self.drawdown_manager.calculate_ulcer_index(returns)
        
        # Ulcer index should be positive
        assert ulcer_index > 0.0
        
        # Ulcer index should be reasonable for given returns
        assert ulcer_index < 0.1  # Should be small for these returns
    
    def test_calculate_ulcer_index_empty_returns(self):
        """Test Ulcer Index calculation with empty returns array."""
        returns = np.array([])
        ulcer_index = self.drawdown_manager.calculate_ulcer_index(returns)
        
        assert ulcer_index == 0.0
    
    def test_get_risk_metrics(self):
        """Test comprehensive risk metrics calculation."""
        portfolio_values = np.array([100, 105, 110, 108, 115, 112, 120])
        risk_metrics = self.drawdown_manager.get_risk_metrics(portfolio_values)
        
        # Should return a dictionary with expected keys
        expected_keys = [
            'max_drawdown', 'current_drawdown', 'volatility', 
            'sharpe_ratio', 'var_95', 'var_99', 'ulcer_index'
        ]
        
        for key in expected_keys:
            assert key in risk_metrics
        
        # Check that values are reasonable
        assert risk_metrics['max_drawdown'] >= 0.0
        assert risk_metrics['volatility'] >= 0.0
        assert risk_metrics['ulcer_index'] >= 0.0
    
    def test_get_risk_metrics_insufficient_data(self):
        """Test risk metrics with insufficient data."""
        portfolio_values = np.array([100])
        risk_metrics = self.drawdown_manager.get_risk_metrics(portfolio_values)
        
        # Should return empty dictionary for insufficient data
        assert risk_metrics == {}


if __name__ == "__main__":
    pytest.main([__file__])
