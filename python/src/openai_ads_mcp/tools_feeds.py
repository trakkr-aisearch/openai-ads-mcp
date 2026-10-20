"""Product feed MCP tools for OpenAI Ads."""

from __future__ import annotations

from ._core import *


def _variant_payload(variant: Any, where: str) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(variant, dict):
        return None, _bad_request(f"{where} must be an object.")
    if id_err := _validate_non_empty(f"{where}.id", variant.get("id")):
        return None, id_err
    out: dict[str, Any] = {"id": variant["id"].strip()}
    if variant.get("title") is not None:
        if not isinstance(variant["title"], str):
            return None, _bad_request(f"{where}.title must be a string.")
        out["title"] = variant["title"]
    price = variant.get("price")
    if price is not None:
        if not isinstance(price, dict):
            return None, _bad_request(f"{where}.price must be an object with amount and currency.")
        amount = price.get("amount")
        currency = price.get("currency")
        if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
            return None, _bad_request(f"{where}.price.amount must be a non-negative integer.")
        if not isinstance(currency, str) or len(currency) != 3:
            return None, _bad_request(f"{where}.price.currency must be a 3-letter currency code.")
        out["price"] = {"amount": amount, "currency": currency}
    availability = variant.get("availability")
    if availability is not None:
        if not isinstance(availability, dict):
            return None, _bad_request(f"{where}.availability must be an object.")
        if "available" in availability and not isinstance(availability["available"], bool):
            return None, _bad_request(f"{where}.availability.available must be true or false.")
        if "status" in availability and not isinstance(availability["status"], str):
            return None, _bad_request(f"{where}.availability.status must be a string.")
        out["availability"] = {
            key: availability[key] for key in ("available", "status") if key in availability
        }
    return out, None


def _products_payload(products: Any) -> tuple[list[dict[str, Any]] | None, str | None]:
    items, err = _coerce_json(products, "products")
    if err:
        return None, err
    if not isinstance(items, list) or not items:
        return None, _bad_request("products must be a non-empty list.")
    out: list[dict[str, Any]] = []
    for index, product in enumerate(items):
        where = f"products[{index}]"
        if not isinstance(product, dict):
            return None, _bad_request(f"{where} must be an object.")
        if id_err := _validate_non_empty(f"{where}.id", product.get("id")):
            return None, id_err
        variants = product.get("variants")
        if not isinstance(variants, list) or not variants:
            return None, _bad_request(f"{where}.variants must be a non-empty list.")
        parsed_variants = []
        for variant_index, variant in enumerate(variants):
            parsed, variant_err = _variant_payload(variant, f"{where}.variants[{variant_index}]")
            if variant_err:
                return None, variant_err
            parsed_variants.append(parsed)
        out.append({"id": product["id"].strip(), "variants": parsed_variants})
    return out, None


# The price unit is unverified, so a wrong guess would reprice live ads 100x: off unless the operator opts in.
@ads_tool(
    writes=True,
    destructive=True,
    idempotent=True,
    open_world=True,
    enabled=_truthy(os.environ.get("OPENAI_ADS_ENABLE_FEED_WRITES")),
)
async def update_product_feed_products(feed_id: str, products: Any) -> str:
    """Patch price, title, or availability on products in a product feed.

    Only the fields you send change. Price changes show up in live product ads.
    The price unit is UNVERIFIED (see products below). Listed only when the
    server sets OPENAI_ADS_ENABLE_FEED_WRITES=1.

    Args:
        feed_id: Product feed id, as in an ad group's product_set.product_feed_id.
        products: Non-empty list of {"id": "<product id>", "variants": [{"id": "<variant id>",
            "title": "...", "price": {"amount": 2500, "currency": "USD"},
            "availability": {"available": true, "status": "in_stock"}}]}. price.amount is a
            non-negative integer; the spec does not state its unit, minor units are assumed
            (2500 = 25.00 USD), so verify on one product before a bulk change.
    """
    if feed_err := _validate_non_empty("feed_id", feed_id, maximum=255):
        return feed_err
    payload, payload_err = _products_payload(products)
    if payload_err:
        return payload_err
    client, client_err = _get_client_or_error()
    if client_err:
        return client_err
    try:
        return _ok(await client.patch(f"/feeds/{feed_id.strip()}/products", json={"products": payload}))
    except OpenAIAdsAPIError as e:
        return _err(e)


__all__ = ("update_product_feed_products",)
