# Radar de Passagens Inteligentes

MVP em Streamlit para rastrear passagens aéreas baratas, salvar histórico de cotações, classificar oportunidades e disparar alertas automáticos. O dashboard roda no Streamlit Cloud e o monitoramento 24h roda por GitHub Actions.

## Funcionalidades

- Dashboard com buscas ativas, alertas disparados, menor preço recente e rotas monitoradas.
- Cadastro de monitoramento com origem, destino ou `ANYWHERE`, datas, passageiros, preço máximo, moeda, bagagem e frequência.
- Providers iniciais: Amadeus, Kiwi/Tequila e TravelPayouts.
- Mocks automáticos quando as chaves reais não estão configuradas.
- Histórico de preços por rota.
- Comparação entre provedores.
- Regras de preço: abaixo do limite, queda contra média, menor histórico e oportunidade rara.
- Alertas por Telegram e e-mail.
- GitHub Actions agendado a cada 30 minutos.
- Banco via Supabase/PostgreSQL, com fallback SQLite para teste local.

## Rodar localmente

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run streamlit_app.py
```

## Rodar o monitor manualmente

```bash
python scripts/run_monitor.py
```

## Deploy no Streamlit Cloud

Use:

- Repository: `Tiago84Barros/Radar-de-Passagens-Inteligentes`
- Branch: `main`
- Main file path: `streamlit_app.py`

Detalhes em [docs/STREAMLIT_CLOUD.md](docs/STREAMLIT_CLOUD.md).

## Supabase

Crie um projeto Supabase e copie a string de conexão PostgreSQL para:

```toml
DATABASE_URL = "postgresql://..."
```

Configure esse secret tanto no Streamlit Cloud quanto no GitHub Actions.

## Testes

```bash
pytest
```
