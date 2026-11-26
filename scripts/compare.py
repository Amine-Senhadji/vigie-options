#!/usr/bin/env python3
"""Calculs de comparaison pour l'analyste : ne qualifie rien, calcule seulement.

Lit donnees/brut-*.json, compare le jour à la veille et à l'historique propre
de chaque ticker (jusqu'à 30 collectes précédentes). Les collectes faites pendant
la séance américaine (volumes partiels) sont exclues de l'historique.
Les séances de bourse restées sans collecte entre la veille et le jour sont
détectées et signalées : la variation d'open interest couvre alors plusieurs séances.
Le volume d'un contrat n'est compté que si son dernier échange date de la séance :
Yahoo laisse affiché le volume du dernier jour où le contrat a traité, parfois ancien.
Les volumes sont recalculés à partir des contrats des fichiers bruts, historique compris.
Sortie : donnees/comparaison-AAAA-MM-JJ.json

Usage : python3 scripts/compare.py [AAAA-MM-JJ]
"""

import json
import math
import statistics as st
import sys
from datetime import date, datetime, timezone
from itertools import pairwise
from pathlib import Path
from zoneinfo import ZoneInfo

RACINE = Path(__file__).resolve().parent.parent
DOSSIER = RACINE / "donnees"
INDISPO = "INDISPONIBLE"
FENETRE = 30
NEW_YORK = ZoneInfo("America/New_York")  # les séances et les derniers échanges sont datés à l'heure de New York

# Critères du marquage "candidat" : volontairement explicites et modifiables.
SEUIL_RANG_VOLUME = 90  # volume d'options >= 90e centile de son propre historique
SEUIL_Z_VOLUME = 3.5  # et z robuste du volume d'options >= 3,5 (Iglewicz et Hoaglin) : le rang seul retient une séance sur dix
ECHELLE_MAD = 1.4826  # 1,4826 × MAD = écart-type pour une loi normale
ECHELLE_ECART_MOYEN = 1.2533  # repli quand la MAD vaut 0 : 1,2533 × écart moyen absolu à la médiane
MIN_JOURS_HISTORIQUE = 10  # en dessous, on ne qualifie pas un volume d'inhabituel
SEUIL_Z_PRIX = 1.0  # mouvement du cours < 1 écart-type de ses variations récentes
SEUIL_PART_OI_ZERO = 0.5  # au-delà de 50 % de contrats à open interest 0 (jour ou veille), variation d'OI non fiable
NB_CONTRATS_ACTIFS = 5  # l'ouverture de positions est mesurée sur les N contrats les plus échangés du jour
SEUIL_PART_OI_INCHANGE = 0.95  # open interest inchangé sur 95 % des contrats échangés : source pas mise à jour
MIN_CONTRATS_CONTROLE = 10  # nombre minimal de contrats pour les contrôles d'OI figé et d'alignement
ECART_ALIGNEMENT = 0.2  # écart de corrélation au-delà duquel l'OI semble suivre le volume de la veille


def num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def charger(f):
    return json.loads(f.read_text(encoding="utf-8"))


def jour_dernier_echange(contrat):
    """Date du dernier échange du contrat à l'heure de New York (AAAA-MM-JJ), ou None si elle est inconnue."""
    try:
        d = datetime.fromisoformat(str(contrat.get("dernier_echange")))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)  # Yahoo horodate en UTC
    return d.astimezone(NEW_YORK).date().isoformat()


def volume_seance(contrat, seance):
    """Volume du contrat pendant la séance.

    Yahoo laisse affiché le volume du dernier jour où le contrat a traité : il n'appartient
    à la séance que si le dernier échange date de ce jour-là. Sinon le volume de la séance
    vaut 0, y compris quand la date du dernier échange est inconnue. None si le volume manque.
    """
    v = num(contrat.get("volume"))
    if v is None:
        return None
    return v if jour_dernier_echange(contrat) == seance else 0


