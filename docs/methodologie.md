# Méthodologie

Ce document explique chaque indicateur, pourquoi il est calculé ainsi, et ce qu'il ne permet pas de conclure.

## 1. Mesurer l'inhabituel par rapport au titre lui-même

Un volume de 50 000 contrats est banal sur une très grande capitalisation et exceptionnel sur une petite. Toutes les comparaisons se font donc contre l'**historique propre** du ticker, jamais en valeur absolue.

- **Rang percentile** : part des séances précédentes où le volume d'options était strictement inférieur à celui du jour. 100 signifie « plus haut volume de l'historique disponible ». C'est le critère principal, parce qu'il ne suppose aucune forme de distribution.
- **Z-score** : écart à la moyenne, en écarts-types. Il est calculé dès 5 séances, mais reste instable sur un historique court. Il sert à départager deux tickers au même rang, pas à décider seul.

## 2. L'open interest, seule trace des positions nouvelles

Le volume compte les contrats échangés dans la journée. L'**open interest** compte les contrats encore ouverts. Si 2 000 contrats s'échangent et que l'open interest monte de 1 500, des positions ont été ouvertes. S'il baisse, des positions existantes ont été fermées.

La variation est calculée **contrat par contrat** (même symbole d'option, donc même échéance, même strike, même type), et non en comparant « les strikes les plus actifs » d'un jour à l'autre, qui changent d'une séance à l'autre et produiraient des variations sans signification.

Yahoo met souvent l'open interest à jour avec une séance de retard. C'est pourquoi il est recommandé de lancer la collecte le matin, avant l'ouverture américaine.

## 3. Le cours a-t-il bougé « en proportion » ?

Le mouvement du jour est rapporté à l'écart-type des variations quotidiennes des 30 séances précédentes (**z-score du mouvement**). Un z-score inférieur à 1 en valeur absolue signifie un mouvement ordinaire pour ce titre : une forte activité sur les options n'a alors pas de contrepartie visible sur le cours.

## 4. Le marquage « candidat »

Un ticker est marqué `candidat` si les trois conditions sont réunies :

| Condition | Seuil par défaut | Constante |
|---|---|---|
| Volume d'options inhabituel | rang ≥ 90e centile | `SEUIL_RANG_VOLUME` |
| Nouvelles positions ouvertes | variation d'open interest totale > 0 | – |
| Cours peu affecté | \|z-score du mouvement\| < 1 | `SEUIL_Z_PRIX` |

En dessous de 10 séances d'historique (`MIN_JOURS_HISTORIQUE`), le marquage vaut `NON EVALUABLE`. Les seuils sont volontairement simples, affichés dans chaque fichier de comparaison et modifiables en haut de `scripts/compare.py`. L'analyste part de ce marquage mais peut signaler un cas limite en expliquant pourquoi.

## 5. Fiabilité de l'historique

| Séances collectées | Fiabilité | Conséquence |
|---|---|---|
| 0 à 9 | insuffisante | aucun volume qualifié d'inhabituel |
| 10 à 19 | partielle | confiance de la vigie plafonnée à « faible » |
| 20 et plus | correcte | comparaisons sur 20 à 30 séances |

Une séance n'est comptée qu'une fois, même si la collecte est relancée le même jour ou tourne un week-end.

## 6. Ce que ces données ne disent jamais

- **La direction.** Chaque contrat a un acheteur et un vendeur. Un fort volume de calls peut être un pari à la hausse, une vente de calls couverts ou la couverture d'une position vendeuse.
- **L'intention.** Ouvrir une position n'indique pas si elle est spéculative ou défensive. Les agents ont pour consigne de décrire une activité, jamais un « positionnement des institutionnels ».
- **Les acteurs.** Les positions réelles des fonds américains (déclarations 13F) ne sont publiées que 45 jours après la fin de chaque trimestre.

C'est pourquoi la vigie doit d'abord proposer **l'explication banale la plus probable** (résultats, dividende, rééquilibrage d'indice, échéance mensuelle, mouvement sectoriel) et pourquoi le journal de suivi existe : seul le taux de réussite mesuré sur plusieurs mois dit si les signalements valent quelque chose.

## 7. Qualité des données

yfinance est une bibliothèque non officielle qui lit Yahoo Finance : cotations en différé, champs parfois vides ou faux, interface qui peut changer sans préavis. Le collecteur n'estime jamais une valeur manquante, et chaque bloc de données porte sa source et son horodatage pour pouvoir remonter à l'origine d'un chiffre.
