import logging

import httpx

log = logging.getLogger(__name__)

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELS_URL = "https://api.groq.com/openai/v1/models"

SYSTEM_PROMPT = (
    "Tu es HMB AI, l'assistant commercial de HMB SURF BOT, boutique de services "
    "Orange et Camtel. Tu réponds en français simple, naturel et court, sauf si le client "
    "écrit dans une autre langue. Tu aides à choisir une offre et expliques le parcours : "
    "/start, choix de l'offre, paiement, envoi de la capture d'écran, vérification par "
    "l'administrateur, puis livraison manuelle. Tu n'inventes jamais de prix, de numéro, "
    "de disponibilité ou de délai : si une information manque, invite le client à consulter "
    "le catalogue ou à contacter Assistance. Pour un litige de paiement ou une commande "
    "bloquée, dirige vers Assistance. Ne prétends jamais avoir vérifié un paiement ni "
    "effectué une livraison. Maximum 6 phrases."
)


def _build_messages(history, text):
    """Construit un historique propre pour l'API Groq."""
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    # Limite l'historique envoyé pour garder des réponses rapides et maîtriser les coûts.
    for row in history[-16:]:
        content = str(row.get("content", "")).strip()
        if not content:
            continue
        role = "assistant" if row.get("role") == "assistant" else "user"
        messages.append({"role": role, "content": content[:6000]})
    messages.append({"role": "user", "content": str(text).strip()[:6000]})
    return messages


def _extract_answer(data):
    choices = data.get("choices") or []
    if not choices:
        raise RuntimeError("Groq n'a renvoyé aucun choix de réponse.")
    message = choices[0].get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        answer = content.strip()
    elif isinstance(content, list):
        # Certaines réponses compatibles OpenAI renvoient le texte sous forme de blocs.
        answer = "\n".join(
            str(part.get("text", ""))
            for part in content
            if isinstance(part, dict) and part.get("type") in ("text", "output_text")
        ).strip()
    else:
        answer = ""
    if not answer:
        reason = choices[0].get("finish_reason", "inconnu")
        raise RuntimeError(f"Réponse Groq vide (finish_reason={reason}).")
    return answer


async def generate_reply(api_key, model, history, text):
    """Moteur conversationnel unique : Groq Chat Completions."""
    if not api_key:
        raise RuntimeError("GROQ_API_KEY manquante dans les variables d'environnement.")
    if not model:
        raise RuntimeError("GROQ_CHAT_MODEL est vide.")

    payload = {
        "model": model,
        "messages": _build_messages(history, text),
        "max_completion_tokens": 600,
        "reasoning_effort": "low",
        "reasoning_format": "hidden",
    }

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(40.0, connect=10.0),
            limits=httpx.Limits(max_connections=30, max_keepalive_connections=10),
        ) as client:
            response = await client.post(
                GROQ_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            return _extract_answer(response.json())
    except httpx.HTTPStatusError as exc:
        detail = exc.response.text[:500]
        log.error("Groq HTTP %s : %s", exc.response.status_code, detail)
        if exc.response.status_code == 401:
            raise RuntimeError("Clé GROQ_API_KEY invalide ou non autorisée.") from exc
        if exc.response.status_code == 429:
            raise RuntimeError("Limite Groq atteinte ou quota temporairement indisponible.") from exc
        if exc.response.status_code == 400:
            raise RuntimeError(
                f"Requête Groq refusée. Vérifie GROQ_CHAT_MODEL ({model}) et ses paramètres."
            ) from exc
        raise RuntimeError(f"Service Groq indisponible (HTTP {exc.response.status_code}).") from exc
    except httpx.TimeoutException as exc:
        log.warning("Délai d'attente dépassé pour Groq.")
        raise RuntimeError("Groq met trop de temps à répondre. Réessaie dans un instant.") from exc


async def list_models(api_key):
    """Retourne les identifiants de modèles visibles par la clé Groq."""
    if not api_key:
        raise RuntimeError("GROQ_API_KEY manquante.")
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            GROQ_MODELS_URL,
            headers={"Authorization": f"Bearer {api_key}"},
        )
        response.raise_for_status()
        data = response.json()
    return sorted(item.get("id", "") for item in data.get("data", []) if item.get("id"))
