"""
Alias export for Mock Execution Engine.
Re-exports services.execution.mock_execution_engine to match src/engine conventions.
"""

from services.execution.mock_execution_engine import (
    MOCK_MODE,
    BaseMockBrokerClient,
    BasePriceProvider,
    FaultInjector,
    MockExecutionEngine,
    MockPriceProvider,
    SimulatedBrokerClient,
    format_simulated_symbol,
)

__all__ = [
    "MOCK_MODE",
    "BaseMockBrokerClient",
    "BasePriceProvider",
    "FaultInjector",
    "MockExecutionEngine",
    "MockPriceProvider",
    "SimulatedBrokerClient",
    "format_simulated_symbol",
]
