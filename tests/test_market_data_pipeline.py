import pytest
from unittest.mock import Mock, AsyncMock
import sys
import os

# Add the src directory to the Python path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src', 'market_data_pipeline'))

from main import MarketDataPipeline

@pytest.mark.asyncio
async def test_market_data_pipeline_initialization():
    """Test that the MarketDataPipeline can be initialized"""
    pipeline = MarketDataPipeline()
    assert pipeline is not None

@pytest.mark.asyncio
async def test_fetch_raw_data():
    """Test the fetch_raw_data method"""
    pipeline = MarketDataPipeline()
    result = await pipeline.fetch_raw_data()
    # Since the method is not fully implemented, we expect an empty dict
    assert result == {}

def test_normalize_adjust():
    """Test the normalize_adjust method"""
    pipeline = MarketDataPipeline()
    raw_data = {"test": "data"}
    result = pipeline.normalize_adjust(raw_data)
    # Since the method is not fully implemented, we expect the same data back
    assert result == raw_data

def test_write_timeseries_store():
    """Test the write_timeseries_store method"""
    pipeline = MarketDataPipeline()
    # This method returns None, so we just ensure it runs without error
    result = pipeline.write_timeseries_store({"test": "data"})
    assert result is None

def test_emit_prices_updated():
    """Test the emit_prices_updated method """
    pipeline = MarketDataPipeline()
    # This method returns None, so we just ensure it runs without error
    result = pipeline.emit_prices_updated()
    assert result is None

if __name__ == "__main__":
    pytest.main([__file__])