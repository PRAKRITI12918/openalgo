# api/funds.py

import json
import os

import httpx

from broker.dhan.api.baseurl import get_url
from broker.dhan.api.order_api import get_positions
from broker.dhan.mapping.order_data import map_position_data
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def test_auth_token(auth_token):
    """Test if the auth token is valid by making a simple API call to funds endpoint."""
    api_key = os.getenv("BROKER_API_KEY")

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    headers = {
        "access-token": auth_token,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        url = get_url("/v2/fundlimit")
        res = client.get(url, headers=headers)
        res.status = res.status_code
        response_data = json.loads(res.text)

        error_type = str(response_data.get("errorType") or "")
        status = str(response_data.get("status") or "").lower()

        # Check for authentication errors
        if (
            res.status_code == 401
            or "invalid_authentication" in error_type.lower()
            or "auth" in error_type.lower()
            or "token" in error_type.lower()
            or "session" in error_type.lower()
        ):
            error_msg = response_data.get("errorMessage") or response_data.get("message") or "Invalid authentication token"
            return False, error_msg

        # Check for other error types
        if error_type or status in {"error", "failed", "failure"} or res.status_code >= 400:
            error_msg = (
                response_data.get("errors")
                or response_data.get("errorMessage")
                or response_data.get("message")
                or f"API error (HTTP {res.status_code})"
            )
            return False, str(error_msg)

        # If we get here, authentication is valid
        return True, None

    except Exception as e:
        logger.error(f"Error testing auth token: {str(e)}")
        return False, f"Error validating authentication: {str(e)}"


def get_margin_data(auth_token):
    """Fetch margin data from Dhan API using the provided auth token."""
    api_key = os.getenv("BROKER_API_KEY")

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    headers = {
        "access-token": auth_token,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    url = get_url("/v2/fundlimit")
    res = client.get(url, headers=headers)
    # Add status attribute for compatibility with existing codebase
    res.status = res.status_code
    try:
        margin_data = json.loads(res.text)
    except Exception as e:
        logger.error(f"Failed to parse Dhan margin data response: {res.text}")
        raise ValueError(f"Failed to parse Dhan API response (HTTP {res.status_code}): {e}")

    logger.info(f"Dhan /v2/fundlimit raw response: {margin_data}")

    error_type = str(margin_data.get("errorType") or "")
    status = str(margin_data.get("status") or "").lower()

    # Check for authentication errors first
    is_auth_error = (
        res.status_code == 401
        or "invalid_authentication" in error_type.lower()
        or "token" in error_type.lower()
        or "auth" in error_type.lower()
        or "session" in error_type.lower()
    )
    if is_auth_error:
        error_msg = margin_data.get("errorMessage") or margin_data.get("message") or "Invalid authentication token or Dhan session expired"
        logger.error(f"Dhan authentication error: {error_msg}")
        raise PermissionError(f"Dhan authentication error: {error_msg}")

    if error_type or status in {"error", "failed", "failure"} or res.status_code >= 400:
        error_msg = (
            margin_data.get("errors")
            or margin_data.get("errorMessage")
            or margin_data.get("message")
            or f"HTTP {res.status_code}"
        )
        logger.error(f"Error fetching Dhan margin data: [{error_type or status}] {error_msg}")
        raise ValueError(f"Dhan API error: {error_msg}")

    try:
        position_book = get_positions(auth_token)

        logger.info(f"Dhan /v2/positions raw response: {position_book}")

        # Check if position_book is an error response
        if isinstance(position_book, dict) and (
            position_book.get("errorType") or str(position_book.get("status", "")).lower() in {"error", "failed", "failure"}
        ):
            pos_err_type = str(position_book.get("errorType") or "")
            pos_is_auth_error = (
                "invalid_authentication" in pos_err_type.lower()
                or "token" in pos_err_type.lower()
                or "auth" in pos_err_type.lower()
                or "session" in pos_err_type.lower()
            )
            if pos_is_auth_error:
                error_msg = position_book.get("errorMessage") or position_book.get("message") or "Dhan session expired"
                logger.error(f"Dhan positions authentication error: {error_msg}")
                raise PermissionError(f"Dhan authentication error: {error_msg}")

            logger.error(
                f"Error getting positions: [{pos_err_type}] {position_book.get('errorMessage') or position_book.get('errors') or 'Unknown error'}"
            )
            total_realised = 0
            total_unrealised = 0
        else:
            # If successful, process the positions
            def sum_realised_unrealised(position_book):
                total_realised = 0
                total_unrealised = 0
                if isinstance(position_book, list):
                    total_realised = sum(
                        float(position.get("realizedProfit", 0) or 0) for position in position_book
                    )
                    total_unrealised = sum(
                        float(position.get("unrealizedProfit", 0) or 0) for position in position_book
                    )
                return total_realised, total_unrealised

            total_realised, total_unrealised = sum_realised_unrealised(position_book)

        # Dhan's "availabelBalance" (their spelling) includes pledged
        # collateral, confirmed against a live account -- double-counting
        # against the separately reported "collateral" field below, same
        # class of bug as GitHub issue #1582. Subtract collateralAmount to
        # get the actual cash-only balance.
        raw_avail = (
            margin_data.get("availabelBalance")
            if "availabelBalance" in margin_data
            else margin_data.get("availableBalance", 0)
        ) or 0
        collateral = margin_data.get("collateralAmount") or 0
        available_cash = float(raw_avail) - float(collateral)
        utilized = float(margin_data.get("utilizedAmount") or 0)

        # Construct and return the processed margin data with null checks
        processed_margin_data = {
            "availablecash": f"{available_cash:.2f}",
            "collateral": f"{float(collateral):.2f}",
            "m2munrealized": f"{total_unrealised:.2f}",
            "m2mrealized": f"{total_realised:.2f}",
            "utiliseddebits": f"{utilized:.2f}",
        }
        logger.info(f"Dhan processed margin data: {processed_margin_data}")
        return processed_margin_data
    except (PermissionError, ValueError):
        raise
    except KeyError as e:
        logger.error(f"KeyError in processing Dhan margin data: {e}")
        raise ValueError(f"Unexpected Dhan margin data structure: missing key {e}")
    except Exception as e:
        logger.exception(f"Unexpected error processing Dhan margin data: {e}")
        raise ValueError(f"Error processing Dhan margin data: {e}")