def volume_options(tk_data):
    """Volume d'options de la séance (total, calls, puts), recalculé à partir des contrats du fichier brut.

    Les totaux écrits par collect.py additionnent tous les volumes affichés, anciens compris : ils ne servent plus.
    """
    d = tk_data or {}
    seance = d.get("cours", {}).get("date_seance")
    contrats = d.get("options", {}).get("contrats")
    if not contrats or not seance or seance == INDISPO:
        return None, None, None
    tot = {}
    for type_ in ("call", "put"):
        vols = [v for c in contrats if c.get("type") == type_ and (v := volume_seance(c, seance)) is not None]
        tot[type_] = sum(vols) if vols else None
    c, p = tot["call"], tot["put"]
    return (c + p if c is not None and p is not None else None), c, p


def volume_ancien(opts, seance):
    """Ce que le filtre écarte : volume affiché par Yahoo mais échangé un autre jour que la séance."""
    ecartes = [
        (c, jour_dernier_echange(c))
        for c in opts.get("contrats", [])
        if (num(c.get("volume")) or 0) > 0 and volume_seance(c, seance) == 0
    ]
    return {
        "volume_ancien_ecarte": sum(c["volume"] for c, _ in ecartes),
        "contrats_au_volume_ancien": len(ecartes),
        "contrats_au_dernier_echange_inconnu": sum(1 for _, j in ecartes if j is None),
    }


def z_robuste(valeur, historique):
    """z-score modifié d'Iglewicz et Hoaglin : (valeur − médiane) ÷ (1,4826 × MAD).

    Si la MAD vaut 0 (plus de la moitié de l'historique partage une valeur), repli sur
    1,2533 × écart moyen absolu à la médiane. None si l'historique est plat ou compte
    moins de MIN_JOURS_HISTORIQUE séances.
    """
    if valeur is None or len(historique) < MIN_JOURS_HISTORIQUE:
        return None
    med = st.median(historique)
    ecarts = [abs(h - med) for h in historique]
    echelle = ECHELLE_MAD * st.median(ecarts)
    if echelle == 0:
        echelle = ECHELLE_ECART_MOYEN * st.mean(ecarts)
    if echelle == 0:
        return None
    return (valeur - med) / echelle


def stats_historique(valeur, historique, avec_log=False):
    if valeur is None:
        return {"statut": INDISPO}
    res = {"jour": valeur, "nb_jours": len(historique)}
    if not historique:
        res["statut"] = "aucun historique"
        return res
    res.update(
        min=min(historique),
        max=max(historique),
        moyenne=round(st.mean(historique), 2),
        mediane=st.median(historique),
        rang_percentile=round(100 * sum(1 for h in historique if h < valeur) / len(historique), 1),
    )
    z = z_robuste(valeur, historique)
    if z is not None:
        res["z_score_robuste"] = round(z, 3)
    if avec_log:
        # À titre d'information seulement : n'intervient jamais dans le marquage candidat
        zl = z_robuste(math.log1p(valeur), [math.log1p(h) for h in historique])
        if zl is not None:
            res["z_score_robuste_log"] = round(zl, 3)
    return res


def mouvement_cours(cours):
    var = num(cours.get("variation_pct"))
    clotures = [num(x.get("cloture")) for x in cours.get("historique_90j", [])]
    clotures = [c for c in clotures if c is not None]
    res = {"variation_pct": var if var is not None else INDISPO}
    rends = [(b / a - 1) * 100 for a, b in pairwise(clotures)][-31:-1]
    if var is not None and len(rends) >= 10 and st.pstdev(rends) > 0:
        res["ecart_type_variations_30j_pct"] = round(st.pstdev(rends), 3)
        res["z_score_mouvement"] = round(var / st.pstdev(rends), 2)
    return res


def part_oi_zero(opts):
    contrats = opts.get("contrats", [])
    if not contrats:
        return None
    return round(sum(1 for c in contrats if num(c.get("open_interest")) == 0) / len(contrats), 4)


def correlation(x, y):
    if len(x) < MIN_CONTRATS_CONTROLE or len(set(x)) < 2 or len(set(y)) < 2:
        return INDISPO
    return round(st.correlation(x, y), 3)


