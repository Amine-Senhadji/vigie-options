# Méthodologie

Ce document explique chaque indicateur, pourquoi il est calculé ainsi, et ce qu'il ne permet pas de conclure.

## 1. Mesurer l'inhabituel par rapport au titre lui-même

Un volume de 50 000 contrats est banal sur une très grande capitalisation et exceptionnel sur une petite. Toutes les comparaisons se font donc contre l'**historique propre** du ticker, jamais en valeur absolue.

- **Rang percentile** : part des séances précédentes où le volume d'options était strictement inférieur à celui du jour. 100 signifie « plus haut volume de l'historique disponible ». C'est le critère principal, parce qu'il ne suppose aucune forme de distribution.
- **Z-score** : écart à la moyenne, en écarts-types. Il est calculé dès 5 séances, mais reste instable sur un historique court. Il sert à départager deux tickers au même rang, pas à décider seul.

## 2. L'open interest, seule trace des positions nouvelles

Le volume compte les contrats échangés dans la journée. L'**open interest** compte les contrats encore ouverts. Si 2 000 contrats s'échangent et que l'open interest monte de 1 500, des positions ont été ouvertes. S'il baisse, des positions existantes ont été fermées.

La variation est calculée **contrat par contrat** (même symbole d'option, donc même échéance, même strike, même type), et non en comparant « les strikes les plus actifs » d'un jour à l'autre, qui changent d'une séance à l'autre et produiraient des variations sans signification.

Pour décider si des positions ont été ouvertes, on regarde **là où le volume s'est concentré** : la variation d'open interest est additionnée sur les 5 contrats les plus échangés du jour (`NB_CONTRATS_ACTIFS`), dans `open_interest.strikes_actifs`. La variation totale de la chaîne (`delta_total_calls`, `delta_total_puts`) reste affichée comme contexte, mais elle ne sert pas au marquage : sur des centaines de contrats, le bruit des strikes sans activité peut la rendre positive alors que les contrats réellement échangés ont été fermés. `delta_oi_sur_volume` rapporte la variation au volume de ces contrats : proche de 1, le volume a surtout ouvert des positions ; proche de 0 ou négatif, il a surtout déplacé ou fermé des positions existantes.

Yahoo met souvent l'open interest à jour avec une séance de retard. C'est pourquoi il est recommandé de lancer la collecte le matin, avant l'ouverture américaine.

**Contrôle du décalage d'une séance.** Si l'open interest a une séance de retard, la variation mesurée le matin correspond à l'avant-veille, alors que le volume est celui de la veille : le critère associerait deux séances différentes. Pour le détecter, `compare.py` calcule sur l'ensemble des contrats comparés la corrélation entre la variation absolue d'open interest et le volume du jour, puis avec le volume de la veille (`open_interest.alignement_volume`). Si la seconde dépasse la première de plus de 0,2 (`ECART_ALIGNEMENT`), un avertissement indique que la variation reflète probablement la séance précédente et la vigie plafonne sa confiance à « faible ». Les corrélations ne sont calculées qu'à partir de 10 contrats (`MIN_CONTRATS_CONTROLE`). Il s'agit d'une corrélation de Pearson, sensible aux contrats très échangés : c'est un indice, pas une preuve.

**Contrôle de l'open interest figé.** Si l'open interest est identique à la veille sur au moins 95 % des contrats échangés (`SEUIL_PART_OI_INCHANGE`, à partir de 10 contrats), la source ne l'a probablement pas encore mis à jour : la variation est marquée `non fiable` et le marquage vaut `NON EVALUABLE`.

**Contrôle de qualité.** Yahoo renvoie parfois une chaîne dont l'open interest vaut 0 sur la plupart des contrats, puis des valeurs normales pour la même séance quelques minutes plus tard. Pour chaque ticker, `compare.py` calcule la part de contrats dont l'open interest vaut 0 (sur le total des contrats collectés), le jour et la veille (`qualite_open_interest`). Si cette part dépasse 50 % l'un des deux jours (`SEUIL_PART_OI_ZERO`), la variation d'open interest est marquée `non fiable` avec la raison, et le marquage vaut `NON EVALUABLE`.

## 3. Une base de volume comparable d'un jour à l'autre

Le volume d'options est la somme des contrats des échéances à moins de 60 jours. Cette fenêtre glisse : une nouvelle échéance y entre régulièrement, et son volume s'ajoute à un total qui ne la comptait pas la veille. `compare.py` liste les échéances entrées et sorties de la fenêtre depuis la veille (`echeances`), chiffre le volume qui vient des échéances entrées et l'indique en avertissement. Il signale aussi les séances d'échéance mensuelle (troisième vendredi du mois), où le volume est habituellement élevé pour des raisons mécaniques (débouclages, roulements de positions).

## 4. Les collectes pendant la séance

Pendant la séance américaine (9 h 30 – 16 h à New York, soit en général 15 h 30 – 22 h à Paris), la dernière barre de cours et le volume d'options sont partiels. `collect.py` refuse donc de collecter à ces heures. L'option `--forcer` passe outre, par exemple un jour férié aux États-Unis, que le script ne connaît pas. Le fichier est alors marqué `collecte_pendant_seance`. `compare.py` ne l'utilise ni comme veille ni dans l'historique, et ne qualifie rien le jour même (`NON EVALUABLE`).

## 5. Le cours a-t-il bougé « en proportion » ?

Le mouvement du jour est rapporté à l'écart-type des variations quotidiennes des 30 séances précédentes (**z-score du mouvement**). Un z-score inférieur à 1 en valeur absolue signifie un mouvement ordinaire pour ce titre : une forte activité sur les options n'a alors pas de contrepartie visible sur le cours.

## 6. Le marquage « candidat »

Un ticker est marqué `candidat` si les trois conditions sont réunies :

| Condition | Seuil par défaut | Constante |
|---|---|---|
| Volume d'options inhabituel | rang ≥ 90e centile | `SEUIL_RANG_VOLUME` |
| Nouvelles positions ouvertes | variation d'open interest > 0 sur les 5 contrats les plus échangés | `NB_CONTRATS_ACTIFS` |
| Cours peu affecté | \|z-score du mouvement\| < 1 | `SEUIL_Z_PRIX` |

Le marquage vaut `NON EVALUABLE` en dessous de 10 séances d'historique (`MIN_JOURS_HISTORIQUE`), si l'open interest est non fiable (à 0 sur plus de 50 % des contrats, ou figé : voir section 2), ou si la collecte a eu lieu pendant la séance (section 4). Les seuils sont volontairement simples, affichés dans chaque fichier de comparaison et modifiables en haut de `scripts/compare.py`. L'analyste part de ce marquage mais peut signaler un cas limite en expliquant pourquoi.

## 7. Fiabilité de l'historique

| Séances collectées | Fiabilité | Conséquence |
|---|---|---|
| 0 à 9 | insuffisante | aucun volume qualifié d'inhabituel |
| 10 à 19 | partielle | confiance de la vigie plafonnée à « faible » |
| 20 et plus | correcte | comparaisons sur 20 à 30 séances |

Une séance n'est comptée qu'une fois, même si la collecte est relancée le même jour ou tourne un week-end. Les collectes faites pendant la séance ne comptent pas.

## 8. Ce que ces données ne disent jamais

- **La direction.** Chaque contrat a un acheteur et un vendeur. Un fort volume de calls peut être un pari à la hausse, une vente de calls couverts ou la couverture d'une position vendeuse.
- **L'intention.** Ouvrir une position n'indique pas si elle est spéculative ou défensive. Les agents ont pour consigne de décrire une activité, jamais un « positionnement des institutionnels ».
- **Les acteurs.** Les positions réelles des fonds américains (déclarations 13F) ne sont publiées que 45 jours après la fin de chaque trimestre.

C'est pourquoi la vigie doit d'abord proposer **l'explication banale la plus probable** (résultats, dividende, rééquilibrage d'indice, échéance mensuelle, mouvement sectoriel) et pourquoi le journal de suivi existe : seul le taux de réussite mesuré sur plusieurs mois dit si les signalements valent quelque chose.

