from __future__ import annotations


def format_brl(value: float | int | None) -> str:
    if value is None:
        return "-"
    formatted = f"R$ {float(value):,.2f}"
    return formatted.replace(",", "X").replace(".", ",").replace("X", ".")