def variation_oi(jour_opts, veille_opts, seance, seance_veille):
    prec = {c["symbole"]: c for c in veille_opts.get("contrats", [])}
    lignes, delta = [], {"call": 0, "put": 0}
    compares = nouveaux = 0
    for c in jour_opts.get("contrats", []):
        cv = prec.get(c["symbole"])
        oi = num(c.get("open_interest"))
        oi_veille = num(cv.get("open_interest")) if cv else None
        d = oi - oi_veille if oi is not None and oi_veille is not None else None
        if cv is None:
            nouveaux += 1
        if d is not None:
            compares += 1
            delta[c["type"]] += d
        vs = volume_seance(c, seance)
        lignes.append(
            {
                **c,
                "volume_seance": vs if vs is not None else INDISPO,
                "volume_veille": (volume_seance(cv, seance_veille) or 0) if cv else INDISPO,
                "open_interest_veille": oi_veille if oi_veille is not None else INDISPO,
                "delta_open_interest": d if d is not None else INDISPO,
            }
        )

    def cle_vol(x):
        return num(x["volume_seance"]) or 0

    top_volume = sorted(lignes, key=cle_vol, reverse=True)[:NB_CONTRATS_ACTIFS]
    top_delta = sorted(
        [x for x in lignes if num(x["delta_open_interest"]) is not None],
        key=lambda x: abs(x["delta_open_interest"]),
        reverse=True,
    )[:5]
    for x in top_volume:
        v, ov = num(x["volume_seance"]), num(x["open_interest_veille"])
        x["volume_sur_oi_veille"] = round(v / ov, 2) if v is not None and ov else INDISPO

    # Ouverture de positions mesurée là où le volume s'est concentré, pas sur toute la chaîne
    actifs = [x for x in top_volume if cle_vol(x) > 0 and num(x["delta_open_interest"]) is not None]
    vol_actifs = sum(cle_vol(x) for x in actifs)
    delta_actifs = sum(x["delta_open_interest"] for x in actifs)
    strikes_actifs = {
        "nb_contrats_mesurables": len(actifs),
        "volume": vol_actifs,
        "delta_open_interest": delta_actifs if actifs else INDISPO,
        "delta_oi_sur_volume": round(delta_actifs / vol_actifs, 3) if vol_actifs else INDISPO,
    }

    # Contrôles : OI figé (source pas mise à jour) et OI qui suit le volume de la veille (décalage d'une séance)
    mesures = [x for x in lignes if num(x["delta_open_interest"]) is not None and num(x["volume_veille"]) is not None]
    echanges = [x for x in mesures if cle_vol(x) > 0]
    inchanges = sum(1 for x in echanges if x["delta_open_interest"] == 0)
    abs_delta = [abs(x["delta_open_interest"]) for x in mesures]
    alignement = {
        "nb_contrats": len(mesures),
        "correlation_avec_volume_du_jour": correlation(abs_delta, [cle_vol(x) for x in mesures]),
        "correlation_avec_volume_de_la_veille": correlation(abs_delta, [x["volume_veille"] for x in mesures]),
    }

    return {
        "contrats_compares": compares,
        "contrats_absents_la_veille": nouveaux,
        "delta_total_calls": delta["call"],
        "delta_total_puts": delta["put"],
        "strikes_actifs": strikes_actifs,
        "part_oi_inchange_sur_contrats_echanges": round(inchanges / len(echanges), 4) if echanges else INDISPO,
        "nb_contrats_echanges_compares": len(echanges),
        "alignement_volume": alignement,
        "strikes_les_plus_actifs": top_volume,
        "plus_fortes_variations_oi": top_delta,
        "note": "Comparaison contrat par contrat (même symbole), pas strike le plus actif contre strike le plus actif. "
        "volume = chiffre affiché par Yahoo ; volume_seance = ce chiffre s'il a été échangé pendant la séance, sinon 0. "
        "Yahoo publie souvent l'open interest avec un jour de retard : voir alignement_volume.",
    }


