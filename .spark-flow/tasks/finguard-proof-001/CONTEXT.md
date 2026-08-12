        # CONTEXT: finguard-proof-001

        ## Snapshot

        - Captured: 2026-05-30T23:59:53
        - Repo: `/home/iconbaypark2900/dataScience/financial_alpha_risk_research_lab`
        - Branch: `main`

        ## Git status

        ```text
        ?? .spark-flow/
        ```

        ## Project metadata files

        - `migration_inbox/finGuard/requirements.txt`
- `requirements.txt`

        ## README excerpt

        ```markdown
        # Financial Alpha & Risk Research Lab

A comprehensive quantitative finance research platform designed for developing, testing, and optimizing trading strategies with advanced risk management.

## Overview

The Financial Alpha & Risk Research Lab is a sophisticated platform that combines machine learning, quantitative finance, and natural language processing to enable systematic investment strategy research. It includes:

- **Market Data Pipeline**: Ingests and processes market data from various sources
- **Factor Update Pipeline**: Computes and manages quantitative factors
- **Backtest Pipeline**: Executes comprehensive backtesting with realistic assumptions
- **Strategy Evolution Pipeline**: Automates strategy discovery and optimization
- **Research RAG Pipeline**: Provides AI-powered research assistance with document retrieval
- **Portfolio Risk Service**: Performs portfolio optimization and risk analysis

## Architecture

### Tech Stack
- **Storage**: OpenSearch for logs and document indexing, Qdrant for vector embeddings, Neo4j for knowledge graphs
- **ML/Quant**: PyTorch, vectorbt/Backtrader, PyPortfolioOpt, River for online learning
- **Optimization**: Optuna and OpenEvolve for hyperparameter and strategy optimization
- **Security**: HashiCorp Vault for secrets management, Open Policy Agent for access control
- **Observability**: MLflow, Langfuse, Prometheus + Grafana

### Core Services

#### Market Data Pipeline
- Connects to multiple data sources (broker APIs, crypto exchanges, macro data, SEC filings)
- Normalizes, adjusts for corporate actions, and handles missing data
- Maintains timeseries data store and emits price update events

#### Factor Update Pipeline
- Computes technical factors (momentum, volatility, trend, spreads)
- Calculates cross-sectional factors (value, quality, growth, size, profitability)
- Implements event/flow-based features (earnings, insider trades, buybacks)
- Extensible architecture for custom factor definitions

#### Backtest Pipeline
- Supports daily and intraday granularities
- Includes realistic transaction cost models, borrow fees, partial fills
- Implements various portfolio types (long-only, long-short, market-neutral)
- Generates comprehensive performance and risk metrics

#### Strategy Evolution Pipeline
- Uses Bayesian optimization (Optuna) and evolutionary algorithms (OpenEvolve)
- Optimizes for risk-adjusted returns, tail risk measures, and robustness
- Maintains Pareto-optimal front of strategies across multiple objectives

#### Research RAG Pipeline
- Hybrid retrieval combining BM25, vector embeddings, and graph traversal
- Processes filings, transcripts, research reports, and internal notes
- Enables natural language queries for insights and explanations

#### Portfolio Risk Service
- Implements mean-variance, risk parity, and minimum volatility optimization
- Computes VaR, CVaR, and other risk metrics
- Performs stress testing and scenario analysis

## Setup

1. Clone the repository
2. Install dependencies: `pip install -r requirements.txt`
3. Set up required services (OpenSearch, Qdrant, Neo4j, Vault)
4. Configure settings in `config/settings.json`
5. Run individual services as needed

## Usage

Each service can be run independently or as part of the integrated pipeline:

```bash
# Run market data pipeline
cd src/market_data_pipeline && python main.py

# Run factor update pipeline
cd src/factor_update_pipeline && python main.py

# Run backtest pipeline
cd src/backtest_pipeline && python main.py

        ```

        ## Source of truth

        This file is the durable context snapshot for the current task. Chat history is not the source of truth.
