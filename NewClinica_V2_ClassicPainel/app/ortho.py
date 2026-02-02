# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, timedelta, date
from flask import Blueprint, render_template, request, redirect, url_for, flash

from .auth import login_required
from .db import get_db, get_open_cash_session_id
from .utils import parse_brl_to_cents, cents_to_brl, today_yyyy_mm_dd

bp = Blueprint("ortho", __name__, url_prefix="/ortho")

# Usa as mesmas chaves do Financeiro
PAYMENT_METHODS = [
    ("cash", "Dinheiro"),
    ("pix", "Pix"),
    ("card_credit", "Cartão crédito"),
    ("card_debit", "Cartão débito"),
    ("transfer", "Transferência"),
    ("other", "Outro"),
]

def _safe_int(v: str | None) -> int | None:
    if v is None:
        return None
    s = str(v).strip()
    if not s or not s.isdigit():
        return None
    return int(s)

def _to_sql_datetime(d: str | None, t: str | None) -> str | None:
    """Recebe data YYYY-MM-DD e hora HH:MM e retorna YYYY-MM-DD HH:MM:SS."""
    if not d:
        return None
    d = str(d).strip()
    if not d:
        return None
    t = (t or "").strip() or "09:00"
    # valida
    try:
        datetime.strptime(d, "%Y-%m-%d")
    except Exception:
        return None
    try:
        datetime.strptime(t, "%H:%M")
    except Exception:
        t = "09:00"
    return f"{d} {t}:00"

def _get_or_create_category_id(db, name: str = "Ortodontia") -> int | None:
    """Garante categoria de entrada para lançamentos de ortodontia."""
    if not name:
        return None
    try:
        db.execute("INSERT OR IGNORE INTO categories(name, kind, active) VALUES(?, 'income', 1)", (name,))
        db.commit()
        row = db.execute("SELECT id FROM categories WHERE name=? LIMIT 1", (name,)).fetchone()
        return int(row["id"]) if row else None
    except Exception:
        return None

def _create_finance_tx(
    db,
    *,
    patient_id: int,
    provider_id: int | None,
    amount_cents: int,
    maintenance_done: str,
    status: str,            # paid|pending
    date_eff: str,          # YYYY-MM-DD
    due_date: str | None,   # YYYY-MM-DD
    payment_method: str,
) -> int | None:
    if amount_cents <= 0:
        return None

    if status not in ("paid", "pending"):
        status = "pending"
    pm_allowed = {"cash", "pix", "card_credit", "card_debit", "transfer", "other", "card"}
    if payment_method not in pm_allowed:
        payment_method = "pix"

    # Categoria e repasse
    category_id = _get_or_create_category_id(db, "Ortodontia")
    repasse_percent = 0
    if provider_id:
        pr = db.execute("SELECT default_repasse_percent FROM providers WHERE id=? LIMIT 1", (provider_id,)).fetchone()
        if pr:
            try:
                repasse_percent = int(pr["default_repasse_percent"] or 0)
            except Exception:
                repasse_percent = 0

    desc = "Ortodontia • Manutenção"
    md = (maintenance_done or "").strip()
    if md:
        # limita para não virar um textão no financeiro
        short = (md[:80] + "…") if len(md) > 80 else md
        desc = f"Ortodontia • {short}"

    cash_session_id = None
    open_cash_id = get_open_cash_session_id()
    if status == "paid" and payment_method == "cash" and open_cash_id:
        cash_session_id = open_cash_id

    db.execute(
        "INSERT INTO transactions(kind,status,date,due_date,amount_cents,payment_method,description,patient_id,category_id,provider_id,repasse_percent,cash_session_id) "
        "VALUES('income',?,?,?,?,?,?,?,?,?,?,?)",
        (status, date_eff, due_date, amount_cents, payment_method, desc, patient_id, category_id, provider_id, repasse_percent, cash_session_id),
    )
    tx_id = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    return int(tx_id) if tx_id is not None else None