def troisieme_vendredi(jour):
    """Vrai si la date (AAAA-MM-JJ) est le troisième vendredi du mois, jour d'échéance mensuelle."""
    try:
        d = date.fromisoformat(jour)
    except (TypeError, ValueError):
        return False
    return d.weekday() == 4 and 15 <= d.day <= 21


def echeances(jour_opts, veille_opts, seance):
    j = set(jour_opts.get("echeances_retenues", []))
    v = set(veille_opts.get("echeances_retenues", []))
    entrees = sorted(j - v)
    vol = sum(volume_seance(c, seance) or 0 for c in jour_opts.get("contrats", []) if c.get("echeance") in entrees)
    return {
        "nb_retenues": len(j),
        "entrees_dans_la_fenetre": entrees,
        "volume_echeances_entrees": vol,
        "sorties_de_la_fenetre": sorted(v - j),
        "seance_d_echeance_mensuelle": troisieme_vendredi(seance),
    }


def seances_manquantes(cours, seance, seance_veille):
    """Séances de bourse sans collecte exploitable entre la veille et le jour.

    Le calendrier vient de l'historique des cours du jour : week-ends et jours fériés
    n'y figurent pas et ne sont donc jamais comptés comme manquants.
    """
    dates = sorted(x["date"] for x in cours.get("historique_90j", []) if x.get("date"))
    if not dates or seance not in dates or not seance_veille or seance_veille == INDISPO:
        return {"statut": INDISPO}
    entre = [d for d in dates if seance_veille < d < seance]
    return {
        "seance_veille": seance_veille,
        "nb": len(entre),
        "dates": entre,
        # Veille plus ancienne que l'historique des cours : le décompte n'est qu'un minimum
        "decompte_minimal": seance_veille < dates[0],
    }


