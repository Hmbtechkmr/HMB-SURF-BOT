import logging

import httpx

log = logging.getLogger(__name__)

GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
# Modèles essayés dans l'ordre si celui configuré échoue (400/404/429/5xx).
FALLBACK_MODELS = ("gemini-3.6-flash", "gemini-3.8-flash", "gemini-3.5-flash-lite")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

SYSTEM_PROMPT = (
    "Tu es HMB AI, l'assistant commercial de HMB SURF BOT, boutique de services "
    "Orange et Camtel. Tu réponds en français simple et court, sauf si le client "
    "écrit dans une autre langue. Tu aides à choisir une offre, expliques les moyens "
    "de paiement et le parcours : /start, choix de l'offre, paiement, envoi de la "
    "capture d'écran, vérification par l'administrateur, livraison manuelle. "
    "Tu n'inventes jamais de prix : tu renvoies au catalogue. Pour un litige de "
    "paiement ou une commande bloquée, tu diriges vers Assistance. Maximum 6 phrases."
)


def _build_contents(history, text):
    contents = []
    for row in history:
        role = "model" if row["role"] == "assistant" else "user"
        if contents and contents[-1]["role"] == role:
            contents[-1]["parts"].append({"text": row["content"]})
        else:
            contents.append({"role": role, "parts": [{"text": row["content"]}]})
    if contents and contents[-1]["role"] == "user":
        contents[-1]["parts"].append({"text": text})
    else:
        contents.append({"role": "user", "parts": [{"text": text}]})
    return contents


def _extract(data):
    candidates = data.get("candidates") or []
    if not candidates:
        feedback = data.get("promptFeedback", {}).get("blockReason")
        raise RuntimeError(f"Réponse Gemini vide (blockReason={feedback}).")
    parts = (candidates[0].get("content") or {}).get("parts") or []
    answer = "\n".join(p.get("text", "") for p in parts).strip()
    if not answer:
        reason = candidates[0].get("finishReason", "inconnu")
        raise RuntimeError(f"Réponse Gemini vide (finishReason={reason}).")
    return answer


async def _gemini(api_key, model, history, text):
    body = {
        "contents": _build_contents(history, text),
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        # Pas de temperature : non supportée par les modèles Gemini 3.
        "generationConfig": {"maxOutputTokens": 1024},
    }
    async with httpx.AsyncClient(timeout=45) as client:
        response = await client.post(
            f"{GEMINI_BASE}/models/{model}:generateContent",
            # Clés AQ. : l'en-tête est obligatoire, ?key= renvoie 404.
            headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
            json=body,
        )
        response.raise_for_status()
        data = response.json()
    return _extract(data)


async def _groq(api_key, model, history, text):
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for row in history:
        role = "assistant" if row["role"] == "assistant" else "user"
        messages.append({"role": role, "content": row["content"]})
    messages.append({"role": "user", "content": text})
    async with httpx.AsyncClient(timeout=45) as client:
        response = await client.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "messages": messages, "max_tokens": 1024, "temperature": 0.6},
        )
        response.raise_for_status()
        data = response.json()
    answer = (data["choices"][0]["message"]["content"] or "").strip()
    if not answer:
        raise RuntimeError("Réponse Groq vide.")
    return answer


async def list_models(api_key):
    """Diagnostic : liste les modèles accessibles à cette clé."""
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(
            f"{GEMINI_BASE}/models",
            headers={"x-goog-api-key": api_key},
            params={"pageSize": 200},
        )
        response.raise_for_status()
        return [m.get("name", "") for m in response.json().get("models", [])]


async def generate_reply(api_key, model, history, text,
                         groq_api_key="", groq_model="llama-3.3-70b-versatile"):
    last_error = None

    if api_key:
        models = [m for m in (model, *FALLBACK_MODELS) if m]
        models = list(dict.fromkeys(models))
        for candidate in models:
            try:
                return await _gemini(api_key, candidate, history, text)
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                log.warning("Gemini %s -> HTTP %s : %s",
                            candidate, status, exc.response.text[:200])
                last_error = exc
                if status in (400, 404, 429, 500, 503):
                    continue
                break
            except Exception as exc:
                log.warning("Gemini %s -> %s", candidate, exc)
                last_error = exc
                continue

    if groq_api_key:
        try:
            log.info("Bascule sur Groq (%s).", groq_model)
            return await _groq(groq_api_key, groq_model, history, text)
        except Exception as exc:
            log.exception("Groq indisponible")
            last_error = exc

    raise last_error or RuntimeError("Aucune clé IA configurée.")
