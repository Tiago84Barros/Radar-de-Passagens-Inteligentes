# Radar de Passagens Inteligentes

MVP em Streamlit para rastrear passagens aéreas baratas, salvar histórico de cotações, classificar oportunidades e disparar alertas automáticos. O dashboard roda no Streamlit Cloud e o monitoramento 24h roda por GitHub Actions.

## Funcionalidades

- Dashboard com buscas ativas, alertas disparados, menor preço recente e rotas monitoradas.
- Cadastro de monitoramento com origem, destino ou `ANYWHERE`, datas, passageiros, preço máximo, moeda, bagagem e frequência.
- Providers de busca ativa: SerpApi Google Flights e Travelpayouts.
- Assistente de Escolha opcional com OpenAI ou Gemini, limitado a comparar
  tarifas já confirmadas pelas APIs.
- Sem tarifas simuladas: na ausência de fonte confirmada, a busca retorna vazia.
- Histórico de preços por rota.
- Comparação entre provedores.
- Regras de preço: abaixo do limite, queda contra média, menor histórico e oportunidade rara.
- Alertas por Telegram e e-mail.
- GitHub Actions agendado a cada 2 horas.
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
  fontes estruturadas: **SerpApi Google Flights** é a API principal de
  descoberta e **Travelpayouts** entra como fonte complementar/cache e para
  rotas combinadas. Gemini/OpenAI não participam mais do motor de tarifas.
  Inclui conexões via hubs (`services.multi_segment_search`). Cada oferta é
  carimbada com `source_confidence` (`real` / `verified` / `demo`).

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

Sem `SERPAPI_API_KEY` e/ou `TRAVELPAYOUTS_API_TOKEN`, o app não tem fonte
automática para confirmar tarifas. O link exibido nas ofertas da SerpApi aponta
para a busca correspondente no Google Flights; Travelpayouts aponta para o link
de compra retornado pela API. Não há API de disponibilidade de milhas:
estimativas de milhas são identificadas separadamente e não são tratadas como
disponibilidade real.

Quando a companhia exibe preços em uma página dinâmica que não é retornada pela
API, o app não transforma essa busca em tarifa confirmada. Nesses casos, a tela
vazia mostra atalhos para abrir a mesma rota/data em fontes reais, começando
pela Azul, sem registrar preço inventado.

### Assistente de Escolha

Depois da busca, o painel **Assistente de Escolha** compara preço, duração,
conexões, orçamento, risco de bilhetes separados e ofertas reais em milhas.
Ele sempre funciona em modo local e, opcionalmente, pode usar OpenAI ou Gemini.

As IAs não recebem companhia, data ou link e não escrevem fatos livres. Elas
podem apenas selecionar o ID de uma tarifa confirmada e códigos de motivos já
calculados pelo app. Valores, datas, fontes e links são renderizados diretamente
dos dados das APIs. Uma resposta inválida ou uma falha da IA aciona
automaticamente a análise local segura.

### Captura assistida em fonte oficial

A aba **Captura oficial** cobre o caso em que a tarifa existe no site da
companhia, mas não é acessível pelas APIs configuradas. O
fluxo seguro é:

1. Abrir a fonte oficial pelo botão da aba.
2. Copiar o texto visível da lista de voos da Azul e colar no app; ou rodar o
   coletor local opcional abaixo.
3. O app importa somente linhas que tenham rota, duração e preço em BRL visíveis
   no texto/JSON, sempre com o link da fonte oficial.

Coletor local opcional, sem salvar senha:

```bash
pip install playwright
playwright install chromium
python scripts/capture_azul_assisted.py --origin BEL --destination FOR --departure-date 2026-06-27 --output data/captures/azul-bel-for.json
```

O navegador abre visível. Se aparecer CAPTCHA, login ou seleção adicional, faça
isso manualmente e pressione Enter no terminal quando a lista de voos estiver na
tela. Depois importe o JSON na aba **Captura oficial**.

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
SERPAPI_API_KEY = "..."
TRAVELPAYOUTS_API_TOKEN = "..."

# Opcionais: somente para o Assistente de Escolha no app
OPENAI_API_KEY = "..."
GEMINI_API_KEY = "..."
CHOICE_ASSISTANT_PROVIDER = "auto"
```

Configure `DATABASE_URL`, SerpApi e Travelpayouts tanto no Streamlit Cloud
quanto no GitHub Actions. As chaves OpenAI/Gemini são necessárias apenas no
Streamlit Cloud, pois o bot não usa LLM para pesquisar ou validar tarifas.

## Testes

```bash
pytest
```