def analyser(tk, d, veille, precedents):
    cours, opts = d.get("cours", {}), d.get("options", {})
    seance = cours.get("date_seance", INDISPO)
    res = {"date_seance": seance, "evenements_30j": d.get("evenements", {}).get("evenements", INDISPO), "avertissements": []}

    res["cours"] = mouvement_cours(cours)
    res["cours"]["ratio_volume_action_vs_moyenne_30"] = cours.get("ratio_volume_vs_moyenne_30", INDISPO)

    # Historique propre, une valeur par séance distincte (les relances le même jour sont ignorées)
    hist_vol, hist_ratio, vues = [], [], {seance}
    for p in reversed(precedents):
        tp = p["tickers"].get(tk)
        s = (tp or {}).get("cours", {}).get("date_seance")
        if not tp or s in vues:
            continue
        vues.add(s)
        tot, c, pu = volume_options(tp)
        if tot is not None:
            hist_vol.append(tot)
        if c is not None and pu:
            hist_ratio.append(c / pu)

    tot, c, pu = volume_options(d)
    res["volume_options"] = stats_historique(tot, hist_vol, avec_log=True)
    res["volume_options"].update(calls=c if c is not None else INDISPO, puts=pu if pu is not None else INDISPO)
    if tot is not None:
        res["volume_options"].update(volume_ancien(opts, seance))
    ratio = round(c / pu, 3) if c is not None and pu else None
    res["ratio_calls_puts"] = stats_historique(ratio, [round(r, 3) for r in hist_ratio])

    n = len(hist_vol)
    res["fiabilite_historique"] = "insuffisante" if n < MIN_JOURS_HISTORIQUE else "partielle" if n < 20 else "correcte"

    # Variation d'open interest contre la veille
    tv = veille["tickers"].get(tk) if veille else None
    seance_veille = (tv or {}).get("cours", {}).get("date_seance")
    # Séances restées sans collecte entre la veille et le jour
    if not tv:
        res["seances_manquantes"] = {"statut": "pas de collecte de la veille pour ce ticker"}
    else:
        res["seances_manquantes"] = sm = seances_manquantes(cours, seance, seance_veille)
        if sm.get("nb"):
            res["avertissements"].append(
                f"SÉANCES MANQUANTES : {'au moins ' if sm['decompte_minimal'] else ''}{sm['nb']} séance(s) de bourse "
                f"sans collecte exploitable entre la veille ({seance_veille}) et le jour ({seance}) : {', '.join(sm['dates'])}. "
                f"La variation d'open interest couvre {sm['nb'] + 1} séances alors que le volume est celui du jour seul : "
                "elle ne peut pas être attribuée à la séance du jour"
            )
        elif sm.get("statut") == INDISPO and seance_veille != seance:
            res["avertissements"].append(
                "séances manquantes entre la veille et le jour : INDISPONIBLE (dates de séance ou historique des cours absents)"
            )

    if not tv:
        res["open_interest"] = {"statut": "pas de collecte de la veille pour ce ticker"}
    elif seance_veille == seance:
        res["open_interest"] = {"statut": "même séance que la veille (jour férié ou relance) : variation non mesurable"}
    elif opts.get("statut") == INDISPO or tv.get("options", {}).get("statut") == INDISPO:
        res["open_interest"] = {"statut": INDISPO}
    else:
        res["open_interest"] = variation_oi(opts, tv["options"], seance, seance_veille)
        res["echeances"] = echeances(opts, tv["options"], seance)
        e = res["echeances"]
        if e["entrees_dans_la_fenetre"]:
            res["avertissements"].append(
                f"échéance(s) entrée(s) dans la fenêtre depuis la veille ({', '.join(e['entrees_dans_la_fenetre'])}) : "
                f"{e['volume_echeances_entrees']} contrats du volume du jour viennent d'échéances non comptées la veille"
            )

    # Contrôle de qualité : une chaîne majoritairement à 0 rend la variation d'open interest non fiable
    parts = {"jour": part_oi_zero(opts), "veille": part_oi_zero(tv.get("options", {})) if tv else None}
    res["qualite_open_interest"] = {
        "seuil_part_oi_zero_max": SEUIL_PART_OI_ZERO,
        **{f"part_oi_zero_{k}": v if v is not None else INDISPO for k, v in parts.items()},
    }
    excedents = [f"{k} : {v:.0%}" for k, v in parts.items() if v is not None and v > SEUIL_PART_OI_ZERO]
    if excedents:
        raison = (
            f"open interest à 0 sur plus de {SEUIL_PART_OI_ZERO:.0%} des contrats ({', '.join(excedents)}) : "
            "chaîne possiblement incomplète ou périmée à la source"
        )
        res["open_interest"].update(fiabilite="non fiable", raison=raison)
        res["avertissements"].append(raison)

    oi = res["open_interest"]
    part_inchange = num(oi.get("part_oi_inchange_sur_contrats_echanges"))
    if (
        "fiabilite" not in oi
        and part_inchange is not None
        and oi["nb_contrats_echanges_compares"] >= MIN_CONTRATS_CONTROLE
        and part_inchange >= SEUIL_PART_OI_INCHANGE
    ):
        raison = (
            f"open interest identique à la veille sur {part_inchange:.0%} des contrats échangés : "
            "la source ne l'a probablement pas encore mis à jour"
        )
        oi.update(fiabilite="non fiable", raison=raison)
        res["avertissements"].append(raison)

    al = oi.get("alignement_volume", {})
    cj, cv = num(al.get("correlation_avec_volume_du_jour")), num(al.get("correlation_avec_volume_de_la_veille"))
    if cj is not None and cv is not None and cv - cj > ECART_ALIGNEMENT:
        res["avertissements"].append(
            f"la variation d'open interest suit davantage le volume de la veille (corrélation {cv}) que celui du jour ({cj}) : "
            "elle reflète probablement la séance précédente"
        )
    if troisieme_vendredi(seance):
        res["avertissements"].append("séance d'échéance mensuelle (troisième vendredi) : volume habituellement élevé")

    # Marquage candidat selon des critères fixes et affichés
    vo, oi, mv = res["volume_options"], res["open_interest"], res["cours"]
    if n < MIN_JOURS_HISTORIQUE:
        candidat = "NON EVALUABLE"
        res["avertissements"].append(f"historique de {n} séances : trop court pour qualifier un volume d'inhabituel")
    elif oi.get("fiabilite") == "non fiable":
        candidat = "NON EVALUABLE"
    elif num(vo.get("rang_percentile")) is None or num(oi.get("strikes_actifs", {}).get("delta_open_interest")) is None:
        candidat = "NON EVALUABLE"
        res["avertissements"].append("volume d'options ou variation d'open interest non mesurable aujourd'hui")
    elif num(vo.get("z_score_robuste")) is None:
        candidat = "NON EVALUABLE"
        res["avertissements"].append("z-score robuste du volume d'options non calculable (historique plat)")
    else:
        delta_oi = oi["strikes_actifs"]["delta_open_interest"]
        z = num(mv.get("z_score_mouvement"))
        candidat = (
            vo["rang_percentile"] >= SEUIL_RANG_VOLUME
            and vo["z_score_robuste"] >= SEUIL_Z_VOLUME
            and delta_oi > 0
            and z is not None
            and abs(z) < SEUIL_Z_PRIX
        )
    res["candidat"] = candidat

    if seance != INDISPO and seance < d.get("_date_collecte", seance):
        res["avertissements"].append("la dernière séance disponible est antérieure à la date de collecte")
    return res


