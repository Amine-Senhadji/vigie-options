#!/usr/bin/env python3
"""Calculs de comparaison pour l'analyste : ne qualifie rien, calcule seulement.

Lit donnees/brut-*.json, compare le jour à la veille et à l'historique propre
de chaque ticker (jusqu'à 30 collectes précédentes).
Sortie : donnees/comparaison-AAAA-MM-JJ.json

Usage : python3 scripts/compare.py [AAAA-MM-JJ]
"""

import json
import statistics as st
import sys
from itertools import pairwise
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
DOSSIER = RACINE / "donnees"
INDISPO = "INDISPONIBLE"
FENETRE = 30

# Critères du marquage "candidat" : volontairement explicites et modifiables.
SEUIL_RANG_VOLUME = 90  # volume d'options >= 90e centile de son propre historique
MIN_JOURS_HISTORIQUE = 10  # en dessous, on ne qualifie pas un volume d'inhabituel
SEUIL_Z_PRIX = 1.0  # mouvement du cours < 1 écart-type de ses variations récentes
SEUIL_PART_OI_ZERO = 0.5  # au-delà de 50 % de contrats à open interest 0 (jour ou veille), variation d'OI non fiable


def num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def charger(f):
    return json.loads(f.read_text(encoding="utf-8"))


def volume_options(tk_data):
    o = (tk_data or {}).get("options", {})
    c, p = num(o.get("volume_calls")), num(o.get("volume_puts"))
    return (c + p if c is not None and p is not None else None), c, p


def stats_historique(valeur, historique):
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
    if len(historique) >= 5 and st.pstdev(historique) > 0:
        res["z_score"] = round((valeur - st.mean(historique)) / st.pstdev(historique), 2)
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


def variation_oi(jour_opts, veille_opts):
    prec = {c["symbole"]: num(c.get("open_interest")) for c in veille_opts.get("contrats", [])}
    lignes, delta = [], {"call": 0, "put": 0}
    compares = nouveaux = 0
    for c in jour_opts.get("contrats", []):
        oi = num(c.get("open_interest"))
        oi_veille = prec.get(c["symbole"])
        d = oi - oi_veille if oi is not None and oi_veille is not None else None
        if c["symbole"] not in prec:
            nouveaux += 1
        if d is not None:
            compares += 1
            delta[c["type"]] += d
        lignes.append(
            {
                **c,
                "open_interest_veille": oi_veille if oi_veille is not None else INDISPO,
                "delta_open_interest": d if d is not None else INDISPO,
            }
        )

    def cle_vol(x):
        return num(x["volume"]) or 0

    top_volume = sorted(lignes, key=cle_vol, reverse=True)[:5]
    top_delta = sorted(
        [x for x in lignes if num(x["delta_open_interest"]) is not None],
        key=lambda x: abs(x["delta_open_interest"]),
        reverse=True,
    )[:5]
    for x in top_volume:
        v, ov = num(x["volume"]), num(x["open_interest_veille"])
        x["volume_sur_oi_veille"] = round(v / ov, 2) if v is not None and ov else INDISPO
    return {
        "contrats_compares": compares,
        "contrats_absents_la_veille": nouveaux,
        "delta_total_calls": delta["call"],
        "delta_total_puts": delta["put"],
        "strikes_les_plus_actifs": top_volume,
        "plus_fortes_variations_oi": top_delta,
        "note": "Comparaison contrat par contrat (même symbole), pas strike le plus actif contre strike le plus actif. "
        "Yahoo publie souvent l'open interest avec un jour de retard.",
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
    res["volume_options"] = stats_historique(tot, hist_vol)
    res["volume_options"].update(calls=c if c is not None else INDISPO, puts=pu if pu is not None else INDISPO)
    ratio = round(c / pu, 3) if c is not None and pu else None
    res["ratio_calls_puts"] = stats_historique(ratio, [round(r, 3) for r in hist_ratio])

    n = len(hist_vol)
    res["fiabilite_historique"] = "insuffisante" if n < MIN_JOURS_HISTORIQUE else "partielle" if n < 20 else "correcte"

    # Variation d'open interest contre la veille
    tv = veille["tickers"].get(tk) if veille else None
    seance_veille = (tv or {}).get("cours", {}).get("date_seance")
    if not tv:
        res["open_interest"] = {"statut": "pas de collecte de la veille pour ce ticker"}
    elif seance_veille == seance:
        res["open_interest"] = {"statut": "même séance que la veille (jour férié ou relance) : variation non mesurable"}
    elif opts.get("statut") == INDISPO or tv.get("options", {}).get("statut") == INDISPO:
        res["open_interest"] = {"statut": INDISPO}
    else:
        res["open_interest"] = variation_oi(opts, tv["options"])

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

    # Marquage candidat selon des critères fixes et affichés
    vo, oi, mv = res["volume_options"], res["open_interest"], res["cours"]
    if n < MIN_JOURS_HISTORIQUE:
        candidat = "NON EVALUABLE"
        res["avertissements"].append(f"historique de {n} séances : trop court pour qualifier un volume d'inhabituel")
    elif oi.get("fiabilite") == "non fiable":
        candidat = "NON EVALUABLE"
    elif num(vo.get("rang_percentile")) is None or "delta_total_calls" not in oi:
        candidat = "NON EVALUABLE"
        res["avertissements"].append("volume d'options ou variation d'open interest non mesurable aujourd'hui")
    else:
        delta_oi = oi["delta_total_calls"] + oi["delta_total_puts"]
        z = num(mv.get("z_score_mouvement"))
        candidat = vo["rang_percentile"] >= SEUIL_RANG_VOLUME and delta_oi > 0 and z is not None and abs(z) < SEUIL_Z_PRIX
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
    precedents = [charger(f) for f in fichiers[max(0, i - FENETRE) : i]]
    veille = precedents[-1] if precedents else None

    sortie = {
        "date": jour["date_collecte"],
        "fichier_jour": fichiers[i].name,
        "fichier_veille": fichiers[i - 1].name if veille else INDISPO,
        "criteres_candidat": {
            "rang_percentile_volume_options_min": SEUIL_RANG_VOLUME,
            "jours_historique_min": MIN_JOURS_HISTORIQUE,
            "delta_open_interest_total": "> 0",
            "z_score_mouvement_cours_max_absolu": SEUIL_Z_PRIX,
            "part_contrats_oi_zero_max": SEUIL_PART_OI_ZERO,
        },
        "tickers": {},
    }
    for tk, d in jour["tickers"].items():
        d["_date_collecte"] = jour["date_collecte"]
        sortie["tickers"][tk] = analyser(tk, d, veille, precedents)

    f = DOSSIER / f"comparaison-{jour['date_collecte']}.json"
    f.write_text(json.dumps(sortie, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"Fichier : {f.relative_to(RACINE)}")
    for tk, r in sortie["tickers"].items():
        print(f"  {tk} : historique {r['fiabilite_historique']}, candidat = {r['candidat']}")


if __name__ == "__main__":
    main()
