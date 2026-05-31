"""
Visualization module for FinGuard portfolio analysis.
"""

import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import numpy as np
import pandas as pd
from typing import Dict, List, Optional


class PortfolioVisualizer:
    """Creates interactive visualizations for portfolio analysis."""
    
    def __init__(self):
        """Initialize the visualizer."""
        pass
    
    def create_portfolio_evolution_chart(self, portfolio_values: np.ndarray,
                                       time_periods: Optional[np.ndarray] = None,
                                       title: str = "Portfolio Evolution") -> go.Figure:
        """
        Create portfolio evolution chart.
        
        Args:
            portfolio_values: Array of portfolio values over time
            time_periods: Optional time periods for x-axis
            title: Chart title
            
        Returns:
            Plotly figure object
        """
        if time_periods is None:
            time_periods = np.arange(len(portfolio_values))
        
        fig = go.Figure()
        
        # Add portfolio value line
        fig.add_trace(go.Scatter(
            x=time_periods,
            y=portfolio_values,
            mode='lines',
            name='Portfolio Value',
            line=dict(color='blue', width=2)
        ))
        
        # Add peak line
        peak_values = np.maximum.accumulate(portfolio_values)
        fig.add_trace(go.Scatter(
            x=time_periods,
            y=peak_values,
            mode='lines',
            name='Peak Value',
            line=dict(color='green', width=1, dash='dash')
        ))
        
        fig.update_layout(
            title=title,
            xaxis_title="Time Period",
            yaxis_title="Portfolio Value ($)",
            hovermode='x unified',
            showlegend=True
        )
        
        return fig
    
    def create_drawdown_chart(self, portfolio_values: np.ndarray,
                             time_periods: Optional[np.ndarray] = None,
                             title: str = "Portfolio Drawdown") -> go.Figure:
        """
        Create drawdown chart.
        
        Args:
            portfolio_values: Array of portfolio values over time
            time_periods: Optional time periods for x-axis
            title: Chart title
            
        Returns:
            Plotly figure object
        """
        if time_periods is None:
            time_periods = np.arange(len(portfolio_values))
        
        # Calculate drawdown
        peak = np.maximum.accumulate(portfolio_values)
        drawdown = (portfolio_values - peak) / peak * 100
        
        fig = go.Figure()
        
        fig.add_trace(go.Scatter(
            x=time_periods,
            y=drawdown,
            mode='lines',
            name='Drawdown (%)',
            line=dict(color='red', width=2),
            fill='tonexty'
        ))
        
        # Add zero line
        fig.add_hline(y=0, line_dash="dash", line_color="black")
        
        fig.update_layout(
            title=title,
            xaxis_title="Time Period",
            yaxis_title="Drawdown (%)",
            hovermode='x unified',
            showlegend=True
        )
        
        return fig
    
    def create_monte_carlo_chart(self, simulation_results: Dict,
                                time_periods: Optional[np.ndarray] = None,
                                title: str = "Monte Carlo Simulation") -> go.Figure:
        """
        Create Monte Carlo simulation chart.
        
        Args:
            simulation_results: Results from Monte Carlo simulation
            time_periods: Optional time periods for x-axis
            title: Chart title
            
        Returns:
            Plotly figure object
        """
        portfolio_values = simulation_results['portfolio_values']
        n_simulations, n_periods = portfolio_values.shape
        
        if time_periods is None:
            time_periods = np.arange(n_periods)
        
        fig = go.Figure()
        
        # Add individual simulation paths (with low opacity)
        for sim in range(min(100, n_simulations)):  # Limit to 100 paths for clarity
            fig.add_trace(go.Scatter(
                x=time_periods,
                y=portfolio_values[sim, :],
                mode='lines',
                line=dict(color='lightblue', width=1, opacity=0.3),
                showlegend=False
            ))
        
        # Add mean path
        mean_path = np.mean(portfolio_values, axis=0)
        fig.add_trace(go.Scatter(
            x=time_periods,
            y=mean_path,
            mode='lines',
            name='Mean Path',
            line=dict(color='blue', width=3)
        ))
        
        # Add confidence intervals
        percentile_95 = np.percentile(portfolio_values, 95, axis=0)
        percentile_5 = np.percentile(portfolio_values, 5, axis=0)
        
        fig.add_trace(go.Scatter(
            x=time_periods,
            y=percentile_95,
            mode='lines',
            name='95th Percentile',
            line=dict(color='green', width=2, dash='dash')
        ))
        
        fig.add_trace(go.Scatter(
            x=time_periods,
            y=percentile_5,
            mode='lines',
            name='5th Percentile',
            line=dict(color='red', width=2, dash='dash'),
            fill='tonexty'
        ))
        
        fig.update_layout(
            title=title,
            xaxis_title="Time Period",
            yaxis_title="Portfolio Value ($)",
            hovermode='x unified',
            showlegend=True
        )
        
        return fig
    
    def create_risk_metrics_dashboard(self, risk_metrics: Dict,
                                    title: str = "Risk Metrics Dashboard") -> go.Figure:
        """
        Create risk metrics dashboard.
        
        Args:
            risk_metrics: Dictionary of risk metrics
            title: Dashboard title
            
        Returns:
            Plotly figure object
        """
        # Create subplots
        fig = make_subplots(
            rows=2, cols=2,
            subplot_titles=('Return Distribution', 'Drawdown Analysis', 
                          'Risk Metrics', 'Performance Summary'),
            specs=[[{"type": "histogram"}, {"type": "bar"}],
                   [{"type": "indicator"}, {"type": "table"}]]
        )
        
        # Return distribution
        if 'returns' in risk_metrics:
            fig.add_trace(
                go.Histogram(x=risk_metrics['returns'], name='Returns'),
                row=1, col=1
            )
        
        # Drawdown analysis
        if 'drawdown_series' in risk_metrics:
            fig.add_trace(
                go.Bar(x=['Max DD', 'Current DD'], 
                      y=[risk_metrics.get('max_drawdown', 0), 
                         risk_metrics.get('current_drawdown', 0)],
                      name='Drawdowns'),
                row=1, col=2
            )
        
        # Risk metrics gauge
        if 'sharpe_ratio' in risk_metrics:
            fig.add_trace(
                go.Indicator(
                    mode="gauge+number+delta",
                    value=risk_metrics['sharpe_ratio'],
                    title={'text': "Sharpe Ratio"},
                    gauge={'axis': {'range': [-2, 3]},
                           'bar': {'color': "darkblue"},
                           'steps': [{'range': [-2, 0], 'color': "lightgray"},
                                   {'range': [0, 1], 'color': "yellow"},
                                   {'range': [1, 3], 'color': "green"}]},
                    delta={'reference': 1}
                ),
                row=2, col=1
            )
        
        # Performance summary table
        if 'volatility' in risk_metrics:
            fig.add_trace(
                go.Table(
                    header=dict(values=['Metric', 'Value']),
                    cells=dict(values=[
                        ['Volatility', 'Sharpe Ratio', 'Max Drawdown', 'VaR (95%)'],
                        [f"{risk_metrics.get('volatility', 0):.2%}",
                         f"{risk_metrics.get('sharpe_ratio', 0):.2f}",
                         f"{risk_metrics.get('max_drawdown', 0):.2%}",
                         f"{risk_metrics.get('var_95', 0):.2%}"]
                    ])
                ),
                row=2, col=2
            )
        
        fig.update_layout(height=800, title_text=title)
        return fig
    
    def create_allocation_chart(self, weights: np.ndarray,
                               asset_names: List[str],
                               title: str = "Portfolio Allocation") -> go.Figure:
        """
        Create portfolio allocation pie chart.
        
        Args:
            weights: Portfolio weights
            asset_names: Names of assets
            title: Chart title
            
        Returns:
            Plotly figure object
        """
        fig = go.Figure(data=[go.Pie(
            labels=asset_names,
            values=weights,
            hole=0.3
        )])
        
        fig.update_layout(
            title=title,
            showlegend=True
        )
        
        return fig
    
    def create_stress_test_chart(self, stress_results: Dict,
                                title: str = "Stress Test Results") -> go.Figure:
        """
        Create stress test comparison chart.
        
        Args:
            stress_results: Results from stress testing
            title: Chart title
            
        Returns:
            Plotly figure object
        """
        scenarios = list(stress_results.keys())
        mean_returns = []
        max_drawdowns = []
        
        for scenario in scenarios:
            stats = stress_results[scenario]['statistics']
            mean_returns.append(stats.get('mean_return', 0))
            max_drawdowns.append(stats.get('avg_max_drawdown', 0))
        
        fig = make_subplots(
            rows=1, cols=2,
            subplot_titles=('Mean Returns by Scenario', 'Max Drawdown by Scenario')
        )
        
        # Mean returns
        fig.add_trace(
            go.Bar(x=scenarios, y=mean_returns, name='Mean Return'),
            row=1, col=1
        )
        
        # Max drawdowns
        fig.add_trace(
            go.Bar(x=scenarios, y=max_drawdowns, name='Max Drawdown'),
            row=1, col=2
        )
        
        fig.update_layout(height=500, title_text=title)
        return fig
    
    def create_comprehensive_dashboard(self, portfolio_data: Dict,
                                     simulation_results: Optional[Dict] = None,
                                     title: str = "FinGuard Portfolio Dashboard") -> go.Figure:
        """
        Create comprehensive portfolio dashboard.
        
        Args:
            portfolio_data: Portfolio data including values, weights, etc.
            simulation_results: Optional Monte Carlo simulation results
            title: Dashboard title
            
        Returns:
            Plotly figure object
        """
        # Create subplots for comprehensive view
        fig = make_subplots(
            rows=3, cols=2,
            subplot_titles=('Portfolio Evolution', 'Asset Allocation',
                          'Drawdown Analysis', 'Risk Metrics',
                          'Monte Carlo Simulation', 'Performance Summary'),
            specs=[[{"type": "scatter"}, {"type": "pie"}],
                   [{"type": "scatter"}, {"type": "indicator"}],
                   [{"type": "scatter"}, {"type": "table"}]]
        )
        
        # Portfolio evolution
        if 'portfolio_values' in portfolio_data:
            time_periods = np.arange(len(portfolio_data['portfolio_values']))
            fig.add_trace(
                go.Scatter(x=time_periods, y=portfolio_data['portfolio_values'],
                          mode='lines', name='Portfolio Value'),
                row=1, col=1
            )
        
        # Asset allocation
        if 'weights' in portfolio_data and 'asset_names' in portfolio_data:
            fig.add_trace(
                go.Pie(labels=portfolio_data['asset_names'], 
                      values=portfolio_data['weights']),
                row=1, col=2
            )
        
        # Drawdown analysis
        if 'portfolio_values' in portfolio_data:
            peak = np.maximum.accumulate(portfolio_data['portfolio_values'])
            drawdown = (portfolio_data['portfolio_values'] - peak) / peak * 100
            time_periods = np.arange(len(drawdown))
            
            fig.add_trace(
                go.Scatter(x=time_periods, y=drawdown, mode='lines',
                          name='Drawdown', fill='tonexty'),
                row=2, col=1
            )
        
        # Risk metrics gauge
        if 'sharpe_ratio' in portfolio_data:
            fig.add_trace(
                go.Indicator(
                    mode="gauge+number",
                    value=portfolio_data['sharpe_ratio'],
                    title={'text': "Sharpe Ratio"},
                    gauge={'axis': {'range': [-2, 3]},
                           'bar': {'color': "darkblue"},
                           'steps': [{'range': [-2, 0], 'color': "lightgray"},
                                   {'range': [0, 1], 'color': "yellow"},
                                   {'range': [1, 3], 'color': "green"}]}
                ),
                row=2, col=2
            )
        
        # Monte Carlo simulation
        if simulation_results:
            portfolio_values = simulation_results['portfolio_values']
            mean_path = np.mean(portfolio_values, axis=0)
            time_periods = np.arange(mean_path.shape[0])
            
            fig.add_trace(
                go.Scatter(x=time_periods, y=mean_path, mode='lines',
                          name='MC Mean Path'),
                row=3, col=1
            )
        
        # Performance summary table
        summary_data = [
            ['Metric', 'Value'],
            ['Initial Value', f"${portfolio_data.get('initial_value', 0):,.2f}"],
            ['Final Value', f"${portfolio_data.get('final_value', 0):,.2f}"],
            ['Total Return', f"{portfolio_data.get('total_return', 0):.2%}"],
            ['Volatility', f"{portfolio_data.get('volatility', 0):.2%}"]
        ]
        
        fig.add_trace(
            go.Table(header=dict(values=summary_data[0]),
                    cells=dict(values=[summary_data[i] for i in range(1, len(summary_data))])),
            row=3, col=2
        )
        
        fig.update_layout(height=1200, title_text=title)
        return fig
