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

def digits_only(s: str | None) -> str:
    return re.sub(r"\D+", "", s or "")

def validate_cpf(cpf: str) -> bool:
    cpf = digits_only(cpf)
    if len(cpf) != 11:
        return False
    if cpf == cpf[0] * 11:
        return False
    nums = [int(x) for x in cpf]
    # first digit
    s1 = sum(nums[i] * (10 - i) for i in range(9))
    d1 = 0 if (s1 % 11) < 2 else 11 - (s1 % 11)
    if nums[9] != d1:
        return False
    # second digit
    s2 = sum(nums[i] * (11 - i) for i in range(10))
    d2 = 0 if (s2 % 11) < 2 else 11 - (s2 % 11)
    return nums[10] == d2

def validate_cnpj(cnpj: str) -> bool:
    cnpj = digits_only(cnpj)
    if len(cnpj) != 14:
        return False
    if cnpj == cnpj[0] * 14:
        return False
    nums = [int(x) for x in cnpj]
    w1 = [5,4,3,2,9,8,7,6,5,4,3,2]
    w2 = [6,5,4,3,2,9,8,7,6,5,4,3,2]
    s1 = sum(nums[i] * w1[i] for i in range(12))
    d1 = 0 if (s1 % 11) < 2 else 11 - (s1 % 11)
    if nums[12] != d1:
        return False
    s2 = sum(nums[i] * w2[i] for i in range(13))
    d2 = 0 if (s2 % 11) < 2 else 11 - (s2 % 11)
    return nums[13] == d2

def validate_cpf_cnpj(value: str | None) -> bool:
    d = digits_only(value)
    if len(d) == 11:
        return validate_cpf(d)
    if len(d) == 14:
        return validate_cnpj(d)
    return False