def main():
    fichiers = sorted(DOSSIER.glob("brut-*.json"))
    if not fichiers:
        sys.exit("Aucun fichier donnees/brut-*.json : lance d'abord le collecteur.")
    if len(sys.argv) > 1:
        cible = DOSSIER / f"brut-{sys.argv[1]}.json"
        if cible not in fichiers:
            sys.exit(f"{cible.name} introuvable.")
        i = fichiers.index(cible)
    else:
        i = len(fichiers) - 1

    jour = charger(fichiers[i])
    # Les collectes faites pendant la séance (volumes partiels) ne servent ni de veille ni d'historique
    precedents, exclus = [], []
    for f in fichiers[:i]:
        p = charger(f)
        (exclus if p.get("collecte_pendant_seance") else precedents).append((f.name, p))
    precedents = precedents[-FENETRE:]
    veille = precedents[-1][1] if precedents else None

    sortie = {
        "date": jour["date_collecte"],
        "fichier_jour": fichiers[i].name,
        "fichier_veille": precedents[-1][0] if veille else INDISPO,
        "fichiers_exclus_collecte_pendant_seance": [nom for nom, _ in exclus],
        "criteres_candidat": {
            "rang_percentile_volume_options_min": SEUIL_RANG_VOLUME,
            "z_score_robuste_volume_options_min": SEUIL_Z_VOLUME,
            "jours_historique_min": MIN_JOURS_HISTORIQUE,
            "delta_open_interest_strikes_actifs": "> 0",
            "nb_contrats_actifs": NB_CONTRATS_ACTIFS,
            "z_score_mouvement_cours_max_absolu": SEUIL_Z_PRIX,
            "part_contrats_oi_zero_max": SEUIL_PART_OI_ZERO,
            "part_oi_inchange_max": SEUIL_PART_OI_INCHANGE,
        },
        "tickers": {},
    }
    pendant_seance = bool(jour.get("collecte_pendant_seance"))
    for tk, d in jour["tickers"].items():
        d["_date_collecte"] = jour["date_collecte"]
        r = analyser(tk, d, veille, [p for _, p in precedents])
        if pendant_seance:
            r["candidat"] = "NON EVALUABLE"
            r["avertissements"].insert(0, "collecte faite pendant la séance américaine : volumes partiels, rien n'est qualifié")
        sortie["tickers"][tk] = r

    f = DOSSIER / f"comparaison-{jour['date_collecte']}.json"
    f.write_text(json.dumps(sortie, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Fichier : {f.relative_to(RACINE)}")
    for tk, r in sortie["tickers"].items():
        print(f"  {tk} : historique {r['fiabilite_historique']}, candidat = {r['candidat']}")
        sm = r["seances_manquantes"]
        if sm.get("nb"):
            print(f"    ATTENTION : {sm['nb']} séance(s) manquante(s) depuis la veille ({', '.join(sm['dates'])})")


if __name__ == "__main__":
    main()
