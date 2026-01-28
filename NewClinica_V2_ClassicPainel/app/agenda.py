# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, flash
from .auth import login_required
from .db import get_db

bp = Blueprint("agenda", __name__, url_prefix="/agenda")

def _iso_to_sql(dt_iso: str | None) -> str | None:
    """Aceita ISO (com ou sem timezone) e retorna 'YYYY-MM-DD HH:MM:SS'."""
    if not dt_iso:
        return None
    s = str(dt_iso).strip()
    if not s:
        return None
    # FullCalendar pode mandar "Z"
    s = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # tenta formato sem segundos
        try:
            dt = datetime.fromisoformat(s[:16])
        except Exception:
            return None
    # Mantém o horário "de parede" (local), descartando tzinfo se existir
    if getattr(dt, "tzinfo", None) is not None:
        dt = dt.replace(tzinfo=None)
    return dt.strftime("%Y-%m-%d %H:%M:%S")

def _sql_to_iso(dt_sql: str | None) -> str | None:
    if not dt_sql:
        return None
    s = str(dt_sql).strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace(" ", "T"))
        return dt.strftime("%Y-%m-%dT%H:%M:%S")
    except Exception:
        return None

@bp.get("/")
@login_required
def calendar_view():
    db = get_db()
    patients = db.execute("SELECT id, name FROM patients ORDER BY name COLLATE NOCASE").fetchall()
    providers = db.execute("SELECT id, name FROM providers ORDER BY name COLLATE NOCASE").fetchall()
    return render_template("agenda_calendar.html", patients=patients, providers=providers)

@bp.get("/events")
@login_required
def events():
    db = get_db()
    start = request.args.get("start")  # ISO
    end = request.args.get("end")
    provider_id = request.args.get("provider_id", type=int)

    start_sql = _iso_to_sql(start) or "1970-01-01 00:00:00"
    end_sql = _iso_to_sql(end) or "2999-12-31 23:59:59"

    where_extra = ""
    params = [start_sql, end_sql]
    if provider_id:
        where_extra = " AND a.provider_id = ? "
        params.append(provider_id)

    rows = db.execute(
        f"""
        SELECT a.id, a.title, a.start_at, a.end_at, a.note,
               a.patient_id, p.name AS patient_name, p.phone AS patient_phone,
               a.provider_id, pr.name AS provider_name
          FROM appointments a
          JOIN patients p ON p.id = a.patient_id
          LEFT JOIN providers pr ON pr.id = a.provider_id
         WHERE a.start_at >= ? AND a.start_at < ? {where_extra}
         ORDER BY a.start_at ASC
        """,
        tuple(params),
    ).fetchall()

    out = []
    for r in rows:
        start_iso = _sql_to_iso(r["start_at"])
        end_iso = _sql_to_iso(r["end_at"]) if r["end_at"] else None
        if not end_iso and start_iso:
            # padrão: 30 minutos
            try:
                dt = datetime.fromisoformat(start_iso)
                end_iso = (dt + timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%M:%S")
            except Exception:
                end_iso = None

        out.append({
            "id": r["id"],
            "title": f"{r['patient_name']} • {r['title']}",
            "start": start_iso,
            "end": end_iso,
            "extendedProps": {
                "patient_id": r["patient_id"],
                "patient_name": r["patient_name"],
                "patient_phone": r["patient_phone"] or "",
                "provider_id": r["provider_id"],
                "provider_name": r["provider_name"] or "",
                "note": r["note"] or "",
                "raw_title": r["title"] or "Consulta",
            }
        })
    return jsonify(out)

@bp.post("/event/create")
@login_required
def create_event():
    db = get_db()
    patient_id = request.form.get("patient_id", type=int)
    provider_id_raw = request.form.get("provider_id")
    provider_id = None
    if provider_id_raw is not None:
        s = str(provider_id_raw).strip()
        provider_id = int(s) if s.isdigit() else None
    title = (request.form.get("title") or "Consulta").strip()
    start_at = _iso_to_sql(request.form.get("start_at"))
    end_at = _iso_to_sql(request.form.get("end_at"))
    note = (request.form.get("note") or "").strip()

    if not patient_id or not start_at:
        flash("Selecione o paciente e o horário de início.", "danger")
        return redirect(url_for("agenda.calendar_view"))

    db.execute(
        "INSERT INTO appointments(patient_id, provider_id, title, start_at, end_at, note) VALUES(?,?,?,?,?,?)",
        (patient_id, provider_id, title, start_at, end_at, note),
    )
    db.commit()
    flash("Agendamento criado.", "success")
    return redirect(url_for("agenda.calendar_view"))

@bp.post("/event/<int:aid>/update")
@login_required
def update_event(aid: int):
    db = get_db()
    # Pode vir de drag/drop (start/end) ou do formulário completo
    start_at = _iso_to_sql(request.form.get("start_at"))
    end_at = _iso_to_sql(request.form.get("end_at"))
    title = request.form.get("title")
    provider_id_raw = request.form.get("provider_id")
    provider_id = None
    if provider_id_raw is not None:
        s = str(provider_id_raw).strip()
        provider_id = int(s) if s.isdigit() else None
    note = request.form.get("note")

    # Atualização mínima
    if start_at or end_at:
        db.execute(
            "UPDATE appointments SET start_at=COALESCE(?, start_at), end_at=COALESCE(?, end_at) WHERE id=?",
            (start_at, end_at, aid),
        )

    # Atualização completa (se enviado)
    if title is not None:
        db.execute("UPDATE appointments SET title=? WHERE id=?", ((title or "Consulta").strip(), aid))
    if provider_id_raw is not None:
        db.execute("UPDATE appointments SET provider_id=? WHERE id=?", (provider_id, aid))
    if note is not None:
        db.execute("UPDATE appointments SET note=? WHERE id=?", ((note or "").strip(), aid))

    db.commit()
    return jsonify({"ok": True})

@bp.post("/event/<int:aid>/delete")
@login_required
def delete_event(aid: int):
    db = get_db()
    db.execute("DELETE FROM appointments WHERE id=?", (aid,))
    db.commit()
    flash("Agendamento excluído.", "success")
    return redirect(url_for("agenda.calendar_view"))
