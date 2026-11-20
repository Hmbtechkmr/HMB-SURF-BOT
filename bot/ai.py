import asyncio
import logging

import httpx

log = logging.getLogger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELS_URL = "https://api.groq.com/openai/v1/models"

SEMAPHORE = asyncio.Semaphore(3)
MAX_ANSWER_CHARS = 700

SYSTEM_PROMPT = (
    "Tu es HMB AI, l'assistant commercial de HMB SURF BOT, boutique de services "
    "Orange et Camtel. Tu réponds en français simple, naturel et très court, sauf si "
    "le client écrit dans une autre langue. Tu aides à choisir une offre et expliques "
    "le parcours : /start, choix de l'offre, paiement, envoi de la capture d'écran, "
    "vérification par l'administrateur, puis livraison. Tu n'inventes jamais de prix, "
    "de numéro, de disponibilité ou de délai. Pour un litige, dirige vers Assistance. "
    "Ne prétends jamais avoir vérifié un paiement. Maximum 3 phrases, sans liste."
)


def _build_messages(history, text):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for row in history[-6:]:
        content = str(row.get("content", "")).strip()
        if not content:
            continue
        role = "assistant" if row.get("role") == "assistant" else "user"
        messages.append({"role": role, "content": content[:4000]})
    messages.append({"role": "user", "content": str(text).strip()[:4000]})
    return messages


def _shorten(answer):
    answer = " ".join(answer.split())
    if len(answer) <= MAX_ANSWER_CHARS:
        return answer
    cut = answer[:MAX_ANSWER_CHARS]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return (cut[:end + 1] if end > 200 else cut.rsplit(" ", 1)[0]) + "…"


def _extract_answer(data):
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("Groq n'a renvoyé aucun choix.")
    content = (choices[0].get("message") or {}).get("content")
    if isinstance(content, list):
        content = "\n".join(
            str(p.get("text", "")) for p in content
            if isinstance(p, dict) and p.get("type") in ("text", "output_text")
        )
    answer = (content or "").strip()
    if not answer:
        raise RuntimeError(f"Réponse Groq vide ({choices[0].get('finish_reason')}).")
    return _shorten(answer)


async def generate_reply(api_key, model, history, text):
    if not api_key:
        raise RuntimeError("GROQ_API_KEY manquante.")
    if not model:
        raise RuntimeError("GROQ_CHAT_MODEL est vide.")

    payload = {
        "model": model,
        "messages": _build_messages(history, text),
        "max_completion_tokens": 600,
        "reasoning_effort": "low",
        "reasoning_format": "hidden",
    }
    async with SEMAPHORE:
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(40.0, connect=10.0),
                limits=httpx.Limits(max_connections=30, max_keepalive_connections=10),
            ) as client:
                response = await client.post(
                    GROQ_URL,
                    headers={"Authorization": f"Bearer {api_key}",
                             "Content-Type": "application/json"},
                    json=payload,
                )
                response.raise_for_status()
                return _extract_answer(response.json())
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            log.error("Groq HTTP %s : %s", status, exc.response.text[:300])
            if status == 401:
                raise RuntimeError("Clé GROQ_API_KEY invalide.") from exc
            if status == 429:
                raise RuntimeError("Limite Groq atteinte.") from exc
            if status == 400:
                raise RuntimeError(f"Requête Groq refusée (modèle {model}).") from exc
            raise RuntimeError(f"Groq indisponible (HTTP {status}).") from exc
        except httpx.TimeoutException as exc:
            raise RuntimeError("Groq met trop de temps à répondre.") from exc


async def list_models(api_key):
    if not api_key:
        raise RuntimeError("GROQ_API_KEY manquante.")
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(GROQ_MODELS_URL,
                                    headers={"Authorization": f"Bearer {api_key}"})
        response.raise_for_status()
        data = response.json()
    return sorted(i.get("id", "") for i in data.get("data", []) if i.get("id"))
