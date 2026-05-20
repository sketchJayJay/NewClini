# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any
from urllib.parse import quote

import requests
from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for, jsonify

from .auth import login_required
from .db import get_db
from .utils import parse_brl_to_cents, cents_to_brl, today_yyyy_mm_dd, validate_cpf_cnpj


bp = Blueprint("boletos", __name__)


def _asaas_base_url() -> str:
    env = (current_app.config.get("ASAAS_ENV") or "sandbox").strip().lower()
    # produção: https://api.asaas.com/v3 | sandbox: https://api-sandbox.asaas.com/v3
    return "https://api.asaas.com/v3" if env == "production" else "https://api-sandbox.asaas.com/v3"


def _asaas_headers() -> dict[str, str]:
    key = (current_app.config.get("ASAAS_API_KEY") or "").strip()
    return {
        "access_token": key,
        "Content-Type": "application/json",
        "User-Agent": "NewClinicaV2/2.2",
    }


def _digits(s: str | None) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())


def _row_get(row, key: str, default: Any = "") -> Any:
    """Compatível com sqlite3.Row e dict."""
    try:
        if row is None:
            return default
        if isinstance(row, dict):
            return row.get(key, default)
        # sqlite3.Row
        return row[key] if key in row.keys() else default
    except Exception:
        return default


def _asaas_request(method: str, path: str, *, params: dict[str, Any] | None = None, json_body: dict[str, Any] | None = None) -> dict[str, Any]:
    key = (current_app.config.get("ASAAS_API_KEY") or "").strip()
    if not key:
        raise RuntimeError("ASAAS_API_KEY não configurada")
    url = _asaas_base_url().rstrip("/") + "/" + path.lstrip("/")
    r = requests.request(method.upper(), url, headers=_asaas_headers(), params=params, json=json_body, timeout=25)
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text}
    if r.status_code >= 400:
        # mensagem amigável
        msg = data.get("errors") or data.get("error") or data
        raise RuntimeError(f"Asaas {r.status_code}: {msg}")
    return data


def _ensure_asaas_customer(db, patient_row) -> str:
    """Cria (se necessário) e retorna o customer_id no Asaas."""
    if _row_get(patient_row, "asaas_customer_id"):
        return str(_row_get(patient_row, "asaas_customer_id"))

    cpf = _digits(_row_get(patient_row, "cpf"))
    if not cpf:
        raise RuntimeError("CPF do paciente é obrigatório para emitir boleto (cadastre no paciente).")
    if not validate_cpf_cnpj(cpf):
        raise RuntimeError("CPF/CNPJ do paciente é inválido. Confira os dígitos.")

    payload: dict[str, Any] = {
        "name": _row_get(patient_row, "name"),
        "cpfCnpj": cpf,
    }
    phone = _digits(_row_get(patient_row, "phone"))
    if phone:
        # asaas normalmente espera DDD+numero (sem +). Se não tiver 55, colocamos.
        if not phone.startswith("55") and len(phone) <= 11:
            phone = "55" + phone
        payload["mobilePhone"] = phone

    customer = _asaas_request("POST", "/customers", json_body=payload)
    customer_id = str(customer.get("id") or "")
    if not customer_id:
        raise RuntimeError("Asaas não retornou o ID do cliente.")

    db.execute("UPDATE patients SET asaas_customer_id=? WHERE id=?", (customer_id, int(_row_get(patient_row, "id"))))
    return customer_id


def _get_or_create_category_id(db, name: str = "Procedimentos") -> int | None:
    if not name:
        return None
    try:
        db.execute("INSERT OR IGNORE INTO categories(name, kind, active) VALUES(?, 'income', 1)", (name,))
        row = db.execute("SELECT id FROM categories WHERE name=? LIMIT 1", (name,)).fetchone()
        return int(row["id"]) if row else None
    except Exception:
        return None


