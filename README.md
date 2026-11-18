# HMB SURF BOT — version corrigée et simplifiée

Crédit : **HAMZA alliance HMB**

## Configuration Render : seulement 5 variables

Ajoute exactement ces variables dans Render > Environment :

- `BOT_TOKEN` : token du bot Telegram
- `ADMIN_ID` : identifiant Telegram numérique de l'administrateur
- `WEBHOOK_SECRET` : secret aléatoire contenant uniquement lettres, chiffres, `_` ou `-`
- `GEMINI_API_KEY` : clé Gemini
- `GROQ_API_KEY` : clé Groq

L'adresse publique est lue automatiquement depuis `RENDER_EXTERNAL_URL`. Le port est lu depuis `PORT`. Aucune variable `PUBLIC_URL`, `DATABASE_PATH`, `PIPER_*` ou `VOICE_REPLY_ENABLED` à ajouter.

## Piper vocal

Les deux modèles sont téléchargés automatiquement pendant le build Render :
- Français : Piper UPMC, voix Pierre (speaker 1)
- Anglais : Piper en_US-lessac-medium

Le modèle français UPMC est sous CC BY-SA 4.0 ; le modèle anglais Lessac renvoie aux conditions de licence de son jeu de données. Conserve les notices et vérifie les conditions d'utilisation adaptées à ton activité. Références : https://huggingface.co/rhasspy/piper-voices/tree/v1.0.0/fr/fr_FR/upmc/medium et https://huggingface.co/rhasspy/piper-voices/tree/v1.0.0/en/en_US/lessac/medium.

## Render

- Runtime : Python 3.11.9 (`.python-version`)
- Build : `pip install -r requirements.txt && python download_voices.py`
- Start : `python main.py`
- Health check : `/health`

Le fichier `render.yaml` contient déjà ces paramètres et les cinq variables.

## Stockage

SQLite reste dans `data/hmb_surf_bot.sqlite3`, sur le stockage local de l'instance. Aucun disque persistant n'est requis. Les données locales peuvent être perdues lors d'un redéploiement ou remplacement de l'instance Render.

## Fonctionnalités

- Menu, catalogue Orange/Camtel et choix de paiement
- Réception des preuves de paiement et transmission à l'administrateur
- Validation/refus manuels et livraison manuelle
- HMB AI via Gemini
- Transcription des vocaux via Groq Whisper
- Réponses vocales Piper en français et en anglais
- Commandes administrateur : `/admin`, `/stats`, `/orders`, `/deliver ID`, `/broadcast texte`

## Important

Les clés restent privées : ne les ajoute jamais au dépôt GitHub. Les appels Gemini/Groq, le téléchargement des modèles et le déploiement réel doivent être confirmés par les logs Render après le premier déploiement. Les commandes et clients SQLite ne sont pas garantis après redéploiement sans stockage persistant.
