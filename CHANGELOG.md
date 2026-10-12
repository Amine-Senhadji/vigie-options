# Historique des versions

## 1.1.0

### Détection

- L'ouverture de positions se mesure sur les 5 contrats les plus échangés du jour (`open_interest.strikes_actifs`), et non plus sur toute la chaîne, où le bruit des strikes inactifs pouvait suffire à rendre la variation positive.
- Détection d'un open interest figé, c'est-à-dire identique à la veille sur au moins 95 % des contrats échangés. Il est alors marqué non fiable et le ticker `NON EVALUABLE`.
- Détection d'un open interest en retard d'une séance, par comparaison de sa corrélation avec le volume du jour et avec celui de la veille (`alignement_volume`).
- Signalement des échéances entrées dans la fenêtre de 60 jours depuis la veille, avec le volume concerné, et des séances d'échéance mensuelle.

### Collecte

- `collect.py` refuse de collecter pendant la séance américaine, où les volumes sont partiels. L'option `--forcer` sert les jours fériés. Ces collectes sont exclues de l'historique et de la veille.
- Ajout de `tzdata` sous Windows pour les fuseaux horaires.

### Journal de suivi

- Nouveau script `scripts/suivi.py`. La vigie écrit ses signalements dans `rapports/signalements-DATE.json`, et le script les vérifie (champs requis, tickers réellement collectés) avant de les ajouter au journal.
- Le cours au signalement est lu dans les données brutes, et le cours à J+14 est complété automatiquement.
- Chaque signalement est comparé à des témoins : les tickers non signalés le même jour.
- `suivi.py bilan` résume le journal, sans conclure en dessous de 30 signalements.
- Le journal est écrit de façon atomique. Les journaux 1.0 sont migrés sans perte.

### Tests

- Passage de 13 à 29 tests.

## 1.0.0

- Première version : agents collecteur, analyste et vigie, commande `/bourse`, `collect.py`, `compare.py`, tests sur données simulées.
