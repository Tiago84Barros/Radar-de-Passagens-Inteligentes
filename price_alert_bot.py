from __future__ import annotations

from typing import Any

from google import genai
from google.genai import types

GEMINI_MODEL = "gemini-2.5-flash-lite"
MAX_OUTPUT_TOKENS = 200

SYSTEM_INSTRUCTION = (
    "Voce escreve alertas curtos de queda de preco de passagens aereas em "
    "portugues do Brasil. Tom direto e animado, 2 a 3 linhas, no maximo 1 "
    "emoji. Use apenas os dados fornecidos no prompt — nunca invente rotas, "
    "precos, escalas ou datas — e nao inclua links."
)


def _build_prompt(best: dict[str, Any], old_price: float, drop_pct: float) -> str:
    p_ida, p_volta = best.get("price_outbound"), best.get("price_return")
    breakdown = ""
    if p_ida and p_volta:
        breakdown = f"Trechos: ida R$ {float(p_ida):.2f} e volta R$ {float(p_volta):.2f}\n"
    return (
        f"Trecho: {best.get('origin', '')} -> {best.get('destination', '')}\n"
        f"Companhia: {best.get('airline', '')}\n"
        f"Escalas: {best.get('stops', '')}\n"
        f"Preco anterior: R$ {old_price:.2f}\n"
        f"Preco novo: R$ {best.get('price'):.2f}\n"
        f"{breakdown}"
        f"Queda: {drop_pct:.1f}%\n"
        "Escreva o alerta para o viajante avisando dessa queda de preco."
    )


def _call_gemini(prompt: str) -> str:
    client = genai.Client()
    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_INSTRUCTION,
            max_output_tokens=MAX_OUTPUT_TOKENS,
        ),
    )
    return (getattr(response, "text", None) or "").strip()


def write_alert(best: dict[str, Any], old_price: float, drop_pct: float) -> str:
    """Gera o texto do alerta de queda de preco usando Gemini Flash-Lite."""
    prompt = _build_prompt(best, old_price, drop_pct)
    return _call_gemini(prompt)