def _create_next_appointment(db, *, patient_id: int, provider_id: int | None, next_date: str | None, next_time: str | None, note: str | None) -> int | None:
    start_at = _to_sql_datetime(next_date, next_time)
    if not start_at:
        return None
    try:
        start_dt = datetime.fromisoformat(start_at.replace(" ", "T"))
        end_dt = start_dt + timedelta(minutes=30)
        end_at = end_dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        end_at = None

    title = "Manutenção ortodôntica"
    db.execute(
        "INSERT INTO appointments(patient_id, provider_id, title, start_at, end_at, note) VALUES(?,?,?,?,?,?)",
        (patient_id, provider_id, title, start_at, end_at, (note or "").strip() or None),
    )
    appt_id = db.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    return int(appt_id) if appt_id is not None else None


@bp.get("/")
@login_required
def list_ortho():
    db = get_db()
    q = (request.args.get("q") or "").strip()
    patient_id = (request.args.get("patient_id") or "").strip()
    pay_status = (request.args.get("status") or "").strip()  # paid|pending|''

    where = []
    params = []
    if q:
        where.append("(p.name LIKE ? OR p.cpf LIKE ? OR o.maintenance_done LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
    if patient_id.isdigit():
        where.append("o.patient_id=?")
        params.append(int(patient_id))
    if pay_status in ("paid", "pending"):
        where.append("o.payment_status=?")
        params.append(pay_status)

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    rows = db.execute(
        f"""
        SELECT o.*,
               p.name AS patient_name, p.cpf AS patient_cpf,
               pr.name AS provider_name
          FROM ortho_maintenances o
          JOIN patients p ON p.id=o.patient_id
          LEFT JOIN providers pr ON pr.id=o.provider_id
          {where_sql}
         ORDER BY o.maintenance_date DESC, o.id DESC
         LIMIT 400
        """,
        tuple(params),
    ).fetchall()

    patients = db.execute("SELECT id, name, cpf FROM patients ORDER BY name ASC").fetchall()

    return render_template(
        "ortho_list.html",
        rows=rows,
        patients=patients,
        cents_to_brl=cents_to_brl,
        filters=dict(q=q, patient_id=patient_id, status=pay_status),
    )


@bp.route("/new", methods=["GET", "POST"])
@login_required
def new_ortho():
    db = get_db()
    patients = db.execute("SELECT id, name, cpf FROM patients ORDER BY name ASC").fetchall()
    providers = db.execute("SELECT id, name FROM providers WHERE active=1 ORDER BY name ASC").fetchall()
    patient_prefill = request.args.get("patient_id", "").strip()

    if request.method == "POST":
        patient_id = _safe_int(request.form.get("patient_id"))
        provider_id = _safe_int(request.form.get("provider_id"))
        maintenance_date = (request.form.get("maintenance_date") or today_yyyy_mm_dd()).strip() or today_yyyy_mm_dd()
        maintenance_done = (request.form.get("maintenance_done") or "").strip()

        amount_cents = parse_brl_to_cents(request.form.get("amount") or "0")
        payment_status = (request.form.get("payment_status") or "pending").strip()
        payment_method = (request.form.get("payment_method") or "pix").strip()
        due_date = (request.form.get("due_date") or "").strip() or None
        paid_at = (request.form.get("paid_at") or "").strip() or None

        next_date = (request.form.get("next_date") or "").strip() or None
        next_time = (request.form.get("next_time") or "").strip() or None
        next_note = (request.form.get("next_note") or "").strip() or None
        create_in_agenda = (request.form.get("create_in_agenda") or "").strip() == "1"

        if not patient_id:
            flash("Selecione o paciente.", "danger")
            return render_template("ortho_form.html", item=None, patients=patients, providers=providers, pm=PAYMENT_METHODS, patient_prefill=patient_prefill, cents_to_brl=cents_to_brl)

        if payment_status not in ("paid", "pending"):
            payment_status = "pending"

        # Datas padrão
        if payment_status == "paid":
            if not paid_at:
                paid_at = maintenance_date
            date_eff = paid_at
            due_date = None
        else:
            # pendente: usa vencimento como data efetiva (melhor pra ordenar)
            if not due_date:
                due_date = maintenance_date
            date_eff = due_date

        tx_id = None
        try:
            # cria transação (se tiver valor)
            tx_id = _create_finance_tx(
                db,
                patient_id=patient_id,
                provider_id=provider_id,
                amount_cents=amount_cents,
                maintenance_done=maintenance_done,
                status=payment_status,
                date_eff=date_eff,
                due_date=due_date if payment_status == "pending" else None,
                payment_method=payment_method,
            )

            appt_id = None
            if create_in_agenda and next_date:
                appt_id = _create_next_appointment(
                    db,
                    patient_id=patient_id,
                    provider_id=provider_id,
                    next_date=next_date,
                    next_time=next_time,
                    note=next_note or "Retorno ortodôntico",
                )

            db.execute("UPDATE patients SET is_ortho=1 WHERE id=?", (patient_id,))

            db.execute(
                """
                INSERT INTO ortho_maintenances(
                    patient_id, provider_id,
                    maintenance_date, maintenance_done,
                    amount_cents, payment_status, payment_method, due_date, paid_at,
                    next_date, next_time, next_note,
                    finance_tx_id, appointment_id
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    patient_id, provider_id,
                    maintenance_date, maintenance_done,
                    amount_cents, payment_status, payment_method, due_date, paid_at,
                    next_date, next_time, next_note,
                    tx_id, appt_id
                ),
            )
            db.commit()
            flash("Manutenção ortodôntica salva ✅", "success")
            return redirect(url_for("ortho.list_ortho", patient_id=patient_id))
        except Exception as e:
            db.rollback()
            flash(f"Erro ao salvar: {e}", "danger")

    return render_template(
        "ortho_form.html",
        item=None,
        patients=patients,
        providers=providers,
        pm=PAYMENT_METHODS,
        patient_prefill=patient_prefill,
        cents_to_brl=cents_to_brl,
    )


@bp.route("/<int:oid>/edit", methods=["GET", "POST"])
@login_required
def edit_ortho(oid: int):
    db = get_db()
    item = db.execute(
        "SELECT o.*, p.name AS patient_name, p.cpf AS patient_cpf FROM ortho_maintenances o JOIN patients p ON p.id=o.patient_id WHERE o.id=?",
        (oid,),
    ).fetchone()
    if not item:
        flash("Registro não encontrado.", "danger")
        return redirect(url_for("ortho.list_ortho"))

    patients = db.execute("SELECT id, name, cpf FROM patients ORDER BY name ASC").fetchall()
    providers = db.execute("SELECT id, name FROM providers WHERE active=1 ORDER BY name ASC").fetchall()

    if request.method == "POST":
        provider_id = _safe_int(request.form.get("provider_id"))
        maintenance_date = (request.form.get("maintenance_date") or today_yyyy_mm_dd()).strip() or today_yyyy_mm_dd()
        maintenance_done = (request.form.get("maintenance_done") or "").strip()
        amount_cents = parse_brl_to_cents(request.form.get("amount") or "0")

        payment_status = (request.form.get("payment_status") or "pending").strip()
        payment_method = (request.form.get("payment_method") or "pix").strip()
        due_date = (request.form.get("due_date") or "").strip() or None
        paid_at = (request.form.get("paid_at") or "").strip() or None

        next_date = (request.form.get("next_date") or "").strip() or None
        next_time = (request.form.get("next_time") or "").strip() or None
        next_note = (request.form.get("next_note") or "").strip() or None

        if payment_status not in ("paid", "pending"):
            payment_status = "pending"

        # sincroniza com financeiro (se tiver tx)
        tx_id = item["finance_tx_id"]
        if payment_status == "paid":
            if not paid_at:
                paid_at = maintenance_date
            date_eff = paid_at
            due_date_for_tx = None
        else:
            if not due_date:
                due_date = maintenance_date
            date_eff = due_date
            due_date_for_tx = due_date

        try:
            # se tem tx, atualiza; senão, cria quando houver valor
            if tx_id:
                cash_session_id = None
                open_cash_id = get_open_cash_session_id()
                if payment_status == "paid" and payment_method == "cash" and open_cash_id:
                    cash_session_id = open_cash_id

                db.execute(
                    "UPDATE transactions SET status=?, date=?, due_date=?, amount_cents=?, payment_method=?, provider_id=?, cash_session_id=? WHERE id=?",
                    (payment_status, date_eff, due_date_for_tx, amount_cents, payment_method, provider_id, cash_session_id, tx_id),
                )
            else:
                tx_id = _create_finance_tx(
                    db,
                    patient_id=int(item["patient_id"]),
                    provider_id=provider_id,
                    amount_cents=amount_cents,
                    maintenance_done=maintenance_done,
                    status=payment_status,
                    date_eff=date_eff,
                    due_date=due_date_for_tx,
                    payment_method=payment_method,
                )

            db.execute(
                """
                UPDATE ortho_maintenances
                   SET provider_id=?,
                       maintenance_date=?,
                       maintenance_done=?,
                       amount_cents=?,
                       payment_status=?,
                       payment_method=?,
                       due_date=?,
                       paid_at=?,
                       next_date=?,
                       next_time=?,
                       next_note=?,
                       finance_tx_id=?,
                       updated_at=datetime('now')
                 WHERE id=?
                """,
                (
                    provider_id,
                    maintenance_date,
                    maintenance_done,
                    amount_cents,
                    payment_status,
                    payment_method,
                    due_date,
                    paid_at,
                    next_date,
                    next_time,
                    next_note,
                    tx_id,
                    oid,
                ),
            )
            db.commit()
            flash("Atualizado ✅", "success")
            return redirect(url_for("ortho.list_ortho", patient_id=item["patient_id"]))
        except Exception as e:
            db.rollback()
            flash(f"Erro ao atualizar: {e}", "danger")

    return render_template("ortho_form.html", item=item, patients=patients, providers=providers, pm=PAYMENT_METHODS, patient_prefill=str(item["patient_id"]), cents_to_brl=cents_to_brl)


@bp.post("/<int:oid>/confirm_payment")
@login_required
def confirm_payment(oid: int):
    """Confirma pagamento de um registro pendente: muda status e joga/atualiza no Financeiro."""
    db = get_db()
    item = db.execute("SELECT * FROM ortho_maintenances WHERE id=?", (oid,)).fetchone()
    if not item:
        flash("Registro não encontrado.", "danger")
        return redirect(url_for("ortho.list_ortho"))

    payment_method = (request.form.get("payment_method") or "pix").strip()
    paid_at = (request.form.get("paid_at") or today_yyyy_mm_dd()).strip() or today_yyyy_mm_dd()

    tx_id = item["finance_tx_id"]
    try:
        if tx_id:
            cash_session_id = None
            open_cash_id = get_open_cash_session_id()
            if payment_method == "cash" and open_cash_id:
                cash_session_id = open_cash_id

            db.execute(
                "UPDATE transactions SET status='paid', date=?, due_date=NULL, payment_method=?, cash_session_id=? WHERE id=?",
                (paid_at, payment_method, cash_session_id, tx_id),
            )
        else:
            tx_id = _create_finance_tx(
                db,
                patient_id=int(item["patient_id"]),
                provider_id=item["provider_id"],
                amount_cents=int(item["amount_cents"] or 0),
                maintenance_done=item["maintenance_done"] or "",
                status="paid",
                date_eff=paid_at,
                due_date=None,
                payment_method=payment_method,
            )

        db.execute(
            "UPDATE ortho_maintenances SET payment_status='paid', paid_at=?, payment_method=?, finance_tx_id=?, updated_at=datetime('now') WHERE id=?",
            (paid_at, payment_method, tx_id, oid),
        )
        db.commit()
        flash("Pagamento confirmado e atualizado no Financeiro ✅", "success")
    except Exception as e:
        db.rollback()
        flash(f"Erro ao confirmar pagamento: {e}", "danger")

    return redirect(url_for("ortho.list_ortho", patient_id=item["patient_id"]))
