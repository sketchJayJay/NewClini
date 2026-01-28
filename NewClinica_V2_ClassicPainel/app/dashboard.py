# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import date
from urllib.parse import quote
from flask import current_app
from flask import Blueprint, render_template, request, session
from .auth import login_required
from .db import get_db, get_open_cash_session_id
from .utils import cents_to_brl

bp = Blueprint("dashboard", __name__)

@bp.route("/")
@login_required
def index():
    db = get_db()
    finance_unlocked = bool(session.get("finance_unlocked"))
    today = date.today().isoformat()
    month_start = date.today().replace(day=1).isoformat()

    # Por segurança, o Financeiro não aparece na Home enquanto não for desbloqueado.
    # Depois do desbloqueio, mostramos o resumo normalmente.
    stats = None
    if finance_unlocked:
        def sum_cents(sql, params):
            row = db.execute(sql, params).fetchone()
            return int(row["s"] or 0)

        income_today = sum_cents(
            "SELECT SUM(amount_cents) s FROM transactions WHERE kind='income' AND status='paid' AND date=?",
            (today,),
        )
        expense_today = sum_cents(
            "SELECT SUM(amount_cents) s FROM transactions WHERE kind='expense' AND status='paid' AND date=?",
            (today,),
        )
        income_month = sum_cents(
            "SELECT SUM(amount_cents) s FROM transactions WHERE kind='income' AND status='paid' AND date>=?",
            (month_start,),
        )
        expense_month = sum_cents(
            "SELECT SUM(amount_cents) s FROM transactions WHERE kind='expense' AND status='paid' AND date>=?",
            (month_start,),
        )
        pending_receivables = sum_cents(
            "SELECT SUM(amount_cents) s FROM transactions WHERE kind='income' AND status='pending'",
            (),
        )
        pending_payables = sum_cents(
            "SELECT SUM(amount_cents) s FROM transactions WHERE kind='expense' AND status='pending'",
            (),
        )

        open_cash_id = get_open_cash_session_id()
        cash_total = 0
        if open_cash_id:
            cash_total = sum_cents(
                "SELECT SUM(amount_cents) s FROM transactions WHERE status='paid' AND payment_method='cash' AND cash_session_id=?",
                (open_cash_id,),
            )
            row_open = db.execute("SELECT open_balance_cents FROM cash_sessions WHERE id=?", (open_cash_id,)).fetchone()
            cash_total += int(row_open["open_balance_cents"] or 0)

        stats = {
            "income_today": cents_to_brl(income_today),
            "expense_today": cents_to_brl(expense_today),
            "income_month": cents_to_brl(income_month),
            "expense_month": cents_to_brl(expense_month),
            "pending_receivables": cents_to_brl(pending_receivables),
            "pending_payables": cents_to_brl(pending_payables),
            "cash_open": bool(open_cash_id),
            "cash_total": cents_to_brl(cash_total),
        }
    # Lembrete de aniversários (mostra na Home)
    tpl_row = db.execute("SELECT value FROM app_settings WHERE key='birthday_template'").fetchone()
    birthday_template = (tpl_row["value"] if tpl_row and tpl_row["value"] else "Oi {nome}! 🎉 A {clinica} deseja um dia incrível! 🙂")
    clinica = current_app.config.get("CLINIC_NAME", "NewClínica")

    mmdd = date.today().strftime("%m-%d")
    bday_rows = db.execute(
        "SELECT id, name, phone, birth_date FROM patients WHERE birth_date IS NOT NULL AND birth_date!='' AND substr(birth_date,6,5)=? ORDER BY name COLLATE NOCASE",
        (mmdd,),
    ).fetchall()

    sent_today = {
        int(r["patient_id"])
        for r in db.execute("SELECT patient_id FROM birthday_log WHERE sent_on=? AND channel='whatsapp'", (today,)).fetchall()
    }

    todays_birthdays = []
    for r in bday_rows:
        msg = (birthday_template or "").replace("{nome}", r["name"]).replace("{clinica}", clinica)
        phone = "".join(ch for ch in (r["phone"] or "") if ch.isdigit())
        if phone and not phone.startswith("55"):
            phone = "55" + phone
        wa_link = f"https://wa.me/{phone}?text={quote(msg)}" if phone else ""
        todays_birthdays.append({
            "id": int(r["id"]),
            "name": r["name"],
            "phone": r["phone"] or "",
            "birth_date": r["birth_date"] or "",
            "message": msg,
            "wa_link": wa_link,
            "sent": int(r["id"]) in sent_today,
        })

    return render_template("dashboard.html", stats=stats, todays_birthdays=todays_birthdays)