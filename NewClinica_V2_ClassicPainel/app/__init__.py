# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from flask import Flask, session
from .db import close_db
from .auth import bp as auth_bp
from .dashboard import bp as dashboard_bp
from .patients import bp as patients_bp
from .finance import bp as finance_bp
from .agenda import bp as agenda_bp
from .birthdays import bp as birthdays_bp
from .ortho import bp as ortho_bp
from .boletos import bp as boletos_bp

def create_app() -> Flask:
    app = Flask(__name__, instance_relative_config=True)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "change-me-in-production")
    app.config["DB_PATH"] = os.environ.get("DB_PATH", os.path.join(app.instance_path, "newclinica_v2.db"))

    # ===== ASAAS (Boletos) =====
    # ASAAS_ENV: sandbox|production
    app.config["ASAAS_ENV"] = (os.environ.get("ASAAS_ENV", "sandbox") or "sandbox").strip().lower()
    app.config["ASAAS_API_KEY"] = (os.environ.get("ASAAS_API_KEY", "") or "").strip()
    # Token opcional para validar Webhooks do Asaas (header: asaas-access-token)
    app.config["ASAAS_WEBHOOK_TOKEN"] = (os.environ.get("ASAAS_WEBHOOK_TOKEN", "") or "").strip()

    # Informações da clínica (para impressão de orçamento/anamnese etc.)
    # Pode personalizar no Render/PC via variáveis de ambiente.
    app.config["CLINIC_NAME"] = os.environ.get("CLINIC_NAME", "NewClínica Odonto")
    app.config["CLINIC_PHONE"] = os.environ.get("CLINIC_PHONE", "")
    app.config["CLINIC_ADDRESS"] = os.environ.get("CLINIC_ADDRESS", "")
    app.config["CLINIC_EMAIL"] = os.environ.get("CLINIC_EMAIL", "")
    app.config["CLINIC_RESPONSIBLE"] = os.environ.get("CLINIC_RESPONSIBLE", "")
    app.config["CLINIC_CNPJ"] = os.environ.get("CLINIC_CNPJ", "")

    # Proteção extra do Financeiro (senha separada do login)
    # Pode alterar via variável de ambiente FINANCE_PASSWORD (ou FINANCE_PASS)
    app.config["FINANCE_PASSWORD"] = os.environ.get(
        "FINANCE_PASSWORD",
        os.environ.get("FINANCE_PASS", "sorrisonew"),
    )

    @app.context_processor
    def inject_flags():
        # Permite usar {{ finance_unlocked }} em qualquer template
        return {
            "finance_unlocked": bool(session.get("finance_unlocked")),
            "ASAAS_ENV": app.config.get("ASAAS_ENV", "sandbox"),
            "ASAAS_ENABLED": bool(app.config.get("ASAAS_API_KEY")),
        }

    @app.context_processor
    def inject_clinic_info():
        # Permite usar {{ CLINIC_NAME }}, {{ CLINIC_PHONE }}, etc. em qualquer template
        return {
            "CLINIC_NAME": app.config.get("CLINIC_NAME", ""),
            "CLINIC_PHONE": app.config.get("CLINIC_PHONE", ""),
            "CLINIC_ADDRESS": app.config.get("CLINIC_ADDRESS", ""),
            "CLINIC_EMAIL": app.config.get("CLINIC_EMAIL", ""),
            "CLINIC_RESPONSIBLE": app.config.get("CLINIC_RESPONSIBLE", ""),
            "CLINIC_CNPJ": app.config.get("CLINIC_CNPJ", ""),
        }

    # Blueprints
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(patients_bp)
    app.register_blueprint(finance_bp)
    app.register_blueprint(agenda_bp)
    app.register_blueprint(birthdays_bp)
    app.register_blueprint(ortho_bp)
    app.register_blueprint(boletos_bp)

    # DB teardown
    app.teardown_appcontext(close_db)


    return app

# Compatibilidade Render (quando Start Command está como gunicorn app:app)
app = create_app()
