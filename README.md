# HMB SURF BOT

Bot Telegram de vente de services Orange / Camtel. Crédit : HAMZA alliance HMB.

## Variables Render

`BOT_TOKEN`, `ADMIN_ID`, `WEBHOOK_SECRET`, `GROQ_API_KEY`. `RENDER_EXTERNAL_URL` et `PORT` sont fournis par Render.

Optionnel : `DIAG_TOKEN` (accès aux endpoints de diagnostic), `ORDER_TTL_MINUTES` (45), `REMINDER_MINUTES` (20), `LOW_STOCK_THRESHOLD` (3), `GROQ_CHAT_MODEL` (`openai/gpt-oss-20b`).

## Endpoints

- `/health` — readiness (base + Telegram), public
- `/telegram/status?k=DIAG_TOKEN`
- `/ai/status?k=DIAG_TOKEN`

## Commandes client

`/start`, `/help`, `/cgu`, `/cancel`, `/lang`

## Commandes admin

`/admin`, `/stats`, `/orders`, `/stock`, `/client ID`, `/deliver CODE`, `/cancelorder CODE`, `/refund CODE`, `/note CODE texte`, `/addstock CODE`, `/addfaq question | réponse`, `/broadcast texte`, `/backup`, `/diag`, `/setwebhook`, `/voicetest`

`/addstock` : envoie la commande puis colle les codes, un par ligne. À la validation d'un paiement, le code est réservé et envoyé automatiquement. Sans stock, la livraison reste manuelle.

## Comportement

- Commandes non payées expirées après `ORDER_TTL_MINUTES`
- Relance automatique après `REMINDER_MINUTES`
- Doublons d'update ignorés, 5 messages / 10 s par utilisateur
- Réponses longues découpées, texte échappé en HTML
- Cache FAQ et cache audio Piper

## Stockage

SQLite dans `data/`, **sur disque éphémère** : la base est perdue à chaque redéploiement. Lance `/backup` régulièrement. Migration automatique au démarrage.

## Vocal

Modèles Piper téléchargés au build (UPMC français, Lessac anglais). `/voicetest` pour vérifier.
