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

## Radar de decisão (dinheiro × milhas)

A tela inicial é um **assistente de decisão**, não um painel de histórico. Ela
responde: *o preço está bom? vale comprar agora, monitorar ou emitir com milhas?*

Dois modos de busca na lateral (**Tipo de busca**):

- **Rota específica** — origem + destino + datas. Mostra a *Recomendação do
  sistema* (Comprar agora / Monitorar / Aguardar / Melhor pagar em dinheiro /
  Melhor usar milhas), as melhores opções em dinheiro e em milhas, e os preços
  por companhia.
- **Encontrar destinos mais baratos** — origem + janela de viagem + escopo
  (Brasil / Exterior / Ambos). Usa o **motor de múltiplos destinos preservado**
  e devolve um ranking de destinos mais baratos (Brasil e Exterior), cada um com
  recomendação e botão *Monitorar este destino*.

### Motores preservados (não removidos)

O refactor de decisão **reaproveita** o motor de busca existente:

- `providers.provider_manager.search_all_providers` — busca por rota
  (Travelpayouts + scrapers + conexões via hubs).
- `services.opportunity_service.get_home_deals` — ranking de destinos mais
  baratos (nacional/internacional).

A camada `services.multi_destination_adapter` é um **wrapper fino** que converte
a saída desses motores para o formato de oportunidade da nova interface e nunca
reimplementa a lógica de providers. Há testes em
`tests/test_multi_destination.py` garantindo que a busca por múltiplos destinos
continua funcionando.

### Serviços de decisão e milhas

- `services.decision_engine.build_purchase_recommendation` — gera a recomendação,
  confiança, motivos e melhores opções (dinheiro/milhas) a partir das cotações,
  do histórico curto recente e das regras do usuário.
- `services.miles_service` — `estimate_miles_from_cash_price`,
  `calculate_mile_value`, `compare_cash_vs_miles`. Milhas são sempre
  **estimadas** (padrão R$ 0,035/milha, configurável na lateral) e exibem o
  aviso: *"Milhas estimadas. A disponibilidade real depende do programa de
  fidelidade."*

### Histórico vira insumo técnico

O histórico continua no banco, mas saiu do protagonismo: gráficos e calendário
ficam na aba **Histórico técnico**. Na tela inicial o histórico aparece só como
apoio (ex.: *"18% abaixo da média recente observada pelo radar"*).

### Modo demonstração

Sem `TRAVELPAYOUTS_API_TOKEN` (ou quando uma rota falha), o app usa cotações de
**demonstração** claramente marcadas, então a interface de decisão e a busca de
múltiplos destinos funcionam mesmo sem API real. Não há API de disponibilidade
de milhas: os valores em milhas são sempre estimados a partir do preço.

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
