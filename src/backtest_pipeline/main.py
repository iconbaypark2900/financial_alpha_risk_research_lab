"""
Backtest Pipeline Service with actual trading simulation
"""
import asyncio
from typing import List, Dict, Any, Optional
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import vectorbt as vbt
import yfinance as yf


class TradingSimulator:
    def __init__(self, initial_capital: float = 100000.0):
        self.initial_capital = initial_capital
        self.portfolio_value = initial_capital
        self.positions = {}
        self.trades = []
        
    def execute_trade(self, symbol: str, quantity: int, price: float, direction: str = 'buy'):
        """
        Execute a trade and update portfolio
        """
        cost = quantity * price
        
        if direction == 'buy':
            # Check if we have enough capital
            if cost > self.portfolio_value:
                print(f"Insufficient capital for trade: Need ${cost:.2f}, have ${self.portfolio_value:.2f}")
                return False
                
            # Execute buy
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
            self.portfolio_value -= cost
            
        elif direction == 'sell':
            if symbol not in self.positions or self.positions[symbol]['quantity'] < quantity:
                print(f"Cannot sell {quantity} of {symbol}, only hold {self.positions.get(symbol, {}).get('quantity', 0)}")
                return False
                
            # Execute sell
            self.positions[symbol]['quantity'] -= quantity
            self.portfolio_value += cost
            
            # Remove position if quantity becomes zero
            if self.positions[symbol]['quantity'] == 0:
                del self.positions[symbol]
        
        # Record the trade
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
        """
        Calculate current portfolio value based on current prices
        """
        total_value = self.portfolio_value  # Cash
        
        for symbol, position in self.positions.items():
            if symbol in current_prices:
                total_value += position['quantity'] * current_prices[symbol]
        
        return total_value


