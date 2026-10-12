---
description: Collecte, analyse et veille sur la watchlist (aucune recommandation)
---
Enchaîne ces quatre étapes dans l'ordre, sans en sauter aucune :

1. Utilise le sous-agent `collecteur`. S'il signale une erreur bloquante, arrête-toi et affiche-la.
2. Utilise le sous-agent `analyste`.
3. Utilise le sous-agent `vigie`.
4. Lance `.venv/bin/python scripts/suivi.py` si `.venv` existe, sinon `python3 scripts/suivi.py`. Il ajoute les signalements au journal et complète les cours à J+14. S'il refuse le fichier de signalements, affiche son message tel quel : le journal n'a pas été modifié.

Affiche ensuite la sortie de la vigie telle quelle, précédée des avertissements de fiabilité s'il y en a. N'ajoute aucune recommandation, aucun avis haussier ou baissier et aucun commentaire sur ce qu'il faudrait acheter ou vendre.
