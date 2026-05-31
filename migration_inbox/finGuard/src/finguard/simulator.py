"""
Monte Carlo simulation for portfolio stress testing and scenario analysis.
"""

import numpy as np
from typing import Dict, List, Tuple, Optional
from .kelly import KellyCriterion
from .drawdown import DrawdownManager


class MonteCarloSimulator:
    """Monte Carlo simulation for portfolio analysis."""
    
    def __init__(self, n_simulations: int = 1000, time_horizon: int = 252):
        """
        Initialize Monte Carlo simulator.
        
        Args:
            n_simulations: Number of simulation paths
            time_horizon: Time horizon in days (default 252 = 1 year)
        """
        self.n_simulations = n_simulations
        self.time_horizon = time_horizon
        self.kelly = KellyCriterion()
        self.drawdown_manager = DrawdownManager()
    
    def simulate_portfolio_paths(self, initial_value: float,
                               returns: np.ndarray,
                               covariance: np.ndarray,
                               weights: np.ndarray,
                               rebalance_frequency: int = 22) -> Dict:
        """
        Simulate portfolio paths using Monte Carlo.
        
        Args:
            initial_value: Initial portfolio value
            returns: Expected returns for each asset
            covariance: Covariance matrix of returns
            weights: Initial portfolio weights
            rebalance_frequency: Rebalancing frequency in days
            
        Returns:
            Dictionary containing simulation results
        """
        # Generate random returns using multivariate normal distribution
        random_returns = np.random.multivariate_normal(
            returns, covariance, 
            size=(self.n_simulations, self.time_horizon)
        )
        
        # Initialize portfolio values
        portfolio_values = np.zeros((self.n_simulations, self.time_horizon + 1))
        portfolio_values[:, 0] = initial_value
        
        # Track allocations over time
        allocations = np.zeros((self.n_simulations, self.time_horizon + 1, len(weights)))
        allocations[:, 0, :] = weights
        
        # Simulate portfolio evolution
        for sim in range(self.n_simulations):
            current_weights = weights.copy()
            
            for t in range(self.time_horizon):
                # Calculate daily return
                daily_return = np.sum(current_weights * random_returns[sim, t])
                
                # Update portfolio value
                portfolio_values[sim, t + 1] = portfolio_values[sim, t] * (1 + daily_return)
                
                # Rebalance if needed
                if t % rebalance_frequency == 0 and t > 0:
                    # Apply Kelly optimization
                    current_returns = random_returns[sim, max(0, t-22):t+1]
                    if len(current_returns) > 0:
                        # Update covariance estimate
                        current_cov = np.cov(current_returns.T)
                        # Apply Kelly weights
                        kelly_weights = self.kelly.calculate_portfolio_kelly(
                            returns, current_cov
                        )
                        current_weights = kelly_weights
                
                # Apply drawdown control
                current_value = portfolio_values[sim, t + 1]
                current_weights = self.drawdown_manager.apply_drawdown_control(
                    current_value, current_weights, current_weights
                )
                
                # Store current allocation
                allocations[sim, t + 1, :] = current_weights
        
        return {
            'portfolio_values': portfolio_values,
            'allocations': allocations,
            'returns': random_returns,
            'final_values': portfolio_values[:, -1],
            'max_drawdowns': self._calculate_max_drawdowns(portfolio_values)
        }
    
    def _calculate_max_drawdowns(self, portfolio_values: np.ndarray) -> np.ndarray:
        """Calculate maximum drawdown for each simulation path."""
        max_drawdowns = np.zeros(self.n_simulations)
        
        for sim in range(self.n_simulations):
            _, max_dd = self.drawdown_manager.calculate_drawdown(portfolio_values[sim, :])
            max_drawdowns[sim] = max_dd
        
        return max_drawdowns
    
    def calculate_statistics(self, simulation_results: Dict) -> Dict:
        """
        Calculate comprehensive statistics from simulation results.
        
        Args:
            simulation_results: Results from simulate_portfolio_paths
            
        Returns:
            Dictionary of statistical measures
        """
        final_values = simulation_results['final_values']
        max_drawdowns = simulation_results['max_drawdowns']
        
        # Calculate return statistics
        total_returns = (final_values - final_values[0]) / final_values[0]
        annualized_returns = (1 + total_returns) ** (252 / self.time_horizon) - 1
        
        # Calculate risk metrics
        volatility = np.std(annualized_returns)
        sharpe_ratio = np.mean(annualized_returns) / volatility if volatility > 0 else 0
        
        # Calculate drawdown statistics
        avg_max_drawdown = np.mean(max_drawdowns)
        max_drawdown_95 = np.percentile(max_drawdowns, 95)
        max_drawdown_99 = np.percentile(max_drawdowns, 99)
        
        # Calculate value at risk
        var_95 = np.percentile(total_returns, 5)
        var_99 = np.percentile(total_returns, 1)
        
        # Calculate expected shortfall (conditional VaR)
        es_95 = np.mean(total_returns[total_returns <= var_95])
        es_99 = np.mean(total_returns[total_returns <= var_99])
        
        # Calculate probability of loss
        prob_loss = np.mean(total_returns < 0)
        
        # Calculate upside potential
        upside_potential = np.mean(np.maximum(total_returns, 0))
        
        return {
            'mean_return': np.mean(annualized_returns),
            'median_return': np.median(annualized_returns),
            'volatility': volatility,
            'sharpe_ratio': sharpe_ratio,
            'avg_max_drawdown': avg_max_drawdown,
            'max_drawdown_95': max_drawdown_95,
            'max_drawdown_99': max_drawdown_99,
            'var_95': var_95,
            'var_99': var_99,
            'expected_shortfall_95': es_95,
            'expected_shortfall_99': es_99,
            'probability_loss': prob_loss,
            'upside_potential': upside_potential,
            'min_return': np.min(annualized_returns),
            'max_return': np.max(annualized_returns)
        }
    
    def stress_test(self, initial_value: float,
                   returns: np.ndarray,
                   covariance: np.ndarray,
                   weights: np.ndarray,
                   stress_scenarios: Dict) -> Dict:
        """
        Perform stress testing under various market scenarios.
        
        Args:
            initial_value: Initial portfolio value
            returns: Expected returns for each asset
            covariance: Covariance matrix of returns
            weights: Initial portfolio weights
            stress_scenarios: Dictionary of stress scenarios
            
        Returns:
            Dictionary containing stress test results
        """
        stress_results = {}
        
        for scenario_name, scenario_params in stress_scenarios.items():
            # Apply stress scenario
            stressed_returns = returns * scenario_params.get('return_multiplier', 1.0)
            stressed_covariance = covariance * scenario_params.get('volatility_multiplier', 1.0)
            
            # Run simulation with stressed parameters
            scenario_results = self.simulate_portfolio_paths(
                initial_value, stressed_returns, stressed_covariance, weights
            )
            
            # Calculate statistics
            scenario_stats = self.calculate_statistics(scenario_results)
            stress_results[scenario_name] = {
                'statistics': scenario_stats,
                'final_values': scenario_results['final_values'],
                'max_drawdowns': scenario_results['max_drawdowns']
            }
        
        return stress_results
    
    def generate_sample_scenarios(self) -> Dict:
        """Generate sample stress test scenarios."""
        return {
            'market_crash': {
                'return_multiplier': -2.0,
                'volatility_multiplier': 3.0,
                'description': 'Severe market downturn with increased volatility'
            },
            'recession': {
                'return_multiplier': -1.5,
                'volatility_multiplier': 2.0,
                'description': 'Economic recession scenario'
            },
            'high_volatility': {
                'return_multiplier': 0.8,
                'volatility_multiplier': 2.5,
                'description': 'High volatility period with reduced returns'
            },
            'bull_market': {
                'return_multiplier': 1.5,
                'volatility_multiplier': 0.8,
                'description': 'Strong bull market with low volatility'
            }
        }
