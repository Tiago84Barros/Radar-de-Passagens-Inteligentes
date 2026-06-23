# Radar de Passagens Inteligentes

MVP em Streamlit para rastrear passagens aéreas baratas, salvar histórico de cotações, classificar oportunidades e disparar alertas automáticos. O dashboard roda no Streamlit Cloud e o monitoramento 24h roda por GitHub Actions.

## Funcionalidades

- Dashboard com buscas ativas, alertas disparados, menor preço recente e rotas monitoradas.
- Cadastro de monitoramento com origem, destino ou `ANYWHERE`, datas, passageiros, preço máximo, moeda, bagagem e frequência.
- Providers iniciais: Amadeus, Kiwi/Tequila e TravelPayouts.
- Sem tarifas simuladas: na ausência de fonte confirmada, a busca retorna vazia.
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

O motor de busca atual:

- `providers.provider_manager.search_all_providers` — busca por rota com
  hierarquia de confiabilidade: **Travelpayouts (preço real) é primário**; as
  IAs de busca web (Gemini/OpenAI) só entram quando a URL exata da tarifa está
  presente nas citações nativas da ferramenta de busca. Respostas sem citação,
  com homepage genérica ou domínio não confiável são descartadas. Inclui
  conexões via hubs (`services.multi_segment_search`). Cada oferta é carimbada
  com `source_confidence` (`real` / `verified`).

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

### Fontes confirmadas

Sem `TRAVELPAYOUTS_API_TOKEN` e sem uma página citada por Gemini/OpenAI, o app
não mostra tarifa. O link exibido nas ofertas de busca web é a página onde o
preço foi encontrado, como Skyscanner, Decolar, Google Flights ou o site da
companhia. Não há API de disponibilidade de milhas: estimativas de milhas são
identificadas separadamente e não são tratadas como disponibilidade real.

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
