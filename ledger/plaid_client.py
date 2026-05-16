"""Thin wrapper around the Plaid Python SDK.

Centralizes client construction and the few Plaid calls ledger actually
uses. If Plaid's SDK shape changes, this is the one file that needs
updating.
"""

from __future__ import annotations

from typing import Any

import plaid
from plaid.api import plaid_api
from plaid.model.accounts_balance_get_request import AccountsBalanceGetRequest
from plaid.model.country_code import CountryCode
from plaid.model.investments_holdings_get_request import (
    InvestmentsHoldingsGetRequest,
)
from plaid.model.item_get_request import ItemGetRequest
from plaid.model.item_public_token_exchange_request import (
    ItemPublicTokenExchangeRequest,
)
from plaid.model.link_token_create_request import LinkTokenCreateRequest
from plaid.model.link_token_create_request_user import LinkTokenCreateRequestUser
from plaid.model.products import Products
from plaid.model.transactions_sync_request import TransactionsSyncRequest

from .config import Config


# Map env string to Plaid environment URL.
_PLAID_HOST = {
    "sandbox": plaid.Environment.Sandbox,
    "production": plaid.Environment.Production,
}


def make_client(cfg: Config) -> plaid_api.PlaidApi:
    """Return a configured Plaid API client."""
    host = _PLAID_HOST.get(cfg.plaid_env)
    if host is None:
        raise RuntimeError(
            f"Unsupported PLAID_ENV: {cfg.plaid_env}. Use sandbox or production."
        )

    configuration = plaid.Configuration(
        host=host,
        api_key={
            "clientId": cfg.plaid_client_id,
            "secret": cfg.plaid_secret,
        },
    )
    return plaid_api.PlaidApi(plaid.ApiClient(configuration))


def create_link_token(client: plaid_api.PlaidApi) -> str:
    """Create a Link token for the Plaid Link widget.

    Required: transactions (works at every supported institution).
    Required-if-supported: investments (returned at brokerages, skipped at
    plain banks without breaking the Link flow). This is the right mix for
    a personal aggregator: investments where the bank has them, transactions
    everywhere.
    """
    request = LinkTokenCreateRequest(
        products=[Products("transactions")],
        required_if_supported_products=[Products("investments")],
        client_name="ledger",
        country_codes=[CountryCode("US")],
        language="en",
        user=LinkTokenCreateRequestUser(client_user_id="ledger-personal"),
    )
    response = client.link_token_create(request)
    return response.link_token


def exchange_public_token(
    client: plaid_api.PlaidApi, public_token: str
) -> tuple[str, str]:
    """Exchange a one-time public token for a long-lived access token.

    Returns (access_token, item_id).
    """
    request = ItemPublicTokenExchangeRequest(public_token=public_token)
    response = client.item_public_token_exchange(request)
    return response.access_token, response.item_id


def get_item_institution(
    client: plaid_api.PlaidApi, access_token: str
) -> str:
    """Return the institution_id for an item (used to look up institution name)."""
    request = ItemGetRequest(access_token=access_token)
    response = client.item_get(request)
    return response.item.institution_id


def get_institution_name(
    client: plaid_api.PlaidApi, institution_id: str
) -> str:
    """Look up institution display name by id."""
    from plaid.model.institutions_get_by_id_request import (
        InstitutionsGetByIdRequest,
    )

    request = InstitutionsGetByIdRequest(
        institution_id=institution_id,
        country_codes=[CountryCode("US")],
    )
    response = client.institutions_get_by_id(request)
    return response.institution.name


def get_balances(
    client: plaid_api.PlaidApi, access_token: str
) -> Any:
    """Fetch current balances for all accounts under an item."""
    request = AccountsBalanceGetRequest(access_token=access_token)
    return client.accounts_balance_get(request)


def get_holdings(
    client: plaid_api.PlaidApi, access_token: str
) -> Any:
    """Fetch per-position investment holdings + securities."""
    request = InvestmentsHoldingsGetRequest(access_token=access_token)
    return client.investments_holdings_get(request)


def sync_transactions(
    client: plaid_api.PlaidApi,
    access_token: str,
    cursor: str | None = None,
) -> Any:
    """Sync transactions incrementally using a cursor.

    First call: cursor=None. Subsequent calls: pass the previous next_cursor.
    """
    request = TransactionsSyncRequest(
        access_token=access_token,
        cursor=cursor or "",
    )
    return client.transactions_sync(request)
