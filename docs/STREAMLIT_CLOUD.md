# Deploy no Streamlit Cloud

## Configuração

1. Acesse o Streamlit Community Cloud.
2. Clique em **Create app**.
3. Selecione o repositório `Tiago84Barros/Radar-de-Passagens-Inteligentes`.
4. Branch: `main`.
5. Main file path: `streamlit_app.py`.
6. Em **Advanced settings**, cole os secrets.

## Secrets mínimos

```toml
DATABASE_URL = "postgresql://..."
APP_PASSWORD = "uma-senha-para-o-dashboard"
```

Se preferir copiar a aba `.env` do Supabase, use estes nomes no Streamlit Cloud:

```toml
DB_USER = "postgres.seu_project_ref"
DB_PASSWORD = "sua_senha_do_banco"
DB_HOST = "aws-1-us-east-2.pooler.supabase.com"
DB_PORT = "5432"
DB_NAME = "postgres"
APP_PASSWORD = "uma-senha-para-o-dashboard"
```

Sem `DATABASE_URL`, o app usa SQLite local. Isso serve para teste rápido, mas não persiste bem entre reinícios no Streamlit Cloud. Para uso real, use Supabase/PostgreSQL.

## Secrets opcionais

```toml
AMADEUS_CLIENT_ID = ""
AMADEUS_CLIENT_SECRET = ""
AMADEUS_ENV = "test"
KIWI_API_KEY = ""
TRAVELPAYOUTS_TOKEN = ""
TRAVELPAYOUTS_API_TOKEN = ""

TELEGRAM_BOT_TOKEN = ""
TELEGRAM_CHAT_ID = ""

SMTP_HOST = ""
SMTP_PORT = "587"
SMTP_USER = ""
SMTP_PASSWORD = ""
ALERT_FROM_EMAIL = "alerts@radar.local"
```

## Monitoramento 24h

O arquivo `.github/workflows/monitor.yml` roda `scripts/run_monitor.py` a cada 30 minutos e também pode ser disparado manualmente por **workflow_dispatch**.

Configure os mesmos secrets no GitHub Actions em:

`Settings > Secrets and variables > Actions`.
