"""Currency conversion and exchange rates against USD base currency."""

CURRENCY_RATES = {
    "USD": 1.0,
    "EUR": 1.08,
    "GBP": 1.28,
    "INR": 0.012,
    "CAD": 0.74,
    "AUD": 0.66,
    "JPY": 0.0065,
    "SGD": 0.75,
}

CURRENCY_SYMBOLS = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "INR": "₹",
    "CAD": "C$",
    "AUD": "A$",
    "JPY": "¥",
    "SGD": "S$",
}


def to_usd(amount: float | int | str | None, currency: str = "USD") -> float:
    """Convert an amount from a given currency to USD base currency."""
    try:
        val = float(amount or 0.0)
    except (ValueError, TypeError):
        val = 0.0
    rate = CURRENCY_RATES.get((currency or "USD").upper().strip(), 1.0)
    return round(val * rate, 2)


def format_currency(amount: float | int | str | None, currency: str = "USD") -> str:
    """Format an amount with its currency symbol."""
    try:
        val = float(amount or 0.0)
    except (ValueError, TypeError):
        val = 0.0
    sym = CURRENCY_SYMBOLS.get((currency or "USD").upper().strip(), "$")
    return f"{sym}{val:,.2f}"
