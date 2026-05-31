# FinGuard — Risk & Portfolio Simulator

## Overview

**FinGuard** is a financial risk management and portfolio simulation tool. It allows users to simulate different portfolio allocations, apply the **Kelly Criterion** for optimal bet sizing, integrate **drawdown control**, and stress-test allocations with **Monte Carlo simulations**. The project demonstrates applied quantitative finance techniques, data visualization, and a TDD-based workflow.

The project highlights:

- **Risk models**: Kelly Criterion, drawdown management.
- **Simulations**: Monte Carlo for portfolio stress testing.
- **Visualization**: Streamlit dashboards with equity curves and risk metrics.
- **Test-Driven Development (TDD)** for robust financial calculations.

---

## Features

- Define portfolios with multiple assets.
- Simulate allocation strategies with Kelly Criterion.
- Apply drawdown control for capital preservation.
- Run Monte Carlo stress tests.
- Visualize equity curves, risk/reward metrics, and drawdown plots.

---

## Installation

```bash
# Clone repository
git clone https://github.com/yourusername/finguard
cd finguard

# Create virtual environment
python -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

---

## Usage

### Run the Streamlit App

```bash
streamlit run src/app.py
```

### Example Simulation

1. Define portfolio: {BTC 50%, ETH 30%, SPY 20%}.
2. Apply Kelly Criterion to compute optimal sizing.
3. Run Monte Carlo stress test (1000 iterations).
4. Visualize expected growth vs. max drawdown.

---

## Example Output

Simulation Results:

```
Optimal Allocation (Kelly-adjusted): BTC 40%, ETH 25%, SPY 35%
Expected CAGR: 12.5%
Max Drawdown (95% CI): -22%
```

Dashboard:

- Equity curve plot
- Histogram of returns
- Drawdown chart

---

## Testing Strategy

FinGuard follows **TDD methodology**:

1. **Unit Tests**: Kelly formula, drawdown calculator.
2. **Integration Tests**: simulation pipeline (portfolio → results).
3. **Monte Carlo Tests**: distribution reproducibility with seed.
4. **Visualization Tests**: verify plot data integrity.

Run tests:

```bash
pytest -q
```

---

## Project Structure

```
finguard/
├─ src/
│  ├─ finguard/
│  │  ├─ __init__.py
│  │  ├─ kelly.py         # Kelly Criterion logic
│  │  ├─ drawdown.py      # Drawdown management
│  │  ├─ simulator.py     # Monte Carlo simulation
│  │  ├─ visualizer.py    # Dashboard plots
│  └─ app.py              # Streamlit entrypoint
├─ tests/
│  ├─ test_kelly.py
│  ├─ test_drawdown.py
│  ├─ test_simulator.py
│  └─ test_pipeline.py
├─ requirements.txt
└─ README.md
```

---

## Roadmap

-

---

## License

MIT License. See `LICENSE` file for details.

---

## Disclaimer

FinGuard is intended **for educational and demonstration purposes only**. It is **not financial advice** and should not be used to make investment decisions.

