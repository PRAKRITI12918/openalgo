"""
Core Pydantic V2 models and domain schemas for the Strategy Engine.
Strictly decoupled, validated, and serialized data structures for quantitative options strategies.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Annotated, Any, Dict, List, Optional
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MarketRegime(str, Enum):
    """Market regime classification categories."""
    HIGH_IV_TRENDING = "HIGH_IV_TRENDING"
    LOW_IV_RANGING = "LOW_IV_RANGING"
    VOLATILITY_EXPANSION = "VOLATILITY_EXPANSION"
    MEAN_REVERTING = "MEAN_REVERTING"


class TrendDirection(str, Enum):
    """Directional trend classification."""
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class StrategyType(str, Enum):
    """Supported options strategy structures."""
    IRON_CONDOR = "IRON_CONDOR"
    BULL_CALL_SPREAD = "BULL_CALL_SPREAD"
    BEAR_PUT_SPREAD = "BEAR_PUT_SPREAD"
    CALENDAR_SPREAD = "CALENDAR_SPREAD"
    RATIO_SPREAD = "RATIO_SPREAD"
    HEDGED_STRADDLE = "HEDGED_STRADDLE"  # Iron Butterfly
    SHORT_STRANGLE = "SHORT_STRANGLE"


class OptionType(str, Enum):
    """Option contract type."""
    CE = "CE"  # Call Option
    PE = "PE"  # Put Option


class OrderAction(str, Enum):
    """Order transaction action."""
    BUY = "BUY"
    SELL = "SELL"


class SignalType(str, Enum):
    """Strategy lifecycle signal types."""
    ENTRY = "ENTRY"
    EXIT = "EXIT"
    STOP_LOSS = "STOP_LOSS"
    TARGET = "TARGET"
    TRAILING_STOP = "TRAILING_STOP"
    HEDGE_ADJUSTMENT = "HEDGE_ADJUSTMENT"
    NO_ACTION = "NO_ACTION"


class UnderlyingIndex(str, Enum):
    """Supported Indian Index Underlyings."""
    NIFTY = "NIFTY"
    BANKNIFTY = "BANKNIFTY"
    SENSEX = "SENSEX"

    @property
    def strike_step(self) -> float:
        """Standard strike step size for the index."""
        if self == UnderlyingIndex.NIFTY:
            return 50.0
        elif self == UnderlyingIndex.BANKNIFTY:
            return 100.0
        elif self == UnderlyingIndex.SENSEX:
            return 100.0
        return 50.0

    @property
    def default_lot_size(self) -> int:
        """Standard lot size for the index options."""
        if self == UnderlyingIndex.NIFTY:
            return 25  # standard NSE lot
        elif self == UnderlyingIndex.BANKNIFTY:
            return 15
        elif self == UnderlyingIndex.SENSEX:
            return 10
        return 25


class ExpiryType(str, Enum):
    """Expiry selection horizon."""
    CURRENT_WEEKLY = "CURRENT_WEEKLY"
    NEXT_WEEKLY = "NEXT_WEEKLY"
    MONTHLY = "MONTHLY"


class HedgeActionType(str, Enum):
    """Dynamic hedge action classifications."""
    ROLL_UNTESTED_SIDE = "ROLL_UNTESTED_SIDE"
    ADD_WING_PROTECTION = "ADD_WING_PROTECTION"
    DELTA_NEUTRALIZE = "DELTA_NEUTRALIZE"
    SQUARE_OFF = "SQUARE_OFF"
    NO_HEDGE_NEEDED = "NO_HEDGE_NEEDED"


class Greeks(BaseModel):
    """Black-Scholes Greek values for an option or aggregate portfolio."""
    model_config = ConfigDict(frozen=True, extra="ignore")

    delta: float = Field(..., description="Option Delta (-1.0 to 1.0)")
    gamma: float = Field(0.0, description="Option Gamma (change in delta per unit price move)")
    theta: float = Field(0.0, description="Option Theta (daily time decay in INR/points)")
    vega: float = Field(0.0, description="Option Vega (PnL change per 1% change in IV)")
    rho: float = Field(0.0, description="Option Rho (sensitivity to interest rate)")
    iv: float = Field(0.0, description="Implied Volatility in decimal (e.g. 0.15 for 15%)")


class OptionStrikeData(BaseModel):
    """Market depth and pricing data for a single strike option contract."""
    model_config = ConfigDict(extra="ignore")

    strike: float = Field(..., gt=0, description="Strike price")
    option_type: OptionType = Field(..., description="CE or PE")
    ltp: float = Field(..., ge=0, description="Last traded price")
    bid: float = Field(0.0, ge=0, description="Best bid price")
    ask: float = Field(0.0, ge=0, description="Best ask price")
    open_interest: int = Field(0, ge=0, description="Open Interest in contracts/shares")
    volume: int = Field(0, ge=0, description="Traded volume")
    iv: float = Field(0.0, ge=0, description="Implied volatility (0.15 = 15%)")
    greeks: Optional[Greeks] = Field(None, description="Computed Greeks")
    expiry: str = Field(..., description="Expiry date string (YYYY-MM-DD)")

    @property
    def bid_ask_spread(self) -> float:
        """Bid-ask spread in currency."""
        if self.ask > 0 and self.bid > 0:
            return max(0.0, self.ask - self.bid)
        return 0.0

    @property
    def spread_percentage(self) -> float:
        """Bid-ask spread relative to LTP percentage."""
        if self.ltp > 0 and self.ask > 0 and self.bid > 0:
            return (self.ask - self.bid) / self.ltp
        return 0.0


class OptionChainSnapshot(BaseModel):
    """Point-in-time option chain snapshot for an index and expiry."""
    model_config = ConfigDict(extra="ignore")

    underlying: UnderlyingIndex = Field(..., description="Underlying Index")
    spot_price: float = Field(..., gt=0, description="Current spot price")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Snapshot timestamp")
    expiry: str = Field(..., description="Target expiry date (YYYY-MM-DD)")
    strikes: List[OptionStrikeData] = Field(default_factory=list, description="All strikes for this expiry")
    pcr: Optional[float] = Field(None, description="Calculated Put-Call Ratio for the expiry")
    atm_strike: Optional[float] = Field(None, description="ATM strike price based on spot and step")

    @model_validator(mode="after")
    def compute_defaults(self) -> "OptionChainSnapshot":
        # Calculate ATM strike if not set
        if self.atm_strike is None and self.spot_price > 0:
            step = self.underlying.strike_step
            self.atm_strike = round(self.spot_price / step) * step

        # Calculate PCR if not set
        if self.pcr is None and self.strikes:
            total_pe_oi = sum(s.open_interest for s in self.strikes if s.option_type == OptionType.PE)
            total_ce_oi = sum(s.open_interest for s in self.strikes if s.option_type == OptionType.CE)
            self.pcr = (total_pe_oi / total_ce_oi) if total_ce_oi > 0 else 1.0
        return self

    def get_strike(self, strike: float, option_type: OptionType) -> Optional[OptionStrikeData]:
        """Lookup specific strike and option type in the snapshot."""
        for s in self.strikes:
            if abs(s.strike - strike) < 1e-4 and s.option_type == option_type:
                return s
        return None


class MarketIndicators(BaseModel):
    """Quantitative technical and volatility indicator input."""
    model_config = ConfigDict(extra="ignore")

    spot_ltp: float = Field(..., gt=0, description="Underlying Spot LTP")
    atr: float = Field(..., gt=0, description="Average True Range (e.g. 14-period on 15m/daily)")
    adx: float = Field(..., ge=0, le=100, description="Average Directional Index (trend strength)")
    india_vix: float = Field(..., gt=0, description="India VIX current level")
    pcr: float = Field(..., gt=0, description="Put-Call Ratio (OI based)")
    short_term_trend: TrendDirection = Field(TrendDirection.NEUTRAL, description="Directional bias")
    vix_change_pct: float = Field(0.0, description="Day-over-day or intraday VIX % change")
    fast_ema: Optional[float] = Field(None, description="Fast EMA (e.g. 9/20 EMA)")
    slow_ema: Optional[float] = Field(None, description="Slow EMA (e.g. 21/50 EMA)")
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class RegimeClassification(BaseModel):
    """Detailed market regime classification result."""
    model_config = ConfigDict(frozen=True, extra="ignore")

    regime: MarketRegime = Field(..., description="Classified market regime")
    trend: TrendDirection = Field(..., description="Trend direction")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Classification confidence score")
    description: str = Field(..., description="Human-readable rationale for regime classification")
    recommended_strategies: List[StrategyType] = Field(default_factory=list, description="Compatible strategy setups")
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class OptionLeg(BaseModel):
    """Individual option position leg in a multi-leg strategy."""
    model_config = ConfigDict(extra="ignore")

    symbol: str = Field(..., description="Unique trading symbol / token")
    underlying: UnderlyingIndex = Field(..., description="Underlying index")
    strike: float = Field(..., gt=0, description="Strike price")
    option_type: OptionType = Field(..., description="CE or PE")
    expiry: str = Field(..., description="Expiry date string (YYYY-MM-DD)")
    action: OrderAction = Field(..., description="BUY or SELL")
    quantity: int = Field(..., gt=0, description="Quantity in units (e.g. multiple of lot size)")
    target_delta: Optional[float] = Field(None, description="Target delta at strike selection")
    actual_delta: Optional[float] = Field(None, description="Current or entry delta")
    entry_price: float = Field(0.0, ge=0.0, description="Execution / expected entry price")
    current_price: float = Field(0.0, ge=0.0, description="Current market price (LTP)")
    greeks: Optional[Greeks] = Field(None, description="Leg Greeks")
    is_hedge_leg: bool = Field(False, description="Whether this leg serves purely as wing protection/hedge")

    @property
    def signed_quantity(self) -> int:
        """Signed quantity (+ for LONG/BUY, - for SHORT/SELL)."""
        return self.quantity if self.action == OrderAction.BUY else -self.quantity

    @property
    def net_delta(self) -> float:
        """Net position delta contributed by this leg."""
        delta = self.actual_delta if self.actual_delta is not None else (self.greeks.delta if self.greeks else 0.0)
        return self.signed_quantity * delta


class TradeSignal(BaseModel):
    """Complete actionable trading signal emitted by the strategy engine."""
    model_config = ConfigDict(extra="ignore")

    signal_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique signal ID")
    strategy_type: StrategyType = Field(..., description="Target strategy type")
    signal_type: SignalType = Field(..., description="Signal action type (ENTRY, EXIT, STOP_LOSS, etc.)")
    underlying: UnderlyingIndex = Field(..., description="Target index underlying")
    regime: MarketRegime = Field(..., description="Market regime under which signal was generated")
    legs: List[OptionLeg] = Field(..., min_length=1, description="Option legs to execute")
    entry_credit_debit: float = Field(0.0, description="Net premium credit (+ve) or debit (-ve) per unit")
    max_profit: Optional[float] = Field(None, description="Theoretical maximum profit")
    max_loss: Optional[float] = Field(None, description="Theoretical maximum loss")
    stop_loss_threshold: Optional[float] = Field(None, description="Max allowable loss before stop trigger")
    target_threshold: Optional[float] = Field(None, description="Profit target threshold")
    trailing_stop_step: Optional[float] = Field(None, description="Trailing step size in PnL/points")
    reason: str = Field("", description="Reasoning and indicator context for signal")
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class PositionState(BaseModel):
    """Active multi-leg portfolio position state with dynamic Greek tracking."""
    model_config = ConfigDict(extra="ignore")

    position_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Unique position identifier")
    strategy_type: StrategyType = Field(..., description="Strategy type")
    underlying: UnderlyingIndex = Field(..., description="Underlying Index")
    entry_regime: MarketRegime = Field(..., description="Regime at initial entry")
    current_regime: Optional[MarketRegime] = Field(None, description="Current market regime")
    legs: List[OptionLeg] = Field(default_factory=list, description="Currently active legs in position")
    net_delta: float = Field(0.0, description="Aggregate portfolio net delta")
    net_gamma: float = Field(0.0, description="Aggregate portfolio net gamma")
    net_theta: float = Field(0.0, description="Aggregate portfolio net daily theta")
    net_vega: float = Field(0.0, description="Aggregate portfolio net vega")
    total_pnl: float = Field(0.0, description="Current unrealized + realized PnL")
    max_drawdown: float = Field(0.0, description="Peak-to-trough maximum drawdown experienced")
    is_active: bool = Field(True, description="Whether position is currently active")
    entry_time: datetime = Field(default_factory=datetime.utcnow)
    last_updated: datetime = Field(default_factory=datetime.utcnow)

    def recalculate_greeks(self) -> None:
        """Aggregate Greeks across all active legs."""
        t_delta, t_gamma, t_theta, t_vega = 0.0, 0.0, 0.0, 0.0
        for leg in self.legs:
            sign = 1.0 if leg.action == OrderAction.BUY else -1.0
            qty = float(leg.quantity)
            if leg.greeks:
                t_delta += sign * qty * leg.greeks.delta
                t_gamma += sign * qty * leg.greeks.gamma
                t_theta += sign * qty * leg.greeks.theta
                t_vega += sign * qty * leg.greeks.vega
            elif leg.actual_delta is not None:
                t_delta += sign * qty * leg.actual_delta
        self.net_delta = round(t_delta, 4)
        self.net_gamma = round(t_gamma, 6)
        self.net_theta = round(t_theta, 2)
        self.net_vega = round(t_vega, 2)
        self.last_updated = datetime.utcnow()


class HedgeAdjustmentSignal(BaseModel):
    """Instruction generated by HedgeManager to dynamically rebalance risk."""
    model_config = ConfigDict(extra="ignore")

    adjustment_id: str = Field(default_factory=lambda: str(uuid.uuid4()), description="Adjustment ID")
    position_id: str = Field(..., description="Target position ID being adjusted")
    trigger_reason: str = Field(..., description="Specific Greek or structural trigger reason")
    imbalance_type: str = Field(..., description="DELTA_BREACH, GAMMA_SPIKE, TESTED_SIDE_PRESSURE, etc.")
    hedge_action: HedgeActionType = Field(..., description="Prescribed hedge adjustment action")
    legs_to_close: List[OptionLeg] = Field(default_factory=list, description="Existing legs to square off")
    legs_to_open: List[OptionLeg] = Field(default_factory=list, description="New hedge / replacement legs to enter")
    expected_delta_after: float = Field(0.0, description="Expected portfolio net delta post-adjustment")
    timestamp: datetime = Field(default_factory=datetime.utcnow)
