# NewClínica V2 (base nova)

Uma base nova, mais simples e organizada, com:
- Login
- Pacientes (CRUD)
- Financeiro (Entradas/Saídas) com status Pago/Pendente
- Categorias
- Caixa (abrir/fechar + histórico)
- Profissionais (dentistas) + Repasses (marcar como pago)
- Valores em centavos (sem bug de vírgula)

## Rodar no PC
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

Acesse: http://127.0.0.1:5000

Login inicial:
- usuário: **admin**
- senha: **admin123**
Depois entre em **Configurações** e troque a senha.

## Render / Produção
- Defina `SECRET_KEY` no ambiente
- Opcional: `DB_PATH` para apontar o SQLite para um disco persistente do Render.
- Start: já vem com `Procfile` usando `gunicorn wsgi:app`

## Próximos passos (fáceis de acoplar)
- Agenda (consultas)
- Orçamentos e Plano/Ficha por paciente
- Exportar PDF/WhatsApp
- Dashboards por dentista (top 5, etc.)
