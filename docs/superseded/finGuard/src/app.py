"""
FinGuard - Financial Risk Management and Portfolio Simulation
Streamlit Application
"""

import streamlit as st
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Import FinGuard modules
from finguard.kelly import KellyCriterion
from finguard.drawdown import DrawdownManager
from finguard.simulator import MonteCarloSimulator
from finguard.visualizer import PortfolioVisualizer

# Set page config
st.set_page_config(
    page_title="FinGuard - Portfolio Risk Management",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize session state
if 'portfolio_data' not in st.session_state:
    st.session_state.portfolio_data = {}
if 'simulation_results' not in st.session_state:
    st.session_state.simulation_results = {}

def main():
    """Main application function."""
    
    # Header
    st.title("📊 FinGuard - Portfolio Risk Management & Simulation")
    st.markdown("---")
    
    # Sidebar for configuration
    with st.sidebar:
        st.header("Portfolio Configuration")
        
        # Portfolio setup
        initial_value = st.number_input(
            "Initial Portfolio Value ($)", 
            min_value=1000, 
            value=100000, 
            step=1000
        )
        
        # Asset configuration
        st.subheader("Asset Configuration")
        n_assets = st.selectbox("Number of Assets", [2, 3, 4, 5], index=1)
        
        asset_names = []
        expected_returns = []
        volatilities = []
        
        # Risk-free asset (first asset)
        asset_names.append("Risk-Free (T-Bills)")
        expected_returns.append(st.number_input("Risk-Free Rate (%)", value=2.0, step=0.1) / 100)
        volatilities.append(0.01)  # Very low volatility for risk-free
        
        # Risky assets
        risky_asset_names = ["Stocks", "Bonds", "Commodities", "Real Estate"]
        for i in range(n_assets - 1):
            asset_names.append(risky_asset_names[i])
            expected_returns.append(
                st.number_input(f"{risky_asset_names[i]} Expected Return (%)", 
                              value=8.0 + i*2, step=0.5) / 100
            )
            volatilities.append(
                st.number_input(f"{risky_asset_names[i]} Volatility (%)", 
                              value=15.0 + i*5, step=0.5) / 100
            )
        
        # Correlation matrix
        st.subheader("Asset Correlations")
        correlation_matrix = np.eye(n_assets)
        
        if n_assets > 1:
            for i in range(1, n_assets):
                for j in range(i+1, n_assets):
                    corr = st.slider(
                        f"Correlation {asset_names[i]} - {asset_names[j]}",
                        min_value=-1.0, max_value=1.0, value=0.3, step=0.1
                    )
                    correlation_matrix[i, j] = corr
                    correlation_matrix[j, i] = corr
        
        # Simulation parameters
        st.subheader("Simulation Parameters")
        n_simulations = st.selectbox("Number of Simulations", [100, 500, 1000, 2000], index=2)
        time_horizon = st.selectbox("Time Horizon (days)", [63, 126, 252, 504], index=2)
        max_drawdown = st.slider("Max Drawdown Limit (%)", 5, 50, 20, step=5) / 100
        
        # Run simulation button
        if st.button("🚀 Run Portfolio Simulation", type="primary"):
            run_simulation(
                initial_value, asset_names, expected_returns, 
                volatilities, correlation_matrix, n_simulations, 
                time_horizon, max_drawdown
            )
    
    # Main content area
    if st.session_state.portfolio_data:
        display_results()
    else:
        display_welcome()
    
    # Footer
    st.markdown("---")
    st.markdown(
        "**FinGuard** - A portfolio risk management tool using Kelly Criterion, "
        "drawdown control, and Monte Carlo simulations. For educational purposes only."
    )

def run_simulation(initial_value, asset_names, expected_returns, 
                  volatilities, correlation_matrix, n_simulations, 
                  time_horizon, max_drawdown):
    """Run the portfolio simulation."""
    
    with st.spinner("Running Monte Carlo simulation..."):
        # Convert to numpy arrays
        returns = np.array(expected_returns)
        vols = np.array(volatilities)
        
        # Build covariance matrix
        covariance = np.outer(vols, vols) * correlation_matrix
        
        # Initial weights (equal weight)
        initial_weights = np.ones(len(asset_names)) / len(asset_names)
        
        # Initialize components
        kelly = KellyCriterion()
        drawdown_manager = DrawdownManager(max_drawdown)
        simulator = MonteCarloSimulator(n_simulations, time_horizon)
        visualizer = PortfolioVisualizer()
        
        # Calculate Kelly-optimal weights
        kelly_weights = kelly.calculate_portfolio_kelly(returns, covariance)
        
        # Run Monte Carlo simulation
        simulation_results = simulator.simulate_portfolio_paths(
            initial_value, returns, covariance, kelly_weights
        )
        
        # Calculate statistics
        stats = simulator.calculate_statistics(simulation_results)
        
        # Calculate risk metrics
        risk_metrics = drawdown_manager.get_risk_metrics(
            simulation_results['portfolio_values'][0, :]
        )
        
        # Store results in session state
        st.session_state.portfolio_data = {
            'initial_value': initial_value,
            'asset_names': asset_names,
            'weights': kelly_weights,
            'returns': returns,
            'covariance': covariance,
            'statistics': stats,
            'risk_metrics': risk_metrics
        }
        
        st.session_state.simulation_results = simulation_results
        
        st.success("Simulation completed successfully!")

def display_welcome():
    """Display welcome message and instructions."""
    
    col1, col2, col3 = st.columns([1, 2, 1])
    
    with col2:
        st.markdown("""
        ## 🎯 Welcome to FinGuard
        
        **FinGuard** is a comprehensive portfolio risk management tool that combines:
        
        - **Kelly Criterion** for optimal portfolio allocation
        - **Drawdown Management** for capital preservation
        - **Monte Carlo Simulation** for stress testing
        
        ### 🚀 Getting Started
        
        1. **Configure your portfolio** in the sidebar
        2. **Set asset parameters** (returns, volatilities, correlations)
        3. **Run the simulation** to see results
        4. **Analyze risk metrics** and performance
        
        ### 📊 What You'll See
        
        - Portfolio evolution charts
        - Risk-adjusted performance metrics
        - Drawdown analysis
        - Monte Carlo simulation paths
        - Stress test scenarios
        
        **Configure your portfolio in the sidebar and click 'Run Portfolio Simulation' to begin!**
        """)

def display_results():
    """Display simulation results."""
    
    portfolio_data = st.session_state.portfolio_data
    simulation_results = st.session_state.simulation_results
    
    # Portfolio overview
    st.header("📈 Portfolio Overview")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric(
            "Initial Value", 
            f"${portfolio_data['initial_value']:,.0f}"
        )
    
    with col2:
        final_value = simulation_results['final_values'].mean()
        st.metric(
            "Expected Final Value", 
            f"${final_value:,.0f}"
        )
    
    with col3:
        total_return = (final_value - portfolio_data['initial_value']) / portfolio_data['initial_value']
        st.metric(
            "Expected Total Return", 
            f"{total_return:.1%}"
        )
    
    with col4:
        sharpe = portfolio_data['statistics']['sharpe_ratio']
        st.metric(
            "Sharpe Ratio", 
            f"{sharpe:.2f}"
        )
    
    # Charts
    st.header("📊 Portfolio Analysis")
    
    col1, col2 = st.columns(2)
    
    with col1:
        # Portfolio allocation
        fig_allocation = go.Figure(data=[go.Pie(
            labels=portfolio_data['asset_names'],
            values=portfolio_data['weights'],
            hole=0.3
        )])
        fig_allocation.update_layout(title="Optimal Asset Allocation (Kelly)")
        st.plotly_chart(fig_allocation, use_container_width=True)
    
    with col2:
        # Risk metrics
        risk_metrics = portfolio_data['risk_metrics']
        fig_risk = go.Figure()
        
        metrics = ['Volatility', 'Max Drawdown', 'VaR (95%)', 'Sharpe Ratio']
        values = [
            risk_metrics.get('volatility', 0),
            risk_metrics.get('max_drawdown', 0),
            risk_metrics.get('var_95', 0),
            risk_metrics.get('sharpe_ratio', 0)
        ]
        
        fig_risk.add_trace(go.Bar(x=metrics, y=values))
        fig_risk.update_layout(title="Risk Metrics")
        st.plotly_chart(fig_risk, use_container_width=True)
    
    # Monte Carlo simulation
    st.header("🎲 Monte Carlo Simulation")
    
    # Create simulation chart
    portfolio_values = simulation_results['portfolio_values']
    time_periods = np.arange(portfolio_values.shape[1])
    
    fig_mc = go.Figure()
    
    # Add individual paths (limited for clarity)
    for sim in range(min(50, portfolio_values.shape[0])):
        fig_mc.add_trace(go.Scatter(
            x=time_periods,
            y=portfolio_values[sim, :],
            mode='lines',
            line=dict(color='lightblue', width=1),
            opacity=0.2,
            showlegend=False
        ))
    
    # Add mean path
    mean_path = np.mean(portfolio_values, axis=0)
    fig_mc.add_trace(go.Scatter(
        x=time_periods,
        y=mean_path,
        mode='lines',
        name='Mean Path',
        line=dict(color='blue', width=3)
    ))
    
    # Add confidence intervals
    percentile_95 = np.percentile(portfolio_values, 95, axis=0)
    percentile_5 = np.percentile(portfolio_values, 5, axis=0)
    
    fig_mc.add_trace(go.Scatter(
        x=time_periods,
        y=percentile_95,
        mode='lines',
        name='95th Percentile',
        line=dict(color='green', width=2, dash='dash')
    ))
    
    fig_mc.add_trace(go.Scatter(
        x=time_periods,
        y=percentile_5,
        mode='lines',
        name='5th Percentile',
        line=dict(color='red', width=2, dash='dash'),
        fill='tonexty'
    ))
    
    fig_mc.update_layout(
        title="Portfolio Value Evolution (Monte Carlo)",
        xaxis_title="Time Period (Days)",
        yaxis_title="Portfolio Value ($)",
        height=500
    )
    
    st.plotly_chart(fig_mc, use_container_width=True)
    
    # Detailed statistics
    st.header("📋 Detailed Statistics")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Return Statistics")
        stats = portfolio_data['statistics']
        
        metrics_data = {
            "Mean Annual Return": f"{stats['mean_return']:.2%}",
            "Median Annual Return": f"{stats['median_return']:.2%}",
            "Volatility": f"{stats['volatility']:.2%}",
            "Min Return": f"{stats['min_return']:.2%}",
            "Max Return": f"{stats['max_return']:.2%}"
        }
        
        for metric, value in metrics_data.items():
            st.metric(metric, value)
    
    with col2:
        st.subheader("Risk Statistics")
        
        risk_data = {
            "Probability of Loss": f"{stats['probability_loss']:.1%}",
            "VaR (95%)": f"{stats['var_95']:.2%}",
            "VaR (99%)": f"{stats['var_99']:.2%}",
            "Expected Shortfall (95%)": f"{stats['expected_shortfall_95']:.2%}",
            "Upside Potential": f"{stats['upside_potential']:.2%}"
        }
        
        for metric, value in risk_data.items():
            st.metric(metric, value)
    
    # Drawdown analysis
    st.header("📉 Drawdown Analysis")
    
    # Calculate drawdown for mean path
    peak = np.maximum.accumulate(mean_path)
    drawdown = (mean_path - peak) / peak * 100
    
    fig_dd = go.Figure()
    fig_dd.add_trace(go.Scatter(
        x=time_periods,
        y=drawdown,
        mode='lines',
        name='Drawdown (%)',
        line=dict(color='red', width=2),
        fill='tonexty'
    ))
    
    fig_dd.add_hline(y=0, line_dash="dash", line_color="black")
    fig_dd.update_layout(
        title="Portfolio Drawdown Over Time",
        xaxis_title="Time Period (Days)",
        yaxis_title="Drawdown (%)",
        height=400
    )
    
    st.plotly_chart(fig_dd, use_container_width=True)
    
    # Export results
    st.header("💾 Export Results")
    
    if st.button("📊 Export Portfolio Data"):
        # Create summary DataFrame
        summary_data = {
            'Metric': [
                'Initial Value', 'Expected Final Value', 'Total Return',
                'Sharpe Ratio', 'Volatility', 'Max Drawdown', 'VaR (95%)'
            ],
            'Value': [
                f"${portfolio_data['initial_value']:,.0f}",
                f"${final_value:,.0f}",
                f"{total_return:.2%}",
                f"{sharpe:.2f}",
                f"{risk_metrics.get('volatility', 0):.2%}",
                f"{risk_metrics.get('max_drawdown', 0):.2%}",
                f"{risk_metrics.get('var_95', 0):.2%}"
            ]
        }
        
        df_summary = pd.DataFrame(summary_data)
        st.download_button(
            label="📥 Download Summary CSV",
            data=df_summary.to_csv(index=False),
            file_name="finguard_portfolio_summary.csv",
            mime="text/csv"
        )

if __name__ == "__main__":
    main()
