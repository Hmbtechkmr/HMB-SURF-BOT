# Correctif vocal HMB SURF BOT

Ce paquet contient les fichiers complets à remplacer dans le dépôt GitHub.

## Fichiers à remplacer
- `bot/voice.py`
- `bot/handlers.py`
- `main.py`

Ne remplace pas les autres fichiers.

## Ce que fait ce correctif
- Réutilise les modèles Piper chargés en mémoire au lieu de relancer Piper en processus pour chaque vocal.
- Préchauffe la voix française au démarrage.
- Conserve les chemins des modèles français/anglais et le speaker français 1.
- Conserve le cache WAV et le limite à 250 fichiers.
- Donne jusqu'à 300 secondes uniquement aux traitements susceptibles de produire un vocal, sans augmenter le délai des autres commandes.
- Ajoute une mesure du temps de synthèse dans les logs Render.

## Installation GitHub
Dans le dépôt, ouvre chacun des trois fichiers indiqués, remplace tout son contenu par le contenu du fichier fourni, puis commit les changements. Render redéploiera ensuite le projet si l'auto-déploiement est activé.

## Vérification
Les trois fichiers ont passé la compilation syntaxique Python. Le comportement doit ensuite être vérifié sur Render avec `/voicetest` et une demande vocale longue.

Important : le gain exact dépend du CPU et de la mémoire de l'instance Render. Ce correctif évite surtout le rechargement du modèle à chaque demande ; il ne peut pas garantir que la synthèse d'un très long texte sera instantanée.