class BacktestPipeline:
    def __init__(self, initial_capital: float = 100000.0):
        """
        Initialize the backtest pipeline service
        """
        self.initial_capital = initial_capital
        self.simulator = TradingSimulator(initial_capital)
        
    def load_config(self) -> Dict[str, Any]:
        """
        Load backtest configuration
        """
        return {
            "initial_capital": self.initial_capital,
            "start_date": "2023-01-01",
            "end_date": "2023-12-31",
            "trading_strategy": "momentum",
            "symbols": ["AAPL", "GOOGL", "MSFT", "TSLA"]
        }
    
    def load_data_and_factors(self, symbols: List[str], start_date: str, end_date: str) -> Dict[str, Any]:
        """
        Load market data and factors for backtesting
        """
        print(f"Loading data for symbols: {symbols} from {start_date} to {end_date}")
        
        # Fetch historical data
        data = {}
        for symbol in symbols:
            try:
                ticker = yf.Ticker(symbol)
                hist = ticker.history(start=start_date, end=end_date)
                data[symbol] = hist
                
                # Calculate simple factors (momentum, volatility)
                hist['returns'] = hist['Close'].pct_change()
                hist['momentum'] = hist['Close'].pct_change(periods=20)  # 20-day momentum
                hist['volatility'] = hist['returns'].rolling(window=20).std() * np.sqrt(252)  # Annualized volatility
                hist['sma_20'] = hist['Close'].rolling(window=20).mean()
                hist['sma_50'] = hist['Close'].rolling(window=50).mean()
                
            except Exception as e:
                print(f"Error loading data for {symbol}: {e}")
        
        return data
    
    def run_backtest(self, config: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run the backtest with specified configuration and data
        Implements a simple momentum strategy
        """
        print("Running backtest with momentum strategy...")
        
        symbols = config.get("symbols", [])
        start_date = config.get("start_date")
        end_date = config.get("end_date")
        
        # Get data for each symbol
        for symbol, df in data.items():
            if df.empty:
                continue
                
            # Simple momentum strategy: buy when 20-day MA crosses above 50-day MA, sell when opposite
            for i in range(50, len(df)):  # Start from index 50 since we need 50-day MA
                current_price = df['Close'].iloc[i]
                
                # Check if we have SMA data
                if pd.isna(df['sma_20'].iloc[i]) or pd.isna(df['sma_50'].iloc[i]):
                    continue
                
                # Buy signal: 20-day MA crosses above 50-day MA
                if (df['sma_20'].iloc[i-1] <= df['sma_50'].iloc[i-1] and 
                    df['sma_20'].iloc[i] > df['sma_50'].iloc[i]):
                    
                    # Buy 10 shares if we have enough capital
                    if self.simulator.portfolio_value >= current_price * 10:
                        self.simulator.execute_trade(symbol, 10, current_price, 'buy')
                        print(f"BUY: {10} shares of {symbol} at ${current_price:.2f}")
                
                # Sell signal: 20-day MA crosses below 50-day MA
                elif (df['sma_20'].iloc[i-1] >= df['sma_50'].iloc[i-1] and 
                      df['sma_20'].iloc[i] < df['sma_50'].iloc[i]):
                    
                    # Sell 10 shares if we hold any
                    if symbol in self.simulator.positions and self.simulator.positions[symbol]['quantity'] >= 10:
                        self.simulator.execute_trade(symbol, 10, current_price, 'sell')
                        print(f"SELL: {10} shares of {symbol} at ${current_price:.2f}")
            
            print(f"Completed backtest for {symbol}")
        
        # Calculate final portfolio value
        final_prices = {}
        for symbol, df in data.items():
            if not df.empty:
                final_prices[symbol] = df['Close'].iloc[-1]
        
        final_portfolio_value = self.simulator.get_portfolio_value(final_prices)
        
        return {
            "initial_capital": self.initial_capital,
            "final_portfolio_value": final_portfolio_value,
            "total_return": (final_portfolio_value - self.initial_capital) / self.initial_capital * 100,
            "num_trades": len(self.simulator.trades),
            "symbols": symbols,
            "positions": self.simulator.positions,
            "trades": self.simulator.trades
        }
    
    def compute_metrics(self, backtest_results: Dict[str, Any]) -> Dict[str, Any]:
        """
        Compute performance and risk metrics from backtest results
        """
        initial_capital = backtest_results["initial_capital"]
        final_value = backtest_results["final_portfolio_value"]
        total_return = backtest_results["total_return"]
        num_trades = backtest_results["num_trades"]
        
        # Calculate additional metrics
        total_return_pct = (final_value - initial_capital) / initial_capital * 100
        profit = final_value - initial_capital
        
        # Calculate Sharpe ratio (simplified, assuming risk-free rate of 0)
        # For a real implementation, you'd calculate the standard deviation of returns
        sharpe_ratio = "N/A - requires return series for calculation"
        
        # Calculate max drawdown (simplified)
        max_drawdown = "N/A - requires daily portfolio values for calculation"
        
        return {
            "total_return_pct": total_return_pct,
            "profit_loss": profit,
            "final_value": final_value,
            "initial_capital": initial_capital,
            "num_trades": num_trades,
            "sharpe_ratio": sharpe_ratio,
            "max_drawdown": max_drawdown,
            "win_rate": "N/A - requires individual trade results"
        }
    
    def persist_results(self, metrics: Dict[str, Any], detailed_results: Dict[str, Any]):
        """
        Persist backtest results and metrics
        """
        # In a real implementation, this would save to a database
        print("\nPersisting backtest results...")
        print(f"Final portfolio value: ${detailed_results['final_portfolio_value']:,.2f}")
        print(f"Total return: {detailed_results['total_return']:.2f}%")
        print(f"Number of trades: {detailed_results['num_trades']}")
        print("Positions at end of backtest:", detailed_results['positions'])


async def main():
    """
    Main function to run the backtest pipeline with actual trading simulation
    """
    print("="*60)
    print("FINANCIAL ALPHA & RISK RESEARCH LAB - BACKTEST SIMULATION")
    print("="*60)
    
    pipeline = BacktestPipeline(initial_capital=100000.0)
    
    # Load configuration
    config = pipeline.load_config()
    print(f"Loaded configuration: {config}")
    
    # Load data and factors
    data = pipeline.load_data_and_factors(
        symbols=config["symbols"], 
        start_date=config["start_date"], 
        end_date=config["end_date"]
    )
    
    # Run backtest
    backtest_results = pipeline.run_backtest(config, data)
    
    # Compute metrics
    metrics = pipeline.compute_metrics(backtest_results)
    
    # Persist results
    pipeline.persist_results(metrics, backtest_results)
    
    # Print summary
    print("\n" + "="*60)
    print("BACKTEST SUMMARY")
    print("="*60)
    print(f"Initial Capital: ${backtest_results['initial_capital']:,.2f}")
    print(f"Final Portfolio Value: ${backtest_results['final_portfolio_value']:,.2f}")
    print(f"Total Return: {backtest_results['total_return']:.2f}%")
    print(f"Number of Trades: {backtest_results['num_trades']}")
    print(f"Final Positions: {backtest_results['positions']}")
    print("="*60)
    
    return backtest_results

if __name__ == "__main__":
    asyncio.run(main())