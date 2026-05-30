"""
Comprehensive integration test demonstrating how all services work together
in the Financial Alpha & Risk Research Lab
"""
import asyncio
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, Any, List
import yfinance as yf


class TradingSimulator:
    """Simple trading simulator for demonstration"""
    def __init__(self, initial_capital: float = 100000.0):
        self.initial_capital = initial_capital
        self.portfolio_value = initial_capital
        self.positions = {}
        self.trades = []
        self.cash = initial_capital
    
    def execute_trade(self, symbol: str, quantity: int, price: float, direction: str = 'buy'):
        """Execute a trade and update portfolio"""
        cost = quantity * price
        
        if direction == 'buy':
            if cost > self.cash:
                return False
            
            if symbol in self.positions:
                self.positions[symbol]['quantity'] += quantity
                self.positions[symbol]['cost_basis'] = (
                    (self.positions[symbol]['cost_basis'] * self.positions[symbol]['quantity'] + cost) 
                    / (self.positions[symbol]['quantity'] + quantity)
                )
            else:
                self.positions[symbol] = {
                    'quantity': quantity,
                    'cost_basis': price
                }
            self.cash -= cost
            
        elif direction == 'sell':
            if symbol not in self.positions or self.positions[symbol]['quantity'] < quantity:
                return False
                
            self.positions[symbol]['quantity'] -= quantity
            self.cash += cost
            
            if self.positions[symbol]['quantity'] == 0:
                del self.positions[symbol]
        
        self.trades.append({
            'symbol': symbol,
            'quantity': quantity,
            'price': price,
            'direction': direction,
            'timestamp': datetime.now(),
            'value': cost
        })
        
        return True
    
    def get_portfolio_value(self, current_prices: Dict[str, float]):
        """Calculate current portfolio value"""
        total_value = self.cash
        for symbol, position in self.positions.items():
            if symbol in current_prices:
                total_value += position['quantity'] * current_prices[symbol]
        return total_value


