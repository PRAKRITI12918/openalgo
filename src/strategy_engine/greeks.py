"""
Black-Scholes Option Pricing and Analytical Greeks Engine.
Provides robust calculation of Delta, Gamma, Theta, Vega, Rho and Implied Volatility (IV)
with fallback solvers for extreme edge cases.
"""

from __future__ import annotations

import math
from typing import Optional, Tuple
from scipy.stats import norm

from src.strategy_engine.models import Greeks, OptionType


DEFAULT_RISK_FREE_RATE = 0.065  # 6.5% standard Indian repo rate benchmark


def black_scholes_price(
    spot: float,
    strike: float,
    dte_years: float,
    volatility: float,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    option_type: OptionType = OptionType.CE,
) -> float:
    """
    Calculate theoretical option price using standard Black-Scholes formula.

    Args:
        spot: Current underlying spot price
        strike: Option strike price
        dte_years: Days to expiry in fractional years (e.g. 7/365)
        volatility: Annualized implied volatility in decimal (e.g. 0.15 for 15%)
        risk_free_rate: Annualized risk-free rate in decimal (default 0.065)
        option_type: OptionType.CE or OptionType.PE

    Returns:
        Theoretical option premium.
    """
    if spot <= 0 or strike <= 0:
        return 0.0

    # At or past expiry
    if dte_years <= 1e-6:
        if option_type == OptionType.CE:
            return max(0.0, spot - strike)
        else:
            return max(0.0, strike - spot)

    if volatility <= 1e-6:
        discounted_strike = strike * math.exp(-risk_free_rate * dte_years)
        if option_type == OptionType.CE:
            return max(0.0, spot - discounted_strike)
        else:
            return max(0.0, discounted_strike - spot)

    sqrt_t = math.sqrt(dte_years)
    d1 = (math.log(spot / strike) + (risk_free_rate + 0.5 * volatility**2) * dte_years) / (volatility * sqrt_t)
    d2 = d1 - volatility * sqrt_t

    if option_type == OptionType.CE:
        price = spot * norm.cdf(d1) - strike * math.exp(-risk_free_rate * dte_years) * norm.cdf(d2)
    else:
        price = strike * math.exp(-risk_free_rate * dte_years) * norm.cdf(-d2) - spot * norm.cdf(-d1)

    return max(0.0, price)


def calculate_greeks(
    spot: float,
    strike: float,
    dte_years: float,
    volatility: float,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    option_type: OptionType = OptionType.CE,
) -> Greeks:
    """
    Calculate analytical Black-Scholes Greeks for an option contract.

    Args:
        spot: Underlying spot price
        strike: Option strike price
        dte_years: Time to expiration in years
        volatility: Annualized implied volatility in decimal
        risk_free_rate: Risk-free interest rate
        option_type: OptionType.CE or OptionType.PE

    Returns:
        Greeks model containing Delta, Gamma, daily Theta, 1% Vega, Rho, and IV.
    """
    if spot <= 0 or strike <= 0:
        return Greeks(delta=0.0, gamma=0.0, theta=0.0, vega=0.0, rho=0.0, iv=volatility)

    # Edge case: At or near expiry
    if dte_years <= 1e-6:
        if option_type == OptionType.CE:
            delta = 1.0 if spot > strike else (0.5 if spot == strike else 0.0)
        else:
            delta = -1.0 if spot < strike else (-0.5 if spot == strike else 0.0)
        return Greeks(delta=delta, gamma=0.0, theta=0.0, vega=0.0, rho=0.0, iv=volatility)

    if volatility <= 1e-6:
        volatility = 0.0001

    sqrt_t = math.sqrt(dte_years)
    d1 = (math.log(spot / strike) + (risk_free_rate + 0.5 * volatility**2) * dte_years) / (volatility * sqrt_t)
    d2 = d1 - volatility * sqrt_t

    pdf_d1 = norm.pdf(d1)
    cdf_d1 = norm.cdf(d1)
    cdf_d2 = norm.cdf(d2)
    exp_rt = math.exp(-risk_free_rate * dte_years)

    # Gamma (identical for Call & Put)
    gamma = pdf_d1 / (spot * volatility * sqrt_t)

    # Vega (derivative with respect to sigma, scaled per 1% move in IV)
    vega_total = spot * sqrt_t * pdf_d1
    vega_1pct = vega_total * 0.01  # Per 1% IV move (standard trading convention)

    if option_type == OptionType.CE:
        delta = cdf_d1
        # Theta per year
        theta_annual = -(spot * pdf_d1 * volatility) / (2 * sqrt_t) - risk_free_rate * strike * exp_rt * cdf_d2
        # Rho per 1% change in interest rate
        rho = (strike * dte_years * exp_rt * cdf_d2) * 0.01
    else:
        delta = cdf_d1 - 1.0
        # Theta per year
        theta_annual = -(spot * pdf_d1 * volatility) / (2 * sqrt_t) + risk_free_rate * strike * exp_rt * norm.cdf(-d2)
        # Rho per 1% change in interest rate
        rho = (-strike * dte_years * exp_rt * norm.cdf(-d2)) * 0.01

    # Convert Theta to 1-day decay in currency points
    theta_daily = theta_annual / 365.0

    return Greeks(
        delta=round(float(delta), 4),
        gamma=round(float(gamma), 6),
        theta=round(float(theta_daily), 4),
        vega=round(float(vega_1pct), 4),
        rho=round(float(rho), 4),
        iv=round(float(volatility), 4),
    )


def implied_volatility(
    price: float,
    spot: float,
    strike: float,
    dte_years: float,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    option_type: OptionType = OptionType.CE,
    max_iterations: int = 100,
    tolerance: float = 1e-5,
) -> float:
    """
    Calculate Implied Volatility (IV) from option market price using Newton-Raphson with Bisection fallback.

    Args:
        price: Observed option market price (LTP)
        spot: Underlying spot price
        strike: Option strike price
        dte_years: Time to expiry in years
        risk_free_rate: Risk free rate
        option_type: OptionType.CE or OptionType.PE

    Returns:
        Implied volatility in decimal (e.g. 0.165 for 16.5%).
    """
    # Intrinsic value bounds check
    intrinsic = max(0.0, spot - strike) if option_type == OptionType.CE else max(0.0, strike - spot)
    if price <= intrinsic:
        return 0.01  # Minimum floor

    if dte_years <= 1e-6:
        return 0.15

    # Initial guess based on Corrado-Miller approximation
    sigma = 0.20

    # Newton-Raphson iteration
    for _ in range(max_iterations):
        theo_price = black_scholes_price(spot, strike, dte_years, sigma, risk_free_rate, option_type)
        diff = theo_price - price

        if abs(diff) < tolerance:
            return max(0.001, min(5.0, sigma))

        # Vega calculation for derivative
        sqrt_t = math.sqrt(dte_years)
        d1 = (math.log(spot / strike) + (risk_free_rate + 0.5 * sigma**2) * dte_years) / (sigma * sqrt_t)
        vega = spot * sqrt_t * norm.pdf(d1)

        if vega < 1e-8:
            break

        sigma -= diff / vega

        # Keep sigma within realistic bounds
        if sigma <= 0.001 or sigma > 5.0:
            break

    # Fallback to Bisection search if Newton-Raphson did not converge
    low_sigma = 0.001
    high_sigma = 5.0
    for _ in range(60):
        mid_sigma = (low_sigma + high_sigma) / 2.0
        theo_price = black_scholes_price(spot, strike, dte_years, mid_sigma, risk_free_rate, option_type)
        diff = theo_price - price

        if abs(diff) < tolerance:
            return round(mid_sigma, 4)

        if diff > 0:
            high_sigma = mid_sigma
        else:
            low_sigma = mid_sigma

    return round((low_sigma + high_sigma) / 2.0, 4)
