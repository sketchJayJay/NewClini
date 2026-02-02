# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import date
from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
from .auth import login_required
from .db import get_db, get_open_cash_session_id
from .utils import parse_brl_to_cents, cents_to_brl, today_yyyy_mm_dd

bp = Blueprint("finance", __name__, url_prefix="/finance")

PAYMENT_METHODS = [
    ("cash", "Dinheiro"),
    ("pix", "Pix"),
    # Cartão separado para melhorar relatórios
    ("card_credit", "Cartão crédito"),
    ("card_debit", "Cartão débito"),
    # legado (versões antigas gravavam apenas 'card')
    ("card", "Cartão"),
    ("transfer", "Transferência"),
    ("other", "Outro"),
]


def finance_required(view):
    """Proteção extra do módulo Financeiro por senha (além do login)."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("finance_unlocked"):
            nxt = request.full_path if request.query_string else request.path
            return redirect(url_for("finance.unlock", next=nxt))
        return view(*args, **kwargs)

    return wrapped


@bp.route("/unlock", methods=["GET", "POST"])
@login_required
def unlock():
    """Tela de desbloqueio do Financeiro."""
    next_url = request.args.get("next") or request.form.get("next") or url_for("finance.transactions")
    if request.method == "POST":
        senha = request.form.get("password", "")
        expected = current_app.config.get("FINANCE_PASSWORD", "sorrisonew")
        if senha == expected:
            session["finance_unlocked"] = True
            flash("Financeiro desbloqueado ✅", "success")
            return redirect(next_url)
        flash("Senha do financeiro incorreta.", "danger")
    return render_template("finance_unlock.html", next=next_url)


@bp.route("/lock")
@login_required
def lock():
    session.pop("finance_unlocked", None)
    flash("Financeiro bloqueado 🔒", "info")
    return redirect(url_for("dashboard.index"))

@bp.route("/transactions")
@login_required
@finance_required
def transactions():
    db = get_db()
    kind = request.args.get("kind", "").strip()  # income|expense|'' (all)
    status = request.args.get("status", "").strip()  # paid|pending|''
    payment_method = request.args.get("payment_method", "").strip()
    q = request.args.get("q", "").strip()
    date_from = request.args.get("from", "").strip()
    date_to = request.args.get("to", "").strip()
    patient_id = request.args.get("patient_id", "").strip()
    category_id = request.args.get("category_id", "").strip()

    where = []
    params = []
    if kind in ("income", "expense"):
        where.append("t.kind=?")
        params.append(kind)
    if status in ("paid", "pending"):
        where.append("t.status=?")
        params.append(status)

    # filtro por forma de pagamento
    pm_allowed = {"cash", "pix", "card_credit", "card_debit", "transfer", "other", "card"}
    if payment_method in pm_allowed:
        # legado: "card" antigo entra junto do crédito
        if payment_method == "card_credit":
            where.append("(t.payment_method=? OR t.payment_method='card')")
            params.append("card_credit")
        else:
            where.append("t.payment_method=?")
            params.append(payment_method)

    if q:
        where.append("(t.description LIKE ? OR p.name LIKE ? OR p.cpf LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
    if date_from:
        where.append("t.date>=?")
        params.append(date_from)
    if date_to:
        where.append("t.date<=?")
        params.append(date_to)
    if patient_id.isdigit():
        where.append("t.patient_id=?")
        params.append(int(patient_id))
    if category_id.isdigit():
        where.append("t.category_id=?")
        params.append(int(category_id))

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    rows = db.execute(
        "SELECT t.*, p.name AS patient_name, p.cpf AS patient_cpf, c.name AS category_name, pr.name AS provider_name "
        "FROM transactions t "
        "LEFT JOIN patients p ON p.id=t.patient_id "
        "LEFT JOIN categories c ON c.id=t.category_id "
        "LEFT JOIN providers pr ON pr.id=t.provider_id "
        f"{where_sql} "
        "ORDER BY t.date DESC, t.id DESC LIMIT 300",
        tuple(params),
    ).fetchall()

    # totals
    total_income = 0
    total_expense = 0
    total_pending = 0

    # breakdown das ENTRADAS por método de pagamento
    income_by_pm_cents = {
        "cash": 0,
        "pix": 0,
        "card_credit": 0,
        "card_debit": 0,
        "transfer": 0,
        "other": 0,
    }
    for r in rows:
        if r["kind"] == "income":
            total_income += int(r["amount_cents"])

            pm = (r["payment_method"] or "other").strip()
            # legado: versões antigas salvavam só "card"
            if pm == "card":
                pm = "card_credit"
            if pm not in income_by_pm_cents:
                pm = "other"
            income_by_pm_cents[pm] += int(r["amount_cents"])
        else:
            total_expense += int(r["amount_cents"])
        if r["status"] == "pending":
            total_pending += int(r["amount_cents"])

    patients = db.execute("SELECT id, name, cpf FROM patients ORDER BY name ASC").fetchall()
    categories = db.execute("SELECT id, name FROM categories WHERE active=1 ORDER BY name ASC").fetchall()

    pm_labels = {k: v for k, v in PAYMENT_METHODS}

    income_by_pm = {
        "cash": cents_to_brl(income_by_pm_cents["cash"]),
        "pix": cents_to_brl(income_by_pm_cents["pix"]),
        "card_credit": cents_to_brl(income_by_pm_cents["card_credit"]),
        "card_debit": cents_to_brl(income_by_pm_cents["card_debit"]),
        "transfer": cents_to_brl(income_by_pm_cents["transfer"]),
        "other": cents_to_brl(income_by_pm_cents["other"]),
    }

    return render_template(
        "transactions_list.html",
        rows=rows,
        cents_to_brl=cents_to_brl,
        pm_labels=pm_labels,
        filters=dict(kind=kind, status=status, payment_method=payment_method, q=q, date_from=date_from, date_to=date_to, patient_id=patient_id, category_id=category_id),
        totals=dict(income=cents_to_brl(total_income), expense=cents_to_brl(total_expense), pending=cents_to_brl(total_pending)),
        income_by_pm=income_by_pm,
        patients=patients,
        categories=categories,
        pm=PAYMENT_METHODS,
    )

@bp.route("/transactions/new", methods=["GET", "POST"])
@login_required
@finance_required
def transaction_new():
    db = get_db()
    patients = db.execute("SELECT id, name, cpf FROM patients ORDER BY name ASC").fetchall()
    categories = db.execute("SELECT id, name, kind FROM categories WHERE active=1 ORDER BY name ASC").fetchall()
    providers = db.execute("SELECT id, name, default_repasse_percent FROM providers WHERE active=1 ORDER BY name ASC").fetchall()

    if request.method == "POST":
        kind = request.form.get("kind", "income")
        status = request.form.get("status", "paid")
        date_eff = request.form.get("date", today_yyyy_mm_dd())
        due_date = request.form.get("due_date", "").strip() or None
        amount = parse_brl_to_cents(request.form.get("amount", "0"))
        payment_method = request.form.get("payment_method", "pix")
        description = request.form.get("description", "").strip()
        patient_id = request.form.get("patient_id", "").strip()
        category_id = request.form.get("category_id", "").strip()
        provider_id = request.form.get("provider_id", "").strip()
        repasse_percent = request.form.get("repasse_percent", "").strip()

        if kind not in ("income", "expense"):
            kind = "income"
        if status not in ("paid", "pending"):
            status = "paid"
        if payment_method not in {k for k,_ in PAYMENT_METHODS}:
            payment_method = "other"

        pid = int(patient_id) if patient_id.isdigit() else None
        cid = int(category_id) if category_id.isdigit() else None
        prid = int(provider_id) if provider_id.isdigit() else None

        if repasse_percent == "":
            # puxa default do provider
            if prid is not None:
                r = db.execute("SELECT default_repasse_percent FROM providers WHERE id=?", (prid,)).fetchone()
                repasse_percent = str(int(r["default_repasse_percent"] or 0))
            else:
                repasse_percent = "0"

        try:
            repasse_percent_int = max(0, min(100, int(repasse_percent)))
        except Exception:
            repasse_percent_int = 0

        if amount == 0:
            flash("Valor não pode ser zero.", "danger")
            return render_template("transaction_form.html", tx=None, patients=patients, categories=categories, providers=providers, pm=PAYMENT_METHODS)

        cash_session_id = None
        open_cash_id = get_open_cash_session_id()
        if status == "paid" and payment_method == "cash" and open_cash_id:
            cash_session_id = open_cash_id

        db.execute(
            "INSERT INTO transactions(kind,status,date,due_date,amount_cents,payment_method,description,patient_id,category_id,provider_id,repasse_percent,cash_session_id) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (kind, status, date_eff, due_date, amount, payment_method, description, pid, cid, prid, repasse_percent_int, cash_session_id),
        )
        db.commit()
        flash("Lançamento salvo ✅", "success")
        return redirect(url_for("finance.transactions"))

    tx_prefill = {
        "kind": request.args.get("kind", "income"),
        "status": "paid",
        "date": today_yyyy_mm_dd(),
        "payment_method": "pix",
    }
    return render_template("transaction_form.html", tx=tx_prefill, patients=patients, categories=categories, providers=providers, pm=PAYMENT_METHODS)

@bp.route("/transactions/<int:tid>/edit", methods=["GET", "POST"])
@login_required
@finance_required
def transaction_edit(tid: int):
    db = get_db()
    tx = db.execute("SELECT * FROM transactions WHERE id=?", (tid,)).fetchone()
    if not tx:
        flash("Lançamento não encontrado.", "danger")
        return redirect(url_for("finance.transactions"))

    patients = db.execute("SELECT id, name, cpf FROM patients ORDER BY name ASC").fetchall()
    categories = db.execute("SELECT id, name, kind FROM categories WHERE active=1 ORDER BY name ASC").fetchall()
    providers = db.execute("SELECT id, name, default_repasse_percent FROM providers WHERE active=1 ORDER BY name ASC").fetchall()

    if request.method == "POST":
        kind = request.form.get("kind", tx["kind"])
        status = request.form.get("status", tx["status"])
        date_eff = request.form.get("date", tx["date"])
        due_date = request.form.get("due_date", "").strip() or None
        amount = parse_brl_to_cents(request.form.get("amount", "0"))
        payment_method = request.form.get("payment_method", tx["payment_method"])
        description = request.form.get("description", "").strip()
        patient_id = request.form.get("patient_id", "").strip()
        category_id = request.form.get("category_id", "").strip()
        provider_id = request.form.get("provider_id", "").strip()
        repasse_percent = request.form.get("repasse_percent", "").strip()

        pid = int(patient_id) if patient_id.isdigit() else None
        cid = int(category_id) if category_id.isdigit() else None
        prid = int(provider_id) if provider_id.isdigit() else None
        try:
            repasse_percent_int = max(0, min(100, int(repasse_percent or 0)))
        except Exception:
            repasse_percent_int = 0

        cash_session_id = tx["cash_session_id"]
        open_cash_id = get_open_cash_session_id()
        if status == "paid" and payment_method == "cash" and open_cash_id:
            cash_session_id = open_cash_id
        if payment_method != "cash":
            cash_session_id = None

        db.execute(
            "UPDATE transactions SET kind=?, status=?, date=?, due_date=?, amount_cents=?, payment_method=?, description=?, patient_id=?, category_id=?, provider_id=?, repasse_percent=?, cash_session_id=? WHERE id=?",
            (kind, status, date_eff, due_date, amount, payment_method, description, pid, cid, prid, repasse_percent_int, cash_session_id, tid),
        )
        db.commit()
        flash("Lançamento atualizado ✅", "success")
        return redirect(url_for("finance.transactions"))
    tx_dict = dict(tx)
    tx_dict["amount_brl"] = cents_to_brl(int(tx["amount_cents"]))
    return render_template("transaction_form.html", tx=tx_dict, patients=patients, categories=categories, providers=providers, pm=PAYMENT_METHODS)

@bp.route("/transactions/<int:tid>/delete", methods=["POST"])
@login_required
@finance_required
def transaction_delete(tid: int):
    db = get_db()
    db.execute("DELETE FROM transactions WHERE id=?", (tid,))
    db.commit()
    flash("Lançamento removido.", "info")
    return redirect(url_for("finance.transactions"))

@bp.route("/transactions/<int:tid>/settle", methods=["POST"])
@login_required
@finance_required
def transaction_settle(tid: int):
    """Baixar um lançamento pendente."""
    db = get_db()
    tx = db.execute("SELECT * FROM transactions WHERE id=?", (tid,)).fetchone()
    if not tx:
        flash("Lançamento não encontrado.", "danger")
        return redirect(url_for("finance.transactions"))

    payment_method = (request.form.get("payment_method", "pix") or "pix").strip()
    if payment_method == "card":
        payment_method = "card_credit"
    if payment_method not in {k for k, _ in PAYMENT_METHODS}:
        payment_method = "other"
    date_eff = request.form.get("date", today_yyyy_mm_dd())
    cash_session_id = None
    open_cash_id = get_open_cash_session_id()
    if payment_method == "cash" and open_cash_id:
        cash_session_id = open_cash_id

    db.execute(
        "UPDATE transactions SET status='paid', payment_method=?, date=?, cash_session_id=? WHERE id=?",
        (payment_method, date_eff, cash_session_id, tid),
    )
    db.commit()
    flash("Baixado ✅", "success")
    return redirect(url_for("finance.transactions"))

# Categorias
@bp.route("/categories")
@login_required
@finance_required
def categories_list():
    db = get_db()
    rows = db.execute("SELECT * FROM categories ORDER BY active DESC, name ASC").fetchall()
    return render_template("categories_list.html", rows=rows)

@bp.route("/categories/new", methods=["GET", "POST"])
@login_required
@finance_required
def category_new():
    db = get_db()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        kind = request.form.get("kind", "both")
        if not name:
            flash("Nome é obrigatório.", "danger")
            return render_template("category_form.html", c=None)
        db.execute("INSERT OR IGNORE INTO categories(name, kind) VALUES(?,?)", (name, kind))
        db.commit()
        flash("Categoria salva ✅", "success")
        return redirect(url_for("finance.categories_list"))
    return render_template("category_form.html", c=None)

@bp.route("/categories/<int:cid>/toggle", methods=["POST"])
@login_required
@finance_required
def category_toggle(cid: int):
    db = get_db()
    row = db.execute("SELECT active FROM categories WHERE id=?", (cid,)).fetchone()
    if row:
        newv = 0 if int(row["active"]) == 1 else 1
        db.execute("UPDATE categories SET active=? WHERE id=?", (newv, cid))
        db.commit()
    return redirect(url_for("finance.categories_list"))

# Caixa
@bp.route("/caixa", methods=["GET", "POST"])
@login_required
@finance_required
def caixa():
    db = get_db()
    open_cash_id = get_open_cash_session_id()

    if request.method == "POST":
        action = request.form.get("action")
        if action == "open" and not open_cash_id:
            open_balance = parse_brl_to_cents(request.form.get("open_balance", "0"))
            notes = request.form.get("notes", "").strip()
            db.execute(
                "INSERT INTO cash_sessions(opened_at, open_balance_cents, notes) VALUES(datetime('now'), ?, ?)",
                (open_balance, notes),
            )
            db.commit()
            flash("Caixa aberto ✅", "success")
            return redirect(url_for("finance.caixa"))

        if action == "close" and open_cash_id:
            close_balance = parse_brl_to_cents(request.form.get("close_balance", "0"))
            notes = request.form.get("notes", "").strip()

            # calcula esperado = saldo inicial + entradas cash - saídas cash
            row_open = db.execute("SELECT open_balance_cents FROM cash_sessions WHERE id=?", (open_cash_id,)).fetchone()
            open_balance = int(row_open["open_balance_cents"] or 0)

            rows = db.execute(
                "SELECT kind, SUM(amount_cents) s FROM transactions "
                "WHERE status='paid' AND payment_method='cash' AND cash_session_id=? GROUP BY kind",
                (open_cash_id,),
            ).fetchall()
            incomes = 0
            expenses = 0
            for r in rows:
                if r["kind"] == "income":
                    incomes = int(r["s"] or 0)
                else:
                    expenses = int(r["s"] or 0)
            expected = open_balance + incomes - expenses

            db.execute(
                "UPDATE cash_sessions SET closed_at=datetime('now'), close_balance_cents=?, expected_balance_cents=?, notes=COALESCE(notes,'') || CASE WHEN ?<>'' THEN char(10)||? ELSE '' END WHERE id=?",
                (close_balance, expected, notes, notes, open_cash_id),
            )
            db.commit()
            flash(f"Caixa fechado. Esperado: {cents_to_brl(expected)} | Informado: {cents_to_brl(close_balance)}", "info")
            return redirect(url_for("finance.caixa_history"))

    session_row = None
    expected_now = None
    if open_cash_id:
        session_row = db.execute("SELECT * FROM cash_sessions WHERE id=?", (open_cash_id,)).fetchone()
        # esperado parcial
        row_open = db.execute("SELECT open_balance_cents FROM cash_sessions WHERE id=?", (open_cash_id,)).fetchone()
        open_balance = int(row_open["open_balance_cents"] or 0)

        rows = db.execute(
            "SELECT kind, SUM(amount_cents) s FROM transactions "
            "WHERE status='paid' AND payment_method='cash' AND cash_session_id=? GROUP BY kind",
            (open_cash_id,),
        ).fetchall()
        incomes = 0
        expenses = 0
        for r in rows:
            if r["kind"] == "income":
                incomes = int(r["s"] or 0)
            else:
                expenses = int(r["s"] or 0)
        expected_now = open_balance + incomes - expenses

    return render_template("caixa.html", open_cash_id=open_cash_id, session_row=session_row, expected_now=expected_now, cents_to_brl=cents_to_brl)

@bp.route("/caixa/historico")
@login_required
@finance_required
def caixa_history():
    db = get_db()
    rows = db.execute("SELECT * FROM cash_sessions ORDER BY id DESC LIMIT 60").fetchall()
    return render_template("caixa_historico.html", rows=rows, cents_to_brl=cents_to_brl)

# Profissionais (Dentistas) + Repasses
@bp.route("/providers")
@login_required
@finance_required
def providers_list():
    db = get_db()
    rows = db.execute("SELECT * FROM providers ORDER BY active DESC, name ASC").fetchall()
    return render_template("providers_list.html", rows=rows)

@bp.route("/providers/new", methods=["GET", "POST"])
@login_required
@finance_required
def provider_new():
    db = get_db()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        role = request.form.get("role", "Dentista").strip() or "Dentista"
        default_repasse_percent = request.form.get("default_repasse_percent", "0").strip()
        try:
            drp = max(0, min(100, int(default_repasse_percent)))
        except Exception:
            drp = 0
        if not name:
            flash("Nome é obrigatório.", "danger")
            return render_template("provider_form.html", p=None)
        db.execute("INSERT INTO providers(name, role, default_repasse_percent) VALUES(?,?,?)", (name, role, drp))
        db.commit()
        flash("Profissional salvo ✅", "success")
        return redirect(url_for("finance.providers_list"))
    return render_template("provider_form.html", p=None)

@bp.route("/providers/<int:pid>/toggle", methods=["POST"])
@login_required
@finance_required
def provider_toggle(pid: int):
    db = get_db()
    row = db.execute("SELECT active FROM providers WHERE id=?", (pid,)).fetchone()
    if row:
        newv = 0 if int(row["active"]) == 1 else 1
        db.execute("UPDATE providers SET active=? WHERE id=?", (newv, pid))
        db.commit()
    return redirect(url_for("finance.providers_list"))

@bp.route("/repasses")
@login_required
@finance_required
def repasses():
    db = get_db()
    month_start = date.today().replace(day=1).isoformat()
    rows = db.execute(
        "SELECT pr.id, pr.name, "
        "SUM(CASE WHEN t.status='paid' AND t.date>=? THEN (t.amount_cents*t.repasse_percent)/100 ELSE 0 END) AS repasse_mes, "
        "SUM(CASE WHEN t.status='paid' AND t.repasse_paid=0 THEN (t.amount_cents*t.repasse_percent)/100 ELSE 0 END) AS repasse_pendente "
        "FROM providers pr "
        "LEFT JOIN transactions t ON t.provider_id=pr.id AND t.kind='income' "
        "WHERE pr.active=1 "
        "GROUP BY pr.id, pr.name "
        "ORDER BY pr.name ASC",
        (month_start,),
    ).fetchall()

    # detalhe pendente
    pend = db.execute(
        "SELECT t.*, pr.name AS provider_name, p.name AS patient_name "
        "FROM transactions t "
        "JOIN providers pr ON pr.id=t.provider_id "
        "LEFT JOIN patients p ON p.id=t.patient_id "
        "WHERE t.kind='income' AND t.status='paid' AND t.repasse_percent>0 AND t.repasse_paid=0 "
        "ORDER BY t.date DESC, t.id DESC LIMIT 200"
    ).fetchall()

    return render_template("repasses.html", rows=rows, pend=pend, cents_to_brl=cents_to_brl)

@bp.route("/repasses/<int:tid>/pay", methods=["POST"])
@login_required
@finance_required
def repasse_pay(tid: int):
    db = get_db()
    db.execute("UPDATE transactions SET repasse_paid=1 WHERE id=?", (tid,))
    db.commit()
    flash("Repasse marcado como pago ✅", "success")
    return redirect(url_for("finance.repasses"))
