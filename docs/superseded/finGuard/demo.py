#!/usr/bin/env python3
"""
Demo script for FinGuard - demonstrates core functionality.
"""

import numpy as np
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from finguard.kelly import KellyCriterion
from finguard.drawdown import DrawdownManager
from finguard.simulator import MonteCarloSimulator

def main():
    """Run FinGuard demo."""
    
    print("🚀 FinGuard Demo - Portfolio Risk Management")
    print("=" * 50)
    
    # Initialize components
    kelly = KellyCriterion()
    drawdown_manager = DrawdownManager(max_drawdown=0.20)
    simulator = MonteCarloSimulator(n_simulations=100, time_horizon=252)
    
    # Sample portfolio data
    print("\n📊 Portfolio Configuration:")
    asset_names = ["Risk-Free (T-Bills)", "Stocks", "Bonds"]
    expected_returns = np.array([0.02, 0.08, 0.05])  # 2%, 8%, 5%
    volatilities = np.array([0.01, 0.15, 0.08])      # 1%, 15%, 8%
    
    # Build correlation matrix
    correlation_matrix = np.array([
        [1.0, 0.0, 0.0],   # Risk-free uncorrelated
        [0.0, 1.0, 0.3],   # Stocks and bonds slightly correlated
        [0.0, 0.3, 1.0]
    ])
    
    # Build covariance matrix
    covariance = np.outer(volatilities, volatilities) * correlation_matrix
    
    print(f"Assets: {asset_names}")
    print(f"Expected Returns: {[f'{r:.1%}' for r in expected_returns]}")
    print(f"Volatilities: {[f'{v:.1%}' for v in volatilities]}")
    
    # Calculate Kelly-optimal weights
    print("\n🎯 Kelly Criterion Optimization:")
    kelly_weights = kelly.calculate_portfolio_kelly(expected_returns, covariance)
    
    for i, (name, weight) in enumerate(zip(asset_names, kelly_weights)):
        print(f"  {name}: {weight:.1%}")
    
    # Run Monte Carlo simulation
    print("\n🎲 Running Monte Carlo Simulation...")
    initial_value = 100000
    
    simulation_results = simulator.simulate_portfolio_paths(
        initial_value, expected_returns, covariance, kelly_weights
    )
    
    # Calculate statistics
    stats = simulator.calculate_statistics(simulation_results)
    
    print("\n📈 Simulation Results:")
    print(f"  Expected Annual Return: {stats['mean_return']:.1%}")
    print(f"  Annual Volatility: {stats['volatility']:.1%}")
    print(f"  Sharpe Ratio: {stats['sharpe_ratio']:.2f}")
    print(f"  Max Drawdown (95% CI): {stats['max_drawdown_95']:.1%}")
    print(f"  Probability of Loss: {stats['probability_loss']:.1%}")
    
    # Calculate risk metrics
    print("\n⚠️  Risk Analysis:")
    portfolio_values = simulation_results['portfolio_values'][0, :]
    risk_metrics = drawdown_manager.get_risk_metrics(portfolio_values)
    
    print(f"  Current Drawdown: {risk_metrics.get('current_drawdown', 0):.1%}")
    print(f"  VaR (95%): {risk_metrics.get('var_95', 0):.1%}")
    print(f"  Ulcer Index: {risk_metrics.get('ulcer_index', 0):.3f}")
    
    # Stress testing
    print("\n🔥 Stress Testing:")
    stress_scenarios = simulator.generate_sample_scenarios()
    
    for scenario_name, scenario_params in stress_scenarios.items():
        print(f"  {scenario_name}: {scenario_params['description']}")
    
    print("\n✅ Demo completed successfully!")
    print("\nTo run the full Streamlit app:")
    print("  streamlit run src/app.py")

if __name__ == "__main__":
    main()
