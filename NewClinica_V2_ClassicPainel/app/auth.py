# -*- coding: utf-8 -*-
from __future__ import annotations

from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, g
from werkzeug.security import check_password_hash, generate_password_hash

from .db import get_db, init_db, ensure_seed_data

bp = Blueprint("auth", __name__)

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        # garante tabelas/migrações mesmo se o usuário já estiver logado
        init_db()
        ensure_seed_data()
        if session.get("user_id") is None:
            return redirect(url_for("auth.login"))
        return view(*args, **kwargs)
    return wrapped

@bp.before_app_request
def load_logged_in_user():
    user_id = session.get("user_id")
    if user_id is None:
        g.user = None
    else:
        g.user = get_db().execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

@bp.route("/login", methods=["GET", "POST"])
def login():
    init_db()
    ensure_seed_data()
    db = get_db()
    # Se ainda não existe usuário, cria admin padrão e força troca depois.
    user = db.execute("SELECT * FROM users ORDER BY id ASC LIMIT 1").fetchone()
    if user is None:
        db.execute(
            "INSERT INTO users(username, password_hash) VALUES(?, ?)",
            ("admin", generate_password_hash("admin123")),
        )
        db.commit()
        flash("Usuário inicial criado: admin / admin123 (troque a senha em Configurações).", "warning")

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = db.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if user is None or not check_password_hash(user["password_hash"], password):
            flash("Login inválido.", "danger")
            return render_template("login.html")
        session.clear()
        session["user_id"] = int(user["id"])
        return redirect(url_for("dashboard.index"))
    return render_template("login.html")

@bp.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("auth.login"))

@bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    db = get_db()
    if request.method == "POST":
        current = request.form.get("current_password", "")
        new1 = request.form.get("new_password", "")
        new2 = request.form.get("new_password2", "")
        user = db.execute("SELECT * FROM users WHERE id=?", (session["user_id"],)).fetchone()
        if not check_password_hash(user["password_hash"], current):
            flash("Senha atual incorreta.", "danger")
        elif len(new1) < 6:
            flash("Senha nova muito curta (mín. 6).", "danger")
        elif new1 != new2:
            flash("As senhas não conferem.", "danger")
        else:
            db.execute("UPDATE users SET password_hash=? WHERE id=?", (generate_password_hash(new1), session["user_id"]))
            db.commit()
            flash("Senha atualizada ✅", "success")
            return redirect(url_for("auth.settings"))
    return render_template("settings.html")
