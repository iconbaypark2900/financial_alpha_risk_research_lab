# FinGuard — Portfolio Risk Management & Simulation

## Overview

**FinGuard** is a comprehensive portfolio risk management tool that combines:

- **Kelly Criterion** for optimal portfolio allocation
- **Drawdown Management** for capital preservation  
- **Monte Carlo Simulation** for stress testing and scenario analysis

Built with **Test-Driven Development (TDD)** and a **Streamlit interface** for interactive portfolio analysis.

## Features

- **Portfolio Optimization**: Kelly Criterion-based asset allocation
- **Risk Management**: Drawdown control and VaR calculations
- **Monte Carlo Simulation**: 1000+ simulation paths with configurable parameters
- **Interactive Dashboard**: Real-time charts and risk metrics
- **Stress Testing**: Built-in market crash, recession, and volatility scenarios
- **Export Capabilities**: CSV export of portfolio summaries and results

## Quick Start

### 1. Install Dependencies

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install requirements
pip install -r requirements.txt
```

### 2. Run the Demo

```bash
# Test core functionality
python demo.py
```

### 3. Launch Streamlit App

```bash
# Start interactive dashboard
streamlit run src/app.py
```

## Usage

### Portfolio Configuration

1. **Set Initial Value**: Choose starting portfolio amount
2. **Configure Assets**: Define returns, volatilities, and correlations
3. **Risk Parameters**: Set drawdown limits and simulation parameters
4. **Run Simulation**: Execute Monte Carlo analysis

### What You'll See

- **Portfolio Overview**: Key metrics and performance indicators
- **Asset Allocation**: Kelly-optimal weights visualization
- **Risk Metrics**: Volatility, VaR, Sharpe ratio, and drawdown analysis
- **Monte Carlo Paths**: 1000+ simulation scenarios with confidence intervals
- **Stress Test Results**: Performance under various market conditions

## Project Structure

```
finGuard/
├── src/
│   ├── finguard/
│   │   ├── kelly.py          # Kelly Criterion implementation
│   │   ├── drawdown.py       # Drawdown management & risk control
│   │   ├── simulator.py      # Monte Carlo simulation engine
│   │   └── visualizer.py     # Chart generation & dashboards
│   └── app.py                # Streamlit application
├── tests/                    # TDD test suite
├── requirements.txt          # Python dependencies
├── demo.py                  # Command-line demo
└── README.md                # This file
```

## Testing

Run the comprehensive test suite:

```bash
# Run all tests
python run_tests.py

# Or use pytest directly
pytest tests/ -v
```

## Example Output

```
🚀 FinGuard Demo - Portfolio Risk Management
==================================================

📊 Portfolio Configuration:
Assets: ['Risk-Free (T-Bills)', 'Stocks', 'Bonds']
Expected Returns: ['2.0%', '8.0%', '5.0%']
Volatilities: ['1.0%', '15.0%', '8.0%']

🎯 Kelly Criterion Optimization:
  Risk-Free (T-Bills): 15.2%
  Stocks: 52.8%
  Bonds: 32.0%

📈 Simulation Results:
  Expected Annual Return: 6.8%
  Annual Volatility: 8.9%
  Sharpe Ratio: 0.76
  Max Drawdown (95% CI): 12.3%
  Probability of Loss: 18.2%
```

## Technical Details

### Kelly Criterion
- Optimal bet sizing for portfolio allocation
- Risk-adjusted return maximization
- Leverage control and adjustment

### Drawdown Management
- Real-time drawdown monitoring
- Automatic risk reduction triggers
- VaR-based drawdown limits

### Monte Carlo Simulation
- Multivariate normal return generation
- Dynamic portfolio rebalancing
- Comprehensive statistical analysis

## Dependencies

- **Streamlit**: Interactive web interface
- **NumPy**: Numerical computations
- **Pandas**: Data manipulation
- **Plotly**: Interactive charts
- **SciPy**: Statistical functions

## License

MIT License - for educational and demonstration purposes only.

## Disclaimer

FinGuard is intended **for educational and demonstration purposes only**. It is **not financial advice** and should not be used to make investment decisions.
