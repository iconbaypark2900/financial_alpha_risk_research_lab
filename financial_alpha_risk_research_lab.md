# Financial Alpha & Risk Research Lab
- OpenSearch for logs, metrics, and document / filings index.
- Qdrant for embeddings over documents, notes, and structured textual fields.
- **Graph & Knowledge:**
- Neo4j for issuer, insider, sector, instrument, and relationship graphs.
- **ML & Quant Stack:**
- PyTorch for ML models.
- vectorbt / Backtrader for backtests.
- PyPortfolioOpt, cvxpy for portfolio construction.
- River + ADWIN for online learning and regime shifts.
- Optuna and OpenEvolve for strategy and hyperparameter search.
- **Security & Governance:**
- Vault for secrets.
- OPA for access policies (desk, asset class, region, regulatory constraints).
- Full audit logging.
- **Observability:**
- MLflow for experiments and models.
- Langfuse for LLM/RAG traces.
- Prometheus + Grafana + OpenSearch for infra and pipeline metrics.


## 5. Core Services & Components


### 5.1 Market & Fundamentals Ingestion Service


- Connectors: broker APIs (e.g., Alpaca), crypto (CCXT), macro (FRED), fundamentals (SEC EDGAR), custom CSV/feeds.
- Functions: normalization, corporate action adjustments, missing data handling, calendar alignment.
- Emits events: `prices.updated`, `fundamentals.updated`, `macro.updated`.


### 5.2 Factor & Signal Engine


- Libraries of:
- Technical factors (momentum, volatility, trend, spreads).
- Cross-sectional factors (value, quality, growth, size, profitability).
- Event/flow-based features (earnings, insider trades, buybacks, volume anomalies).
- Extensible: new signals defined as code + metadata; auto-logged and versioned.


### 5.3 Backtest & Simulation Engine


- Supports:
- Daily and intraday granularity.
- Transaction cost models, borrow fees, partial fills.
- Long-only, long-short, market-neutral, multi-asset portfolios.
- Outputs:
- Equity curves, drawdowns, risk metrics, factor exposures, turnover, capacity estimates.


### 5.4 Portfolio Construction & Risk Service


- Optimization:
- Mean-variance, risk parity, min-vol, custom convex objectives via cvxpy.
- Constraints: leverage, sector, factor, liquidity, ESG/custom.
- Risk:
- Historical / parametric / Monte Carlo VaR & CVaR.
- Max drawdown, time-under-water, regime classification.
- Scenario analysis (rates shocks, credit spread widening, volatility spikes).


### 5.5 Strategy Evolution Service


- Automated search using:
- Optuna (Bayesian/TPE).
- OpenEvolve (genetic/evolutionary search over rules, thresholds, model choices).
- Optimizes for:
- Risk-adjusted return metrics (Sharpe, Sortino, Calmar).
- Tail risk (max drawdown, VaR limits).
- Robustness (performance across rolling windows and regimes).


### 5.6 Research RAG & Insights Service


- Document universe: filings, transcripts, macro reports, internal notes.
- Hybrid retrieval:
- BM25 via OpenSearch.
- Embeddings via Qdrant.
- Issuer & entity graph via Neo4j.
- Use cases:
- "Explain this factor drawdown."
- "Summarize regulatory changes impacting this portfolio."
- "What did management say about capex guidance over last 4 calls?"


## 6. Security, Governance & Multi-Tenancy


- Role- and desk-based access boundaries enforced via OPA.
- Segregation of research environments by team/client.
- Optional on-prem or VPC deployment for sensitive shops.
- All runs (data, models, backtests) fully audited and reproducible.


## 7. Non-Functional Requirements


- Deterministic and reproducible research runs.
- Scales from single-node lab to distributed cluster.
- Supports batch and near-real-time factor updates.
- Designed for extensibility across new asset classes and data vendors.