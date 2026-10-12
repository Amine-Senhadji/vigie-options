#!/usr/bin/env python3
"""Journal de suivi des signalements : écrit et complété par Python, jamais par un agent.

La vigie dépose ses signalements dans rapports/signalements-AAAA-MM-JJ.json ; ce script
les ajoute à suivi/journal.csv, avec le cours de clôture lu dans le fichier brut,
puis complète le cours à J+14 de chaque signalement dès qu'il est disponible.
Chaque signalement est comparé à des témoins : les autres tickers de la watchlist,
non signalés ce jour-là, sur la même période.

Usage :
  python3 scripts/suivi.py [AAAA-MM-JJ]   ajoute les signalements du jour et complète les J+14
  python3 scripts/suivi.py bilan          résume le journal, sans conclure
"""

import csv
import json
import os
import statistics as st
import sys
from datetime import date, timedelta
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
DONNEES = RACINE / "donnees"
RAPPORTS = RACINE / "rapports"
JOURNAL = RACINE / "suivi" / "journal.csv"
INDISPO = "INDISPONIBLE"
HORIZON_JOURS = 14  # jours calendaires ; on retient la première séance à partir de J+14

COLONNES = [
    "date",
    "ticker",
    "date_seance",
    "cours_au_signalement",
    "ce_qui_est_inhabituel",
    "explication_banale_probable",
    "confiance",
    "date_j+14",
    "cours_j+14",
    "variation_j+14_pct",
    "variation_abs_mediane_temoins_pct",
    "nb_temoins",
    "ce_qui_s_est_passe",
]
CHAMPS_SIGNALEMENT = ["ticker", "ce_qui_est_inhabituel", "explication_banale_probable", "confiance"]


def num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def charger(f):
    return json.loads(f.read_text(encoding="utf-8"))


def lire_journal():
    if not JOURNAL.exists():
        return []
    with JOURNAL.open(encoding="utf-8", newline="") as f:
        # Les colonnes absentes d'un ancien journal sont ajoutées vides ; aucune ligne n'est perdue
        return [{c: ligne.get(c) or "" for c in COLONNES} for ligne in csv.DictReader(f)]


def ecrire_journal(lignes):
    JOURNAL.parent.mkdir(exist_ok=True)
    tmp = JOURNAL.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLONNES, quoting=csv.QUOTE_ALL)
        w.writeheader()
        w.writerows(lignes)
    os.replace(tmp, JOURNAL)  # écriture atomique : un plantage ne corrompt pas le journal


def clotures():
    """Clôtures connues par ticker et par date, lues dans tous les fichiers bruts complets."""
    res = {}
    for f in sorted(DONNEES.glob("brut-*.json")):
        d = charger(f)
        if d.get("collecte_pendant_seance"):
            continue  # dernière barre incomplète
        for tk, t in d.get("tickers", {}).items():
            for x in t.get("cours", {}).get("historique_90j", []):
                c = num(x.get("cloture"))
                if c is not None:
                    res.setdefault(tk, {})[x["date"]] = c
    return res


def cloture_a_partir_de(serie, jour_min):
    dates = sorted(d for d in serie if d >= jour_min)
    return (dates[0], serie[dates[0]]) if dates else None


def variation(serie, depart, jour_min):
    c0, fin = serie.get(depart), cloture_a_partir_de(serie, jour_min)
    if c0 is None or fin is None or c0 == 0:
        return None
    return round((fin[1] / c0 - 1) * 100, 2)


def ajouter(jour, lignes):
    f = RAPPORTS / f"signalements-{jour}.json"
    if not f.exists():
        print(f"Aucun fichier {f.name} : rien à ajouter.")
        return 0
    signalements = charger(f).get("signalements", [])
    brut_f = DONNEES / f"brut-{jour}.json"
    if not brut_f.exists():
        sys.exit(f"{brut_f.name} introuvable : impossible de lire le cours au signalement.")
    brut = charger(brut_f)

    erreurs = []
    for i, s in enumerate(signalements):
        manquants = [c for c in CHAMPS_SIGNALEMENT if not str(s.get(c, "")).strip()]
        if manquants:
            erreurs.append(f"signalement {i + 1} : champ(s) manquant(s) {', '.join(manquants)}")
        elif s["ticker"] not in brut["tickers"]:
            erreurs.append(f"signalement {i + 1} : {s['ticker']} absent des données collectées le {jour}")
    if erreurs:
        sys.exit(f"{f.name} refusé, journal inchangé :\n  " + "\n  ".join(erreurs))

    deja = {(x["date"], x["ticker"]) for x in lignes}
    ajoutes = 0
    for s in signalements:
        tk = s["ticker"]
        if (jour, tk) in deja:
            continue
        cours = brut["tickers"][tk].get("cours", {})
        cloture = num(cours.get("cloture"))
        lignes.append(
            {
                **dict.fromkeys(COLONNES, ""),
                "date": jour,
                "ticker": tk,
                "date_seance": cours.get("date_seance", INDISPO),
                "cours_au_signalement": cloture if cloture is not None else INDISPO,
                **{c: str(s[c]).strip() for c in CHAMPS_SIGNALEMENT[1:]},
            }
        )
        deja.add((jour, tk))
        ajoutes += 1
    return ajoutes


def completer(lignes):
    """Remplit cours et variation à J+14, et la variation absolue médiane des témoins."""
    series = clotures()
    signales = {}
    for x in lignes:
        signales.setdefault(x["date"], set()).add(x["ticker"])

    completes = 0
    for x in lignes:
        if x["cours_j+14"] or x["date_seance"] in ("", INDISPO):
            continue
        jour_min = (date.fromisoformat(x["date_seance"]) + timedelta(days=HORIZON_JOURS)).isoformat()
        fin = cloture_a_partir_de(series.get(x["ticker"], {}), jour_min)
        if fin is None:
            continue  # pas encore disponible
        x["date_j+14"], x["cours_j+14"] = fin
        c0 = num(x["cours_au_signalement"])
        x["variation_j+14_pct"] = round((fin[1] / c0 - 1) * 100, 2) if c0 else INDISPO

        brut_f = DONNEES / f"brut-{x['date']}.json"
        temoins = set(charger(brut_f)["tickers"]) - signales[x["date"]] if brut_f.exists() else set()
        vars_t = [v for tk in sorted(temoins) if (v := variation(series.get(tk, {}), x["date_seance"], jour_min)) is not None]
        x["variation_abs_mediane_temoins_pct"] = round(st.median(abs(v) for v in vars_t), 2) if vars_t else INDISPO
        x["nb_temoins"] = len(vars_t)
        completes += 1
    return completes


def bilan(lignes):
    mesures = [
        (x, abs(num(x["variation_j+14_pct"])), num(x["variation_abs_mediane_temoins_pct"]))
        for x in lignes
        if num(x["variation_j+14_pct"]) is not None
    ]
    print(f"Journal : {len(lignes)} signalement(s), {len(mesures)} avec un cours à J+{HORIZON_JOURS}.")
    if not mesures:
        print("Rien à résumer pour l'instant.")
        return
    avec_temoins = [(x, v, t) for x, v, t in mesures if t is not None]

    def resume(groupe, nom):
        vs = [v for _, v, _ in groupe]
        ligne = f"  {nom} : n = {len(vs)}, mouvement absolu médian à J+{HORIZON_JOURS} = {st.median(vs):.2f} %"
        g = [(v, t) for _, v, t in groupe if t is not None]
        if g:
            ligne += (
                f", témoins = {st.median(t for _, t in g):.2f} %"
                f", signalements au-dessus de leurs témoins = {sum(v > t for v, t in g)}/{len(g)}"
            )
        print(ligne)

    resume(mesures, "tous")
    for conf in sorted({x["confiance"] for x, _, _ in mesures}):
        resume([m for m in mesures if m[0]["confiance"] == conf], f"confiance {conf}")
    if len(avec_temoins) < 30:
        print(
            f"Moins de 30 signalements comparés à des témoins ({len(avec_temoins)}) : "
            "ces chiffres ne permettent pas de conclusion."
        )
    print(
        "Mouvement absolu, pas direction : un signalement ne dit pas dans quel sens le cours bougera. "
        "Ce bilan décrit le journal, il ne mesure pas un gain."
    )


def main():
    args = sys.argv[1:]
    lignes = lire_journal()
    if args[:1] == ["bilan"]:
        bilan(lignes)
        return
    if args:
        jour = args[0]
    else:
        fichiers = sorted(RAPPORTS.glob("signalements-*.json"))
        jour = fichiers[-1].stem.removeprefix("signalements-") if fichiers else None
    ajoutes = ajouter(jour, lignes) if jour else 0
    completes = completer(lignes)
    if ajoutes or completes or not JOURNAL.exists():
        ecrire_journal(lignes)
    print(f"Journal : {JOURNAL.relative_to(RACINE)}")
    print(f"  {ajoutes} signalement(s) ajouté(s), {completes} complété(s) à J+{HORIZON_JOURS}")


if __name__ == "__main__":
    main()