## 9. Le journal de suivi

Le journal `suivi/journal.csv` sert à mesurer, au bout de quelques mois, si les signalements valent quelque chose. Il est entièrement tenu par `scripts/suivi.py`, jamais par un agent :

- La vigie dépose ses signalements dans `rapports/signalements-DATE.json`. Le script refuse tout le fichier, sans toucher au journal, si un champ manque ou si un ticker est absent des données collectées ce jour-là.
- Le cours au signalement est la clôture lue dans le fichier brut, pas un chiffre recopié par un agent.
- Le cours à J+14 est la clôture de la première séance à au moins 14 jours calendaires de la séance signalée. Il est complété automatiquement dès qu'une collecte le contient.
- **Témoins.** Un mouvement de 5 % n'a de sens que comparé à ce qu'ont fait les autres titres sur la même période. Pour chaque signalement, le script calcule la variation absolue médiane, sur la même période, des tickers de la watchlist qui n'ont pas été signalés ce jour-là.
- Le journal est réécrit de façon atomique : un plantage ne peut pas le corrompre. Un journal créé avec une version antérieure reçoit les nouvelles colonnes vides, sans perte de lignes.

`python3 scripts/suivi.py bilan` résume le journal : mouvement absolu médian des signalements, celui des témoins, et nombre de signalements au-dessus de leurs témoins, au total et par niveau de confiance. Le bilan mesure un **mouvement absolu**, pas une direction : il ne mesure aucun gain. En dessous de 30 signalements comparés, il précise que les chiffres ne permettent pas de conclure. Les cours ne sont pas ajustés des divisions d'actions : une division pendant la période fausse la ligne concernée.

## 10. Qualité des données

yfinance est une bibliothèque non officielle qui lit Yahoo Finance : cotations en différé, champs parfois vides ou faux, interface qui peut changer sans préavis. Le collecteur n'estime jamais une valeur manquante, et chaque bloc de données porte sa source et son horodatage pour pouvoir remonter à l'origine d'un chiffre.
