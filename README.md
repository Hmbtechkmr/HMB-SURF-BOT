# HMB SURF BOT

Base technique du bot Telegram **HMB SURF BOT** — crédit : **HAMZA alliance HMB**.

## Fonctions incluses dans cette première version
- Accueil et catalogue Orange / Camtel.
- Choix d'une offre et affichage des instructions de paiement.
- Envoi d'une preuve de paiement (photo) à l'administrateur.
- Validation ou refus par boutons réservés à l'administrateur.
- Notification du client après décision.
- Commande `/deliver ID` pour marquer une commande comme livrée manuellement.
- Endpoint `/health` pour le contrôle de disponibilité.

Le bot ne génère ni ne distribue automatiquement de fichiers de configuration réseau. La livraison reste manuelle par l'administrateur.

## 1. Créer le bot Telegram
1. Dans Telegram, ouvrir BotFather.
2. Créer un bot et copier son token.
3. Récupérer son identifiant numérique Telegram (ADMIN_ID) avec un outil fiable de consultation d'ID.
4. Ne jamais partager le token.

## 2. Lancer en local
Python 3.11 ou plus récent :
```bash
python -m venv .venv
source .venv/bin/activate  # Windows : .venv\\Scripts\\activate
pip install -r requirements.txt
cp .env.example .env
```
Compléter `BOT_TOKEN`, `ADMIN_ID` et `WEBHOOK_SECRET`, puis :
```bash
python main.py
```
Pour un test local, utiliser un tunnel HTTPS et renseigner `PUBLIC_URL` dans `.env`.

## 3. Déployer sur Render
1. Envoyer ce dossier dans un dépôt GitHub privé.
2. Sur Render, créer un **Web Service** depuis ce dépôt.
3. Build command : `pip install -r requirements.txt`
4. Start command : `python main.py`
5. Ajouter les trois variables obligatoires : `BOT_TOKEN`, `ADMIN_ID`, `WEBHOOK_SECRET`.
6. Render fournit `RENDER_EXTERNAL_URL`; le programme l'utilise automatiquement pour créer le webhook.

## Variables d'environnement
- `BOT_TOKEN` : obligatoire.
- `ADMIN_ID` : obligatoire, identifiant numérique du compte administrateur.
- `WEBHOOK_SECRET` : obligatoire, secret de vérification Telegram (lettres/chiffres/tirets/underscores, 1 à 256 caractères).
- `PUBLIC_URL` : facultatif ; sinon `RENDER_EXTERNAL_URL` est utilisé.
- `PORT` : facultatif ; défaut `10000`.
- `DATABASE_PATH` : facultatif ; défaut `./data/hmb_surf_bot.sqlite3`.

## Important pour la production
Le SQLite local peut être perdu lors d'un redéploiement ou d'un remplacement d'instance Render. Avant une utilisation réelle, connecter une base PostgreSQL persistante et adapter la configuration de stockage. Ne pas traiter une capture d'écran comme une preuve définitive : vérifier le paiement dans le compte destinataire.

## Catalogue de démonstration
Les offres dans `bot/catalog.py` sont des exemples repris des éléments fournis dans la conversation. Vérifier les prix, volumes et durées avant publication.
