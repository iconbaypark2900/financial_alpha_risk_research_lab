"""
Example demonstrating integration between market data pipeline and factor update pipeline
"""
import asyncio
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import yfinance as yf
from typing import Dict, Any, List


class MarketDataPipeline:
    def __init__(self):
        """
        Initialize the market data pipeline service
        """
        pass
    
    async def fetch_raw_data(self, symbols: List[str], start_date: str, end_date: str) -> Dict[str, Any]:
        """
        Fetch raw market data from sources
        """
        print(f"Fetching raw data for symbols: {symbols} from {start_date} to {end_date}")
        
        raw_data = {}
        for symbol in symbols:
            try:
                ticker = yf.Ticker(symbol)
                hist = ticker.history(start=start_date, end=end_date)
                raw_data[symbol] = hist
                print(f"Successfully fetched data for {symbol}: {len(hist)} records")
            except Exception as e:
                print(f"Error fetching data for {symbol}: {e}")
                raw_data[symbol] = pd.DataFrame()  # Return empty DataFrame in case of error
        
        return raw_data
    
    def normalize_adjust(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize and adjust data
        """
        normalized_data = {}
        
        for symbol, df in raw_data.items():
            if df.empty:
                normalized_data[symbol] = df
                continue
            
            # Basic normalization: calculate returns and adjust for any obvious anomalies
            df = df.copy()
            df['returns'] = df['Close'].pct_change()
            
            # Adjust for splits, dividends would be handled here too
            # For simplicity, assuming data from yfinance is already adjusted
            
            # Fill any remaining NaN values
            df = df.ffill()
            df = df.fillna(0)  # For any leading NaN values
            
            normalized_data[symbol] = df
            print(f"Normalized data for {symbol}: {len(df)} records after adjustments")
        
        return normalized_data
    
    def write_timeseries_store(self, normalized_data: Dict[str, Any]):
        """
        Write normalized data to timeseries store
        """
        # In a real implementation, this would write to a timeseries database
        print(f"Writing data for {len(normalized_data)} symbols to timeseries store")
        for symbol, df in normalized_data.items():
            if not df.empty:
                print(f"  - {symbol}: {len(df)} records, date range: {df.index[0]} to {df.index[-1]}")
    
    def emit_prices_updated(self, symbols: List[str]):
        """
        Emit prices.updated event
        """
        print(f"Emitting prices.updated event for {len(symbols)} symbols: {symbols}")


class FactorUpdatePipeline:
    def __init__(self):
        """
        Initialize the factor update pipeline service
        """
        pass
    
    def load_prices(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Load prices from the provided data (simulating loading from timeseries store)
        """
        print(f"Loading prices for {len(data)} symbols")
        return data
    
    def compute_factors(self, price_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Compute factors based on loaded prices
        """
        factors = {}
        
        for symbol, df in price_data.items():
            if df.empty:
                factors[symbol] = pd.DataFrame()
                continue
            
            # Calculate various factors
            df_factors = df[['Open', 'High', 'Low', 'Close', 'Volume', 'returns']].copy()
            
            # Technical factors
            df_factors['momentum'] = df_factors['Close'].pct_change(periods=20)  # 20-day momentum
            df_factors['volatility'] = df_factors['returns'].rolling(window=20).std() * np.sqrt(252)  # Annualized volatility
            df_factors['sma_20'] = df_factors['Close'].rolling(window=20).mean()
            df_factors['sma_50'] = df_factors['Close'].rolling(window=50).mean()
            df_factors['rsi'] = self._calculate_rsi(df_factors['Close'])  # Relative Strength Index
            df_factors['macd'] = self._calculate_macd(df_factors['Close'])  # Moving Average Convergence Divergence
            
            # Simple price-based factors
            df_factors['high_low_ratio'] = df_factors['High'] / df_factors['Low']
            df_factors['close_open_ratio'] = df_factors['Close'] / df_factors['Open']
            
            factors[symbol] = df_factors
            print(f"Computed {len(df_factors.columns)} factors for {symbol}")
        
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
    
    def store_factors(self, factors: Dict[str, Any]):
        """
        Store computed factors
        """
        print(f"Storing factors for {len(factors)} symbols")
        for symbol, df in factors.items():
            print(f"  - {symbol}: {len(df)} records with {len(df.columns)} factors each")
    
    def notify_downstream(self, symbols: List[str]):
        """
        Notify downstream services of factor updates
        """
        print(f"Notifying downstream services of factor updates for {len(symbols)} symbols: {symbols}")


async def integrated_pipeline_example():
    """
    Example demonstrating integration between market data and factor update pipelines
    """
    print("="*80)
    print("FINANCIAL ALPHA & RISK RESEARCH LAB - INTEGRATED PIPELINE EXAMPLE")
    print("Demonstrating integration between Market Data Pipeline and Factor Update Pipeline")
    print("="*80)
    
    # Define symbols and time period
    symbols = ["AAPL", "GOOGL", "MSFT"]
    start_date = "2023-01-01"
    end_date = "2023-06-01"  # Using shorter period for faster execution
    
    # Initialize both pipelines
    market_pipeline = MarketDataPipeline()
    factor_pipeline = FactorUpdatePipeline()
    
    # Step 1: Market Data Pipeline - Fetch and process market data
    print("\n[STEP 1: Market Data Pipeline]")
    raw_data = await market_pipeline.fetch_raw_data(symbols, start_date, end_date)
    
    # Normalize and adjust data
    normalized_data = market_pipeline.normalize_adjust(raw_data)
    
    # Write to timeseries store
    market_pipeline.write_timeseries_store(normalized_data)
    
    # Emit prices updated event
    market_pipeline.emit_prices_updated(symbols)
    
    print("\nMarket data pipeline completed successfully!")
    
    # Step 2: Factor Update Pipeline - Use the processed data to compute factors
    print("\n[STEP 2: Factor Update Pipeline]")
    price_data = factor_pipeline.load_prices(normalized_data)
    
    # Compute factors
    factors = factor_pipeline.compute_factors(price_data)
    
    # Store factors
    factor_pipeline.store_factors(factors)
    
    # Notify downstream services
    factor_pipeline.notify_downstream(symbols)
    
    print("\nFactor update pipeline completed successfully!")
    
    # Summary
    print("\n" + "="*80)
    print("INTEGRATION SUMMARY")
    print("="*80)
    print(f"Processed {len(symbols)} symbols: {symbols}")
    print(f"Date range: {start_date} to {end_date}")
    
    for symbol, df in factors.items():
        if not df.empty:
            print(f"- {symbol}: {len(df)} rows, {len(df.columns)} factors computed")
    
    print("="*80)
    
    return normalized_data, factors


def main():
    """
    Main function to run the integrated pipeline example
    """
    # Run the async integrated pipeline
    result = asyncio.run(integrated_pipeline_example())
    return result


if __name__ == "__main__":
    main()