# -*- coding: utf-8 -*-
"""Importador simples do banco antigo (Hellen/new_clinica.db) para o NewClínica V2.

Uso:
    python tools/import_legacy_hellen.py "caminho/para/new_clinica.db"

O que importa:
- patients -> patients
- doctors  -> providers
- movements -> transactions

Observações:
- Categorias: tudo vai para 'Outros' (você pode recategorizar depois).
- Valores: convertidos para centavos (sem bug de vírgula/ponto).
"""
from __future__ import annotations

import sys
import os
import sqlite3
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

from app import create_app
from app.db import get_db, init_db, ensure_seed_data
from app.utils import today_yyyy_mm_dd

def to_cents(amount) -> int:
    if amount is None:
        return 0
    try:
        d = Decimal(str(amount))
    except Exception:
        return 0
    return int((d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) * 100))

def map_kind(t: str) -> str:
    t = (t or "").lower()
    if any(k in t for k in ["pagar", "saida", "saída", "despesa", "expense", "out"]):
        return "expense"
    return "income"

def map_payment(m: str) -> str:
    m = (m or "").lower()
    if "din" in m:
        return "cash"
    if "pix" in m:
        return "pix"
    if "card" in m or "cart" in m:
        return "card"
    if "transf" in m:
        return "transfer"
    return "other"

def main(old_db_path: str):
    old_db_path = os.path.abspath(old_db_path)
    if not os.path.exists(old_db_path):
        print("Arquivo não encontrado:", old_db_path)
        return 2

    app = create_app()
    with app.app_context():
        init_db()
        ensure_seed_data()
        db = get_db()

        # categoria Outros
        cat = db.execute("SELECT id FROM categories WHERE name='Outros'").fetchone()
        cat_id = int(cat["id"]) if cat else None

        src = sqlite3.connect(old_db_path)
        src.row_factory = sqlite3.Row

        # import doctors -> providers
        try:
            doctors = src.execute("SELECT * FROM doctors").fetchall()
        except Exception:
            doctors = []

        prov_map = {}
        for d in doctors:
            name = (d["name"] or "").strip()
            if not name:
                continue
            row = db.execute("SELECT id FROM providers WHERE name=?", (name,)).fetchone()
            if row:
                prov_id = int(row["id"])
            else:
                db.execute("INSERT INTO providers(name, role, default_repasse_percent) VALUES(?,?,?)", (name, "Dentista", 0))
                prov_id = int(db.execute("SELECT last_insert_rowid()").fetchone()[0])
            prov_map[int(d["id"])] = prov_id

        # import patients
        patients = src.execute("SELECT * FROM patients").fetchall()
        pat_map = {}
        for p in patients:
            name = (p["name"] or "").strip()
            if not name:
                continue
            # tenta achar por nome
            row = db.execute("SELECT id FROM patients WHERE name=?", (name,)).fetchone()
            if row:
                pid = int(row["id"])
            else:
                db.execute("INSERT INTO patients(name, phone, birth_date, notes) VALUES(?,?,?,?)", (name, p.get("phone"), None, ""))
                pid = int(db.execute("SELECT last_insert_rowid()").fetchone()[0])
            pat_map[int(p["id"])] = pid

        # import movements
        try:
            moves = src.execute("SELECT * FROM movements ORDER BY id ASC").fetchall()
        except Exception:
            moves = []

        imported = 0
        for m in moves:
            kind = map_kind(m["type"])
            status = "paid" if int(m["is_paid"] or 0) == 1 else "pending"
            date_eff = (m["paid_at"] or m["created_at"] or today_yyyy_mm_dd())
            date_eff = str(date_eff)[:10]  # YYYY-MM-DD
            due_date = m["due_date"]
            due_date = str(due_date)[:10] if due_date else None
            amount_cents = to_cents(m["amount"])
            if amount_cents == 0:
                continue
            payment_method = map_payment(m["method"])
            description = m["description"] or ""

            patient_id = pat_map.get(int(m["patient_id"])) if m["patient_id"] is not None else None
            provider_id = prov_map.get(int(m["doctor_id"])) if m["doctor_id"] is not None else None

            # evita duplicar: simples por assinatura
            exists = db.execute(
                "SELECT 1 FROM transactions WHERE kind=? AND status=? AND date=? AND amount_cents=? AND description=? AND patient_id IS ? LIMIT 1",
                (kind, status, date_eff, amount_cents, description, patient_id),
            ).fetchone()
            if exists:
                continue

            db.execute(
                "INSERT INTO transactions(kind,status,date,due_date,amount_cents,payment_method,description,patient_id,category_id,provider_id,repasse_percent) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (kind, status, date_eff, due_date, amount_cents, payment_method, description, patient_id, cat_id, provider_id, 0),
            )
            imported += 1

        db.commit()
        print(f"Importação concluída. Pacientes: {len(pat_map)} | Profissionais: {len(prov_map)} | Lançamentos: {imported}")
    return 0

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python tools/import_legacy_hellen.py caminho/para/new_clinica.db")
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
