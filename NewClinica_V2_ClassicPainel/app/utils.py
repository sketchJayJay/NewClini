# -*- coding: utf-8 -*-
from __future__ import annotations
import re
from decimal import Decimal, ROUND_HALF_UP

def parse_brl_to_cents(value: str | None) -> int:
    """Parse valores brasileiros (ex: '1.234,56', '480,80', 'R$ 50') para centavos (int).
    Regras:
    - Se tiver ',' como separador decimal, usa como decimal.
    - Se tiver '.' e ',' assume '.' milhar e ',' decimal.
    - Se tiver só '.' assume decimal.
    - Se tiver só dígitos, assume reais inteiros.
    """
    if value is None:
        return 0
    s = str(value).strip()
    if not s:
        return 0
    s = s.replace("R$", "").replace(" ", "")
    # Mantém dígitos e separadores
    s = re.sub(r"[^0-9,\.\-]", "", s)

    neg = s.startswith("-")
    s = s[1:] if neg else s

    if not s:
        return 0

    if "," in s and "." in s:
        # milhar '.' decimal ','
        s = s.replace(".", "")
        s = s.replace(",", ".")
    elif "," in s:
        s = s.replace(".", "")  # trata '.' como milhar (se tiver)
        s = s.replace(",", ".")
    else:
        # só '.' ou só dígitos
        pass

    if re.fullmatch(r"\d+", s):
        dec = Decimal(s)
    else:
        # evita múltiplos pontos
        parts = s.split(".")
        if len(parts) > 2:
            s = "".join(parts[:-1]) + "." + parts[-1]
        dec = Decimal(s)

    cents = int((dec.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100))
    return -cents if neg else cents

def cents_to_brl(cents: int | None) -> str:
    if cents is None:
        cents = 0
    neg = cents < 0
    cents = abs(int(cents))
    reais = cents // 100
    cent = cents % 100
    # formata milhar com ponto
    reais_str = f"{reais:,}".replace(",", ".")
    out = f"{reais_str},{cent:02d}"
    return f"-{out}" if neg else out

def today_yyyy_mm_dd() -> str:
    from datetime import date
    return date.today().isoformat()