def _provider_default_repasse(db, provider_id: int | None) -> int:
    if not provider_id:
        return 0
    r = db.execute("SELECT default_repasse_percent FROM providers WHERE id=?", (provider_id,)).fetchone()
    try:
        return max(0, min(100, int(r["default_repasse_percent"] or 0))) if r else 0
    except Exception:
        return 0


@bp.post("/patients/<int:pid>/boletos/create")
@login_required
def create_boleto(pid: int):
    db = get_db()
    patient = db.execute("SELECT * FROM patients WHERE id=?", (pid,)).fetchone()
    if not patient:
        flash("Paciente não encontrado.", "danger")
        return redirect(url_for("patients.list_patients"))

    due_date = (request.form.get("due_date") or "").strip() or today_yyyy_mm_dd()
    description = (request.form.get("description") or "Boleto").strip()[:500]
    amount_cents = parse_brl_to_cents(request.form.get("amount") or "0")
    provider_id = request.form.get("provider_id", "").strip()
    category_id = request.form.get("category_id", "").strip()

    prid = int(provider_id) if provider_id.isdigit() else None
    cid = int(category_id) if category_id.isdigit() else None
    if cid is None:
        cid = _get_or_create_category_id(db, "Procedimentos")

    if amount_cents <= 0:
        flash("Valor inválido.", "danger")
        return redirect(url_for("patients.view_patient", pid=pid, tab="boletos"))

    try:
        # garante customer no Asaas
        customer_id = _ensure_asaas_customer(db, patient)

        # cria lançamento pendente no financeiro (só vira "dim dim" quando estiver PAGO)
        repasse_percent = _provider_default_repasse(db, prid)
        # para pendente: usamos date=due_date para ordenar bem no financeiro
        db.execute(
            "INSERT INTO transactions(kind,status,date,due_date,amount_cents,payment_method,description,patient_id,category_id,provider_id,repasse_percent) "
            "VALUES('income','pending',?,?,?,?,?,?,?,?,?)",
            (due_date, due_date, amount_cents, "boleto", f"Boleto • {description}", pid, cid, prid, repasse_percent),
        )
        tx_id = int(db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"])

        # cria cobrança no Asaas
        value = float((Decimal(amount_cents) / Decimal(100)).quantize(Decimal("0.01")))
        payment = _asaas_request(
            "POST",
            "/payments",
            json_body={
                "customer": customer_id,
                "billingType": "BOLETO",
                "value": value,
                "dueDate": due_date,
                "description": description,
                "externalReference": f"tx:{tx_id}",
            },
        )
        pay_id = str(payment.get("id") or "")
        bank_slip_url = payment.get("bankSlipUrl") or ""
        invoice_url = payment.get("invoiceUrl") or ""

        identification_field = ""
        if pay_id:
            try:
                ident = _asaas_request("GET", f"/payments/{pay_id}/identificationField")
                identification_field = (ident.get("identificationField") or ident.get("value") or "")
            except Exception:
                identification_field = ""

        db.execute(
            "INSERT INTO boletos(patient_id,provider_id,category_id,finance_tx_id,asaas_customer_id,asaas_payment_id,status,value_cents,due_date,description,bank_slip_url,invoice_url,identification_field) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                pid,
                prid,
                cid,
                tx_id,
                customer_id,
                pay_id,
                "pending",
                amount_cents,
                due_date,
                description,
                bank_slip_url,
                invoice_url,
                identification_field,
            ),
        )
        db.commit()

        flash("Boleto emitido ✅", "success")
    except Exception as e:
        try:
            db.rollback()
        except Exception:
            pass
        flash(f"Não foi possível emitir o boleto: {e}", "danger")

    return redirect(url_for("patients.view_patient", pid=pid, tab="boletos"))


