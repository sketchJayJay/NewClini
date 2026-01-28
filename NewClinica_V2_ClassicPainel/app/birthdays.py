# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import date, datetime, timedelta
from urllib.parse import quote

from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app, jsonify
from .auth import login_required
from .db import get_db

bp = Blueprint("birthdays", __name__, url_prefix="/birthdays")

def _get_setting(db, key: str, default: str = "") -> str:
    row = db.execute("SELECT value FROM app_settings WHERE key=?", (key,)).fetchone()
    return (row["value"] if row and row["value"] is not None else default)

def _render_message(template: str, nome: str, clinica: str) -> str:
    return (template or "").replace("{nome}", nome).replace("{clinica}", clinica)

def _digits_phone(s: str) -> str:
    return "".join(ch for ch in (s or "") if ch.isdigit())

@bp.route("/", methods=["GET", "POST"])
@login_required
def list_birthdays():
    db = get_db()

    if request.method == "POST":
        tpl = (request.form.get("birthday_template") or "").strip()
        if not tpl:
            flash("A mensagem padrão não pode ficar vazia.", "danger")
        else:
            db.execute("INSERT OR REPLACE INTO app_settings(key, value) VALUES(?,?)", ("birthday_template", tpl))
            db.commit()
            flash("Mensagem padrão salva.", "success")
        return redirect(url_for("birthdays.list_birthdays"))

    tpl = _get_setting(
        db,
        "birthday_template",
        "Oi {nome}! 🎉 Hoje é seu aniversário e a {clinica} deseja um dia incrível! Se quiser agendar sua consulta/revisão, é só me chamar por aqui 🙂",
    )
    clinica = current_app.config.get("CLINIC_NAME", "NewClínica")

    today = date.today()
    today_mmdd = today.strftime("%m-%d")
    rows = db.execute(
        "SELECT id, name, phone, birth_date FROM patients WHERE birth_date IS NOT NULL AND birth_date!='' ORDER BY name COLLATE NOCASE"
    ).fetchall()

    sent_today = {
        int(r["patient_id"])
        for r in db.execute("SELECT patient_id FROM birthday_log WHERE sent_on=? AND channel='whatsapp'", (today.isoformat(),)).fetchall()
    }

    todays = []
    upcoming = []
    for r in rows:
        bd_raw = (r["birth_date"] or "").strip()
        if not bd_raw:
            continue
        try:
            bd = date.fromisoformat(bd_raw)
        except ValueError:
            continue

        mmdd = bd.strftime("%m-%d")
        # Próximo aniversário
        next_bd = bd.replace(year=today.year)
        if next_bd < today:
            next_bd = bd.replace(year=today.year + 1)
        delta = (next_bd - today).days

        item = {
            "id": int(r["id"]),
            "name": r["name"],
            "phone": r["phone"] or "",
            "birth_date": bd_raw,
            "next_date": next_bd.isoformat(),
            "days": delta,
            "sent": int(r["id"]) in sent_today,
        }

        if mmdd == today_mmdd:
            msg = _render_message(tpl, item["name"], clinica)
            phone_digits = _digits_phone(item["phone"])
            # Se usuário salva sem DDI, tenta Brasil
            if phone_digits and not phone_digits.startswith("55"):
                phone_digits = "55" + phone_digits
            wa = f"https://wa.me/{phone_digits}?text={quote(msg)}" if phone_digits else ""
            item["wa_link"] = wa
            item["message"] = msg
            todays.append(item)

        if 0 <= delta <= 30:
            upcoming.append(item)

    # Ordena próximos 30 dias
    upcoming.sort(key=lambda x: (x["days"], x["name"].lower()))

    return render_template(
        "birthdays.html",
        todays=todays,
        upcoming=upcoming,
        birthday_template=tpl,
        clinic_name=clinica,
        today=today.isoformat(),
    )

@bp.post("/mark_sent")
@login_required
def mark_sent():
    db = get_db()
    patient_id = request.form.get("patient_id", type=int)
    sent_on = (request.form.get("sent_on") or date.today().isoformat()).strip()
    message = (request.form.get("message") or "").strip()
    if not patient_id:
        return jsonify({"ok": False, "error": "patient_id faltando"}), 400
    db.execute(
        "INSERT OR IGNORE INTO birthday_log(patient_id, sent_on, channel, message) VALUES(?,?, 'whatsapp', ?)",
        (patient_id, sent_on, message),
    )
    db.commit()
    return jsonify({"ok": True})