class MarketDataPipeline:
    """Market Data Pipeline implementation"""
    def __init__(self):
        pass
    
    async def fetch_raw_data(self, symbols: List[str], start_date: str, end_date: str) -> Dict[str, Any]:
        """Fetch raw market data from sources"""
        print(f"[MARKET DATA] Fetching data for symbols: {symbols} from {start_date} to {end_date}")
        
        raw_data = {}
        for symbol in symbols:
            try:
                ticker = yf.Ticker(symbol)
                hist = ticker.history(start=start_date, end=end_date)
                raw_data[symbol] = hist
                print(f"[MARKET DATA] Successfully fetched {len(hist)} records for {symbol}")
            except Exception as e:
                print(f"[MARKET DATA] Error fetching data for {symbol}: {e}")
                raw_data[symbol] = pd.DataFrame()
        
        return raw_data
    
    def normalize_adjust(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize and adjust data"""
        normalized_data = {}
        
        for symbol, df in raw_data.items():
            if df.empty:
                normalized_data[symbol] = df
                continue
            
            df = df.copy()
            df['returns'] = df['Close'].pct_change()
            df = df.ffill().fillna(0)
            normalized_data[symbol] = df
            print(f"[MARKET DATA] Normalized {len(df)} records for {symbol}")
        
        return normalized_data


class FactorUpdatePipeline:
    """Factor Update Pipeline implementation"""
    def __init__(self):
        pass
    
    def load_prices(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Load prices from data"""
        print(f"[FACTOR] Loading prices for {len(data)} symbols")
        return data
    
    def compute_factors(self, price_data: Dict[str, Any]) -> Dict[str, Any]:
        """Compute factors based on loaded prices"""
        factors = {}
        
        for symbol, df in price_data.items():
            if df.empty:
                factors[symbol] = pd.DataFrame()
                continue
            
            df_factors = df[['Open', 'High', 'Low', 'Close', 'Volume', 'returns']].copy()
            
            # Technical factors
            df_factors['momentum'] = df_factors['Close'].pct_change(periods=20)
            df_factors['volatility'] = df_factors['returns'].rolling(window=20).std() * np.sqrt(252)
            df_factors['sma_20'] = df_factors['Close'].rolling(window=20).mean()
            df_factors['sma_50'] = df_factors['Close'].rolling(window=50).mean()
            df_factors['rsi'] = self._calculate_rsi(df_factors['Close'])
            df_factors['macd'] = self._calculate_macd(df_factors['Close'])
            
            factors[symbol] = df_factors
            print(f"[FACTOR] Computed {len(df_factors.columns)} factors for {symbol}")
        
        return factors
    
    def _calculate_rsi(self, prices, window=14):
        """Calculate Relative Strength Index"""
        delta = prices.diff()
        gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
        return rsi
    
    def _calculate_macd(self, prices, fast=12, slow=26, signal=9):
        """Calculate Moving Average Convergence Divergence"""
        exp1 = prices.ewm(span=fast, adjust=False).mean()
        exp2 = prices.ewm(span=slow, adjust=False).mean()
        macd = exp1 - exp2
        return macd


class BacktestPipeline:
    """Backtest Pipeline implementation"""
    def __init__(self, initial_capital: float = 100000.0):
        self.simulator = TradingSimulator(initial_capital)
    
    def run_backtest(self, factors: Dict[str, Any], strategy_params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Run the backtest with factor-based strategy"""
        print("[BACKTEST] Running backtest with factor-based strategy...")
        
        if strategy_params is None:
            strategy_params = {"momentum_threshold": 0.02, "min_volatility": 0.1}
        
        for symbol, df in factors.items():
            if df.empty or len(df) < 50:  # Need at least 50 days for moving averages
                continue
            
            for i in range(50, len(df)):  # Start from index where SMA_50 is available
                current_price = df['Close'].iloc[i]
                
                # Skip if any values are NaN
                if (pd.isna(df['sma_20'].iloc[i]) or pd.isna(df['sma_50'].iloc[i]) or 
                    pd.isna(df['momentum'].iloc[i]) or pd.isna(df['volatility'].iloc[i])):
                    continue
                
                # Momentum strategy: buy when 20-day MA > 50-day MA and momentum > threshold and volatility is acceptable
                if (df['sma_20'].iloc[i] > df['sma_50'].iloc[i] and 
                    df['momentum'].iloc[i] > strategy_params["momentum_threshold"] and
                    df['volatility'].iloc[i] < strategy_params["min_volatility"] and
                    df['rsi'].iloc[i] < 70):  # Avoid overbought conditions
                    
                    # Buy 10 shares if we have enough capital
                    if self.simulator.cash >= current_price * 10:
                        success = self.simulator.execute_trade(symbol, 10, current_price, 'buy')
                        if success:
                            print(f"[BACKTEST] BUY: 10 shares of {symbol} at ${current_price:.2f}")
                
                # Sell signal: 20-day MA < 50-day MA or overbought conditions
                elif (df['sma_20'].iloc[i] < df['sma_50'].iloc[i] or 
                      df['rsi'].iloc[i] > 80):  # Overbought condition
                    
                    # Sell 10 shares if we hold any
                    if (symbol in self.simulator.positions and 
                        self.simulator.positions[symbol]['quantity'] >= 10):
                        success = self.simulator.execute_trade(symbol, 10, current_price, 'sell')
                        if success:
                            print(f"[BACKTEST] SELL: 10 shares of {symbol} at ${current_price:.2f}")
        
        # Calculate final portfolio value
        final_prices = {}
        for symbol, df in factors.items():
            if not df.empty:
                final_prices[symbol] = df['Close'].iloc[-1]
        
        final_portfolio_value = self.simulator.get_portfolio_value(final_prices)
        
        return {
            "initial_capital": self.simulator.initial_capital,
            "final_portfolio_value": final_portfolio_value,
            "total_return": (final_portfolio_value - self.simulator.initial_capital) / self.simulator.initial_capital * 100,
            "num_trades": len(self.simulator.trades),
            "final_positions": self.simulator.positions,
            "trades": self.simulator.trades
        }


class PortfolioRiskService:
    """Portfolio Risk Service implementation"""
    def optimize_portfolio(self, assets: List[str], factors: Dict[str, Any], constraints: Dict[str, Any] = None) -> Dict[str, Any]:
        """Perform portfolio optimization based on factors"""
        print(f"[PORTFOLIO RISK] Optimizing portfolio for {len(assets)} assets")
        
        # Simple mean-variance optimization based on recent returns and volatility
        weights = {}
        total_weight = 0
        
        for asset in assets:
            if asset in factors and not factors[asset].empty:
                # Calculate recent average return and volatility
                recent_data = factors[asset].tail(60)  # Last 60 days
                avg_return = recent_data['returns'].mean() * 252  # Annualized
                volatility = recent_data['returns'].std() * np.sqrt(252)  # Annualized
                
                # Simple risk-adjusted allocation (higher return, lower risk = higher weight)
                if volatility != 0:
                    risk_adjusted_score = avg_return / volatility
                    weights[asset] = max(0.05, min(0.3, risk_adjusted_score))  # Cap between 5% and 30%
                    total_weight += weights[asset]
                else:
                    weights[asset] = 0.1  # Default 10% if no volatility data
                    total_weight += 0.1
            else:
                weights[asset] = 0.1  # Default 10% if no factor data
                total_weight += 0.1
        
        # Normalize weights to sum to 1 (or less if some assets didn't meet criteria)
        if total_weight > 0:
            for asset in weights:
                weights[asset] = weights[asset] / total_weight
        
        print(f"[PORTFOLIO RISK] Portfolio weights: {weights}")
        
        return {"weights": weights}
    
    def compute_risk_metrics(self, portfolio_positions: Dict[str, Any], current_prices: Dict[str, float]) -> Dict[str, Any]:
        """Compute various risk metrics for the portfolio"""
        print("[PORTFOLIO RISK] Computing risk metrics...")
        
        # Calculate portfolio value
        total_value = sum(pos['quantity'] * current_prices.get(symbol, 0) 
                         for symbol, pos in portfolio_positions.items())
        
        # Calculate basic risk metrics
        var_95 = total_value * 0.05  # Simplified 5% VaR
        var_99 = total_value * 0.02  # Simplified 2% VaR
        max_drawdown = total_value * 0.1  # Simplified 10% max drawdown
        
        risk_metrics = {
            "portfolio_value": total_value,
            "var_95": var_95,
            "var_99": var_99,
            "max_drawdown": max_drawdown,
            "volatility": "N/A for this demo"
        }
        
        print(f"[PORTFOLIO RISK] Risk metrics: {risk_metrics}")
        return risk_metrics


async def full_integration_example():
    """
    Full integration example showing how all services work together
    """
    print("="*100)
    print("FINANCIAL ALPHA & RISK RESEARCH LAB - FULL INTEGRATION EXAMPLE")
    print("Demonstrating complete workflow from market data to portfolio optimization")
    print("="*100)
    
    # Define symbols and time period
    symbols = ["AAPL", "GOOGL", "MSFT", "TSLA"]
    start_date = "2023-01-01"
    end_date = "2023-06-01"
    
    # Initialize all services
    market_pipeline = MarketDataPipeline()
    factor_pipeline = FactorUpdatePipeline()
    backtest_pipeline = BacktestPipeline(initial_capital=100000.0)
    risk_service = PortfolioRiskService()
    
    print("\n[STEP 1: MARKET DATA PIPELINE]")
    print("Fetching market data from various sources...")
    raw_data = await market_pipeline.fetch_raw_data(symbols, start_date, end_date)
    
    print("\nNormalizing and adjusting data...")
    normalized_data = market_pipeline.normalize_adjust(raw_data)
    
    print("\n[STEP 2: FACTOR UPDATE PIPELINE]")
    print("Loading price data...")
    price_data = factor_pipeline.load_prices(normalized_data)
    
    print("Computing technical and fundamental factors...")
    factors = factor_pipeline.compute_factors(price_data)
    
    print("\n[STEP 3: BACKTEST PIPELINE]")
    print("Running strategy backtest using computed factors...")
    backtest_results = backtest_pipeline.run_backtest(factors)
    
    print("\n[STEP 4: PORTFOLIO RISK SERVICE]")
    print("Optimizing portfolio based on factors...")
    optimized_portfolio = risk_service.optimize_portfolio(symbols, factors)
    
    print("Computing risk metrics...")
    # Get final prices for risk calculation
    final_prices = {symbol: df['Close'].iloc[-1] if not df.empty else 0 
                   for symbol, df in normalized_data.items()}
    risk_metrics = risk_service.compute_risk_metrics(backtest_results["final_positions"], final_prices)
    
    print("\n" + "="*100)
    print("FULL INTEGRATION SUMMARY")
    print("="*100)
    print(f"Initial Capital: ${backtest_results['initial_capital']:,.2f}")
    print(f"Final Portfolio Value: ${backtest_results['final_portfolio_value']:,.2f}")
    print(f"Total Return: {backtest_results['total_return']:.2f}%")
    print(f"Number of Trades: {backtest_results['num_trades']}")
    print(f"Final Positions: {len(backtest_results['final_positions'])} assets")
    print(f"Portfolio Value (Risk Analysis): ${risk_metrics['portfolio_value']:,.2f}")
    print(f"95% VaR: ${risk_metrics['var_95']:,.2f}")
    print(f"99% VaR: ${risk_metrics['var_99']:,.2f}")
    print("="*100)
    
    # Show portfolio weights
    print("\nPORTFOLIO ALLOCATION:")
    for asset, weight in optimized_portfolio['weights'].items():
        print(f"  {asset}: {weight:.2%}")
    
    print("\n" + "="*100)
    print("FULL INTEGRATION EXAMPLE COMPLETED SUCCESSFULLY")
    print("="*100)
    
    return backtest_results, risk_metrics, optimized_portfolio


def main():
    """
    Main function to run the full integration example
    """
    print("Starting full integration example for Financial Alpha & Risk Research Lab...")
    
    # Run the async full integration pipeline
    results = asyncio.run(full_integration_example())
    
    return results


if __name__ == "__main__":
    main()