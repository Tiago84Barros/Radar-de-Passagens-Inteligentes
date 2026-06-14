"""Diagnóstico do monitor — descobre por que nenhum alerta chega no Telegram.

Uso (local, na raiz do projeto):

    python scripts/diagnose_monitor.py                 # só inspeciona config + buscas
    python scripts/diagnose_monitor.py --run           # roda a busca de cada monitor ativo
    python scripts/diagnose_monitor.py --test-telegram # envia 1 mensagem de teste

Para apontar ao banco de produção, defina DATABASE_URL (e os tokens) antes:
    setx DATABASE_URL "postgresql://..."   (ou use um .env / variáveis de sessão)

NÃO imprime segredos — só diz se cada um está presente.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import select

from app.db import MonitoredSearch, init_db, session_scope
from app.settings import get_settings
from services.decision_engine import REC_BUY, REC_MILES
from services.monitoring_bot import (
    RUNNABLE_STATUS,
    _offer_to_option,
    _preferences,
    _recommendation_for,
    is_due,
    is_within_tracking_window,
    query_from_monitor,
)
from providers.provider_manager import search_all_providers
from services.recommendation_service import rank_flight_options


def _present(value) -> str:
    return "PRESENTE" if value else "AUSENTE  <-- problema"


def main() -> None:
    s = get_settings()
    print("=" * 60)
    print(" CONFIGURAÇÃO")
    print("=" * 60)
    db_kind = "sqlite (LOCAL/vazio)" if s.database_url.startswith("sqlite") else "postgres (remoto)"
    print(f" DATABASE_URL ......... {db_kind}")
    print(f" TELEGRAM_BOT_TOKEN ... {_present(s.telegram_bot_token)}")
    print(f" TELEGRAM_CHAT_ID ..... {_present(s.telegram_chat_id)}")
    print(f" GEMINI_API_KEY ....... {_present(s.gemini_api_key)}")
    print(f" OPENAI_API_KEY ....... {_present(s.openai_api_key)}")
    print(f" TRAVELPAYOUTS ........ {_present(s.travelpayouts_api_token)}")
    if not (s.telegram_bot_token and s.telegram_chat_id):
        print("\n >> Telegram NÃO configurado neste ambiente: nenhum alerta seria enviado.")
        print("    (No GitHub Actions os secrets existem; localmente você precisa defini-los.)")

    init_db()
    now = datetime.now(timezone.utc)
    with session_scope() as db:
        rows = list(db.scalars(select(MonitoredSearch)))
        print("\n" + "=" * 60)
        print(f" BUSCAS MONITORADAS: {len(rows)}")
        print("=" * 60)
        if not rows:
            print(" Nenhuma busca cadastrada. Crie uma no app (aba Buscar -> rastrear 24h).")
        runnable = []
        for r in rows:
            active = (r.status or "").strip().lower() == RUNNABLE_STATUS
            in_window = is_within_tracking_window(r, now)
            due = is_due(r, now)
            will_run = active and in_window and due
            if active and in_window:
                runnable.append(r)
            print(f"\n #{r.id}  {r.origin_iata} -> {r.destination_iata}")
            print(f"     status={r.status!r}  max_price={r.max_price}")
            print(f"     created_at={r.created_at}  last_checked_at={r.last_checked_at}")
            print(f"     ativa={active}  dentro_da_janela_24h={in_window}  vencida_due={due}")
            if not active:
                print("     >> NÃO roda: status != 'active'.")
            elif not in_window:
                print("     >> NÃO roda: passou das 24h desde a criação -> RECRIE a busca no app.")
            elif not due:
                print("     >> Ainda não venceu (rodaria no próximo tick de 2h, ou use --run/force).")
            else:
                print("     >> RODARIA agora.")

        if "--run" in sys.argv:
            print("\n" + "=" * 60)
            print(" SIMULAÇÃO DE BUSCA (monitores ativos dentro da janela)")
            print("=" * 60)
            if not runnable:
                print(" Nenhum monitor elegível para simular.")
            for r in runnable:
                try:
                    offers = search_all_providers(query_from_monitor(r))
                except Exception as exc:  # noqa: BLE001
                    print(f" #{r.id}: ERRO na busca: {exc}")
                    continue
                options = [_offer_to_option(o, r) for o in offers]
                ranking = rank_flight_options(options, _preferences(r))
                best = ranking.get("recommended_option") or ranking.get("cheapest_option")
                print(f"\n #{r.id}: {len(offers)} ofertas encontradas.")
                if not best:
                    print("     Nenhuma tarifa -> nada a alertar nesta verificação.")
                    continue
                rec = _recommendation_for(best, r)
                worth = bool(
                    (r.max_price and best["price_brl"] <= r.max_price)
                    or rec["recommendation"] in {REC_BUY, REC_MILES}
                )
                print(f"     melhor preço = R$ {best['price_brl']:.2f}  (max_price={r.max_price})")
                print(f"     recomendação = {rec['recommendation']}")
                print(f"     vale alertar (worth_alert) = {worth}")
                if not worth:
                    print("     >> NÃO alerta: melhor preço acima do seu max_price (ajuste o limite no app).")

    if "--test-telegram" in sys.argv:
        print("\n" + "=" * 60)
        print(" TESTE DE ENVIO AO TELEGRAM")
        print("=" * 60)
        from services.telegram_service import send_telegram_message

        ok, detail = send_telegram_message(
            "🔧 Teste do Radar de Passagens — se você recebeu isto, o canal do Telegram está OK."
        )
        print(f" enviado={ok}  detalhe={detail}")
        if not ok:
            print(" >> Corrija a config acima (token/chat_id) e tente de novo.")


if __name__ == "__main__":
    main()
