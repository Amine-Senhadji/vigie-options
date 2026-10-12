# Contribuer

Les suggestions et corrections sont bienvenues, en particulier sur la qualité des données et les critères de détection.

## Mettre en place l'environnement

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest
.venv/bin/ruff check . && .venv/bin/ruff format --check .
```

Les tests utilisent des données simulées (`tests/conftest.py`) et ne font aucun appel réseau.

## Règles du projet

1. **Aucune recommandation.** Aucun prompt ni aucune sortie ne doit inciter à acheter, vendre ou dimensionner une position.
2. **Les calculs restent en Python.** Toute nouvelle mesure va dans `scripts/compare.py`, avec un test, pas dans un prompt.
3. **Pas de trou comblé.** Une donnée manquante reste `INDISPONIBLE`.
4. **Tout seuil est explicite** : une constante nommée, documentée dans `docs/methodologie.md` et recopiée dans le fichier de comparaison.

## Proposer une modification

Ouvre une issue pour en discuter, puis une pull request avec les tests à jour. La CI vérifie le lint et les tests sur Python 3.10, 3.11 et 3.12.
