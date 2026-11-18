import httpx
from .catalog import CATALOG, PAYMENT_METHODS

SYSTEM_PROMPT = """Tu es HMB AI, l'assistant IA officiel du service client HMB SURF BOT.
Tu dois répondre dans la langue dominante du client (français ou anglais), avec un ton
professionnel, naturel, patient et concis. Tu es transparent : si on te demande, précise
que tu es une intelligence artificielle, pas un humain.

RÈGLES STRICTES :
- N'invente jamais un paiement reçu, une activation, une livraison, un stock, un délai ou une garantie.
- Seul l'administrateur vérifie les paiements et effectue la livraison manuellement.
- Ne demande jamais le token Telegram ni les clés API du client.
- Pour une question incertaine, un litige ou une demande qui nécessite une vérification,
  demande au client d'utiliser Assistance afin que l'administrateur prenne le relais.
- Ne promets pas un débit ou une couverture non confirmés.
- Utilise uniquement les offres et informations de la base de connaissances ci-dessous.
- Le bot ne crée ni ne distribue automatiquement les fichiers de configuration réseau.

BASE DE CONNAISSANCES CONFIRMÉE :
ORANGE — SXB VPN :
500 FCFA = 5 Go / 5 jours ; 1 000 FCFA = 10 Go / 10 jours ;
1 500 FCFA = 15 Go / 13 jours ; 2 000 FCFA = 20 Go / 15 jours.
CAMTEL — BLUE :
500 FCFA = illimité / 14 jours ; 1 000 FCFA = illimité / 1 mois.
Applications Camtel indiquées : ZIVPN / HTTP Custom selon l'offre.
Paiement Orange Money : 692274053, bénéficiaire IKATIRMEY.
Paiement Mobile Money : 651388771, bénéficiaire MALLAMA SPAWA.
Le client doit envoyer une preuve en photo. L'administrateur vérifie le paiement.
Après validation, la livraison est effectuée manuellement.
Créateur : HAMZA alliance HMB.
"""

async def generate_reply(api_key, model, history, user_text):
    if not api_key:
        return "L'assistant IA n'est pas encore configuré. Utilise Assistance pour contacter l'administrateur."
    contents = []
    for item in history[-10:]:
        role = "model" if item["role"] == "assistant" else "user"
        contents.append({"role": role, "parts": [{"text": item["content"]}]})
    contents.append({"role": "user", "parts": [{"text": user_text}]})
    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": contents,
        "generationConfig": {"temperature": 0.35, "maxOutputTokens": 650},
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    async with httpx.AsyncClient(timeout=35) as client:
        response = await client.post(url, params={"key": api_key}, json=payload)
        response.raise_for_status()
        data = response.json()
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"].strip()
    except (KeyError, IndexError, TypeError):
        return "Je n'ai pas pu formuler une réponse fiable. Utilise Assistance pour contacter l'administrateur."
