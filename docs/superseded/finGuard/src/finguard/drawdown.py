"""
Drawdown management for capital preservation and risk control.
"""

import numpy as np
from typing import Tuple, List, Optional


class DrawdownManager:
    """Manages portfolio drawdowns and implements risk controls."""
    
    def __init__(self, max_drawdown: float = 0.20):
        """
        Initialize drawdown manager.
        
        Args:
            max_drawdown: Maximum allowed drawdown (default 20%)
        """
        self.max_drawdown = max_drawdown
        self.peak_value = 0.0
        self.current_drawdown = 0.0
    
    def calculate_drawdown(self, portfolio_values: np.ndarray) -> Tuple[np.ndarray, float]:
        """
        Calculate drawdown series and maximum drawdown.
        
        Args:
            portfolio_values: Array of portfolio values over time
            
        Returns:
            Tuple of (drawdown_series, max_drawdown)
        """
        if len(portfolio_values) == 0:
            return np.array([]), 0.0
        
        # Calculate running peak
        peak = np.maximum.accumulate(portfolio_values)
        
        # Calculate drawdown series
        drawdown_series = (portfolio_values - peak) / peak
        
        # Calculate maximum drawdown
        max_dd = np.min(drawdown_series)
        
        return drawdown_series, abs(max_dd)
    
    def calculate_var_drawdown(self, returns: np.ndarray, 
                              confidence_level: float = 0.95) -> float:
        """
        Calculate Value at Risk (VaR) based drawdown limit.
        
        Args:
            returns: Array of portfolio returns
            confidence_level: Confidence level for VaR (default 95%)
            
        Returns:
            VaR-based drawdown limit
        """
        if len(returns) == 0:
            return 0.0
        
        # Calculate VaR at specified confidence level
        var_percentile = (1 - confidence_level) * 100
        var = np.percentile(returns, var_percentile)
        
        # Convert to positive drawdown limit
        return abs(var)
    
    def apply_drawdown_control(self, current_value: float, 
                              target_allocation: np.ndarray,
                              current_allocation: np.ndarray) -> np.ndarray:
        """
        Apply drawdown control by adjusting portfolio allocation.
        
        Args:
            current_value: Current portfolio value
            target_allocation: Target allocation weights
            current_allocation: Current allocation weights
            
        Returns:
            Adjusted allocation weights
        """
        # Update peak value
        if current_value > self.peak_value:
            self.peak_value = current_value
        
        # Calculate current drawdown
        if self.peak_value > 0:
            self.current_drawdown = (current_value - self.peak_value) / self.peak_value
        else:
            self.current_drawdown = 0.0
        
        # If drawdown exceeds limit, reduce risk
        if abs(self.current_drawdown) > self.max_drawdown:
            # Reduce allocation to risky assets (assuming first asset is risk-free)
            risk_reduction = min(0.5, abs(self.current_drawdown) - self.max_drawdown)
            
            # Increase allocation to risk-free asset (first asset)
            adjusted_allocation = target_allocation.copy()
            adjusted_allocation[0] += risk_reduction
            
            # Reduce other allocations proportionally
            if len(adjusted_allocation) > 1:
                risk_assets = adjusted_allocation[1:]
                total_risk_weight = np.sum(risk_assets)
                if total_risk_weight > 0:
                    risk_assets = risk_assets * (1 - risk_reduction)
                    adjusted_allocation[1:] = risk_assets
            
            # Normalize weights
            adjusted_allocation = adjusted_allocation / np.sum(adjusted_allocation)
            return adjusted_allocation
        
        return target_allocation
    
    def calculate_recovery_time(self, drawdown: float, 
                               expected_return: float) -> float:
        """
        Calculate expected time to recover from a drawdown.
        
        Args:
            drawdown: Current drawdown (as positive percentage)
            expected_return: Expected annual return
            
        Returns:
            Expected recovery time in years
        """
        if expected_return <= 0:
            return float('inf')
        
        # Simple recovery time calculation
        # Time = log(1 + drawdown) / log(1 + expected_return)
        recovery_time = np.log(1 + drawdown) / np.log(1 + expected_return)
        return max(0, recovery_time)
    
    def calculate_ulcer_index(self, returns: np.ndarray) -> float:
        """
        Calculate Ulcer Index - a measure of downside risk.
        
        Args:
            returns: Array of portfolio returns
            
        Returns:
            Ulcer Index value
        """
        if len(returns) == 0:
            return 0.0
        
        # Calculate cumulative returns
        cumulative = np.cumprod(1 + returns)
        
        # Calculate drawdowns
        peak = np.maximum.accumulate(cumulative)
        drawdowns = (cumulative - peak) / peak
        
        # Calculate Ulcer Index (root mean square of drawdowns)
        ulcer_index = np.sqrt(np.mean(drawdowns ** 2))
        return abs(ulcer_index)
    
    def get_risk_metrics(self, portfolio_values: np.ndarray) -> dict:
        """
        Get comprehensive risk metrics including drawdown analysis.
        
        Args:
            portfolio_values: Array of portfolio values over time
            
        Returns:
            Dictionary of risk metrics
        """
        if len(portfolio_values) < 2:
            return {}
        
        # Calculate returns
        returns = np.diff(portfolio_values) / portfolio_values[:-1]
        
        # Calculate drawdown metrics
        drawdown_series, max_drawdown = self.calculate_drawdown(portfolio_values)
        
        # Calculate other risk metrics
        volatility = np.std(returns) * np.sqrt(252)  # Annualized
        sharpe_ratio = np.mean(returns) / np.std(returns) if np.std(returns) > 0 else 0
        
        # Calculate VaR
        var_95 = self.calculate_var_drawdown(returns, 0.95)
        var_99 = self.calculate_var_drawdown(returns, 0.99)
        
        # Calculate Ulcer Index
        ulcer_index = self.calculate_ulcer_index(returns)
        
        return {
            'max_drawdown': max_drawdown,
            'current_drawdown': self.current_drawdown,
            'volatility': volatility,
            'sharpe_ratio': sharpe_ratio,
            'var_95': var_95,
            'var_99': var_99,
            'ulcer_index': ulcer_index,
            'drawdown_series': drawdown_series
        }