@bp.post("/patients/<int:pid>/boletos/<int:bid>/sandbox_confirm")
@login_required
def sandbox_confirm(pid: int, bid: int):
    """Apenas para SANDBOX: confirma o pagamento para testes."""
    env = (current_app.config.get("ASAAS_ENV") or "sandbox").strip().lower()
    if env == "production":
        flash("Esse botão é só para sandbox.", "warning")
        return redirect(url_for("patients.view_patient", pid=pid, tab="boletos"))

    db = get_db()
    b = db.execute("SELECT * FROM boletos WHERE id=? AND patient_id=?", (bid, pid)).fetchone()
    if not b or not b["asaas_payment_id"]:
        flash("Boleto não encontrado.", "danger")
        return redirect(url_for("patients.view_patient", pid=pid, tab="boletos"))
    try:
        _asaas_request("POST", f"/sandbox/payment/{b['asaas_payment_id']}/confirm")
        flash("Pagamento confirmado no sandbox ✅ (aguarde o webhook)", "success")
    except Exception as e:
        flash(f"Falha ao confirmar no sandbox: {e}", "danger")
    return redirect(url_for("patients.view_patient", pid=pid, tab="boletos"))


@bp.post("/webhooks/asaas")
def asaas_webhook():
    """Recebe eventos do Asaas e atualiza o boleto + financeiro automaticamente."""
    token_cfg = (current_app.config.get("ASAAS_WEBHOOK_TOKEN") or "").strip()
    if token_cfg:
        token_hdr = (request.headers.get("asaas-access-token") or "").strip()
        if token_hdr != token_cfg:
            return jsonify({"ok": False, "error": "invalid token"}), 401

    body = request.get_json(silent=True) or {}
    event_id = str(body.get("id") or "")
    event = str(body.get("event") or "")
    payment = body.get("payment") or {}
    pay_id = str(payment.get("id") or "")

    db = get_db()

    # dedupe de eventos
    if event_id:
        try:
            db.execute(
                "INSERT INTO asaas_webhook_events(id, event, payment_id) VALUES(?,?,?)",
                (event_id, event, pay_id),
            )
            db.commit()
        except Exception:
            # já processado
            return jsonify({"received": True, "dedup": True})

    # atualiza boleto
    if not pay_id:
        return jsonify({"received": True})

    boleto = db.execute("SELECT * FROM boletos WHERE asaas_payment_id=? LIMIT 1", (pay_id,)).fetchone()
    if not boleto:
        return jsonify({"received": True, "unknown_payment": True})

    new_status = None
    if event in ("PAYMENT_CONFIRMED", "PAYMENT_RECEIVED"):
        new_status = "paid"
    elif event in ("PAYMENT_OVERDUE",):
        new_status = "overdue"
    elif event in ("PAYMENT_DELETED", "PAYMENT_BANK_SLIP_CANCELLED"):
        new_status = "cancelled"

    # tenta pegar data de pagamento
    paid_date = None
    for k in ("paymentDate", "confirmedDate", "clientPaymentDate"):
        v = payment.get(k)
        if isinstance(v, str) and len(v) >= 10:
            paid_date = v[:10]
            break
    if not paid_date:
        paid_date = today_yyyy_mm_dd()

    bank_slip_url = payment.get("bankSlipUrl") or boleto["bank_slip_url"]
    invoice_url = payment.get("invoiceUrl") or boleto["invoice_url"]

    if new_status:
        db.execute(
            "UPDATE boletos SET status=?, bank_slip_url=?, invoice_url=?, updated_at=datetime('now') WHERE id=?",
            (new_status, bank_slip_url, invoice_url, int(boleto["id"])),
        )

    # Se pagou, dá baixa automática no financeiro
    if new_status == "paid" and boleto["finance_tx_id"]:
        try:
            db.execute(
                "UPDATE transactions SET status='paid', date=?, due_date=NULL, payment_method='boleto' WHERE id=?",
                (paid_date, int(boleto["finance_tx_id"])),
            )
        except Exception:
            pass

    db.commit()
    return jsonify({"received": True})