"""
Locale Formatter — Formato de numeros, monedas y fechas por pais.
Usa currency de ada_company_profile para personalizar.
"""

from datetime import datetime, date
from typing import Union

CURRENCY_CONFIG = {
    "COP": {"symbol": "$", "decimal": ",", "thousands": ".", "decimals": 0, "suffix": "", "name": "COP"},
    "USD": {"symbol": "$", "decimal": ".", "thousands": ",", "decimals": 2, "suffix": " USD", "name": "USD"},
    "MXN": {"symbol": "$", "decimal": ".", "thousands": ",", "decimals": 2, "suffix": " MXN", "name": "MXN"},
    "EUR": {"symbol": "\u20ac", "decimal": ",", "thousands": ".", "decimals": 2, "suffix": "", "name": "EUR"},
    "PEN": {"symbol": "S/", "decimal": ".", "thousands": ",", "decimals": 2, "suffix": "", "name": "PEN"},
    "CLP": {"symbol": "$", "decimal": ",", "thousands": ".", "decimals": 0, "suffix": " CLP", "name": "CLP"},
    "ARS": {"symbol": "$", "decimal": ",", "thousands": ".", "decimals": 2, "suffix": " ARS", "name": "ARS"},
    "BRL": {"symbol": "R$", "decimal": ",", "thousands": ".", "decimals": 2, "suffix": "", "name": "BRL"},
}

DATE_FORMATS = {
    "COP": "%d/%m/%Y",
    "MXN": "%d/%m/%Y",
    "USD": "%m/%d/%Y",
    "EUR": "%d/%m/%Y",
    "PEN": "%d/%m/%Y",
    "CLP": "%d/%m/%Y",
    "ARS": "%d/%m/%Y",
    "BRL": "%d/%m/%Y",
}

MONTH_NAMES_ES = [
    "", "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
]


def format_currency(value: Union[int, float], currency: str = "COP") -> str:
    """Formatea un valor monetario segun la moneda."""
    cfg = CURRENCY_CONFIG.get(currency.upper(), CURRENCY_CONFIG["COP"])

    if not isinstance(value, (int, float)):
        return str(value)

    abs_val = abs(value)
    neg = "-" if value < 0 else ""

    if cfg["decimals"] == 0:
        integer_part = str(int(round(abs_val)))
        decimal_part = ""
    else:
        integer_part = str(int(abs_val))
        frac = abs_val - int(abs_val)
        decimal_part = cfg["decimal"] + f"{frac:.{cfg['decimals']}f}"[2:]

    # Separador de miles
    digits = integer_part
    groups = []
    while len(digits) > 3:
        groups.insert(0, digits[-3:])
        digits = digits[:-3]
    groups.insert(0, digits)
    formatted_integer = cfg["thousands"].join(groups)

    return f"{neg}{cfg['symbol']}{formatted_integer}{decimal_part}{cfg['suffix']}"


def format_number(value: Union[int, float], currency: str = "COP") -> str:
    """Formatea un numero sin simbolo de moneda, usando separadores del locale."""
    cfg = CURRENCY_CONFIG.get(currency.upper(), CURRENCY_CONFIG["COP"])

    if not isinstance(value, (int, float)):
        return str(value)

    abs_val = abs(value)
    neg = "-" if value < 0 else ""

    if isinstance(value, int) or (isinstance(value, float) and value == int(value)):
        integer_part = str(int(abs_val))
        decimal_part = ""
    else:
        integer_part = str(int(abs_val))
        frac = abs_val - int(abs_val)
        decimal_part = cfg["decimal"] + f"{frac:.2f}"[2:]

    digits = integer_part
    groups = []
    while len(digits) > 3:
        groups.insert(0, digits[-3:])
        digits = digits[:-3]
    groups.insert(0, digits)
    formatted_integer = cfg["thousands"].join(groups)

    return f"{neg}{formatted_integer}{decimal_part}"


def format_date(d: Union[datetime, date, str, None], currency: str = "COP", long_format: bool = False) -> str:
    """Formatea una fecha segun el locale."""
    if d is None:
        return ""

    if isinstance(d, str):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
            try:
                d = datetime.strptime(d[:19], fmt)
                break
            except ValueError:
                continue
        else:
            return d[:10] if len(d) >= 10 else d

    if long_format and isinstance(d, (datetime, date)):
        day = d.day
        month = MONTH_NAMES_ES[d.month] if d.month <= 12 else str(d.month)
        year = d.year
        return f"{day} de {month} de {year}"

    fmt = DATE_FORMATS.get(currency.upper(), "%d/%m/%Y")
    return d.strftime(fmt) if isinstance(d, (datetime, date)) else str(d)


def get_currency_for_empresa(empresa_id: str) -> str:
    """Obtiene la moneda configurada para una empresa desde su DNA."""
    if not empresa_id:
        return "COP"
    try:
        from api.services.dna_loader import load_company_dna
        dna = load_company_dna(empresa_id)
        return dna.get("currency", "COP") or "COP"
    except Exception:
        return "COP"
