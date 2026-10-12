#!/usr/bin/env python3
"""Collecteur : récupère les données brutes de la watchlist. N'analyse rien.

Sortie : donnees/brut-AAAA-MM-JJ.json
Toute donnée manquante est écrite "INDISPONIBLE", jamais estimée.

Usage : python3 scripts/collect.py [--horizon 60] [--forcer]
  --horizon : n'enregistre que les échéances d'options à moins de N jours (défaut 60).
  --forcer  : collecte même pendant la séance américaine. Le fichier est alors marqué
              et compare.py l'exclut de l'historique (séance incomplète).
"""

import argparse
import json
import math
import sys
import time
from datetime import date, datetime, timedelta
from datetime import time as heure
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf

RACINE = Path(__file__).resolve().parent.parent
WATCHLIST = RACINE / "watchlist.txt"
DOSSIER = RACINE / "donnees"
INDISPO = "INDISPONIBLE"
SOURCE = f"Yahoo Finance via yfinance {yf.__version__} (non officiel, différé)"
PAUSE = 0.5  # secondes entre deux requêtes, pour ne pas se faire bloquer
NEW_YORK = ZoneInfo("America/New_York")
OUVERTURE, FERMETURE = heure(9, 30), heure(16, 0)  # séance américaine, heure de New York


def maintenant():
    return datetime.now().astimezone().isoformat(timespec="seconds")


def seance_en_cours(instant=None):
    """Vrai si la séance américaine est ouverte : les volumes du jour seraient partiels.

    Les jours fériés ne sont pas connus : un jour férié en semaine est vu comme ouvert.
    """
    t = (instant or datetime.now(NEW_YORK)).astimezone(NEW_YORK)
    return t.weekday() < 5 and OUVERTURE <= t.time() < FERMETURE


def nombre(v, entier=False):
    """Convertit en nombre, ou renvoie INDISPONIBLE."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return INDISPO
    if math.isnan(f) or math.isinf(f):
        return INDISPO
    return int(f) if entier else round(f, 4)


def lire_watchlist():
    if not WATCHLIST.exists():
        return []
    tickers = []
    for ligne in WATCHLIST.read_text(encoding="utf-8").splitlines():
        ligne = ligne.split("#", 1)[0].strip().upper()
        if ligne and ligne not in tickers:
            tickers.append(ligne)
    return tickers


def collecter_cours(t):
    res = {"source": SOURCE, "horodatage": maintenant()}
    try:
        h = t.history(period="6mo", interval="1d", auto_adjust=False)
    except Exception as e:
        res.update(statut=INDISPO, erreur=str(e))
        return res
    if h is None or h.empty or "Close" not in h:
        res["statut"] = INDISPO
        return res

    h = h.dropna(subset=["Close"])
    debut = h.index[-1] - pd.Timedelta(days=90)
    res["historique_90j"] = [
        {"date": i.strftime("%Y-%m-%d"), "cloture": nombre(r["Close"]), "volume": nombre(r["Volume"], entier=True)}
        for i, r in h[h.index >= debut].iterrows()
    ]

    dernier = h.iloc[-1]
    res["date_seance"] = h.index[-1].strftime("%Y-%m-%d")
    res["cloture"] = nombre(dernier["Close"])
    res["volume"] = nombre(dernier["Volume"], entier=True)
    res["variation_pct"] = nombre((dernier["Close"] / h["Close"].iloc[-2] - 1) * 100) if len(h) >= 2 else INDISPO

    vol30 = h["Volume"].iloc[-31:-1].dropna()
    res["volume_moyen_30_seances"] = nombre(vol30.mean()) if len(vol30) else INDISPO
    res["nb_seances_moyenne"] = len(vol30)
    vol, moy = res["volume"], res["volume_moyen_30_seances"]
    if isinstance(vol, int) and isinstance(moy, float) and moy > 0:
        res["ratio_volume_vs_moyenne_30"] = nombre(vol / moy)
    else:
        res["ratio_volume_vs_moyenne_30"] = INDISPO
    return res


def collecter_options(t, horizon_jours, aujourdhui=None):
    aujourdhui = aujourdhui or date.today()
    res = {"source": SOURCE, "horodatage": maintenant()}
    try:
        echeances = list(t.options)
    except Exception as e:
        res.update(statut=INDISPO, erreur=str(e))
        return res
    if not echeances:
        res.update(statut=INDISPO, erreur="aucune échéance d'option renvoyée par la source")
        return res

    limite = aujourdhui + timedelta(days=horizon_jours)
    retenues = [e for e in echeances if date.fromisoformat(e) <= limite] or echeances[:1]
    res["echeances_retenues"] = retenues
    res["echeances_en_echec"] = []

    contrats = []
    for e in retenues:
        try:
            chaine = t.option_chain(e)
        except Exception as ex:
            res["echeances_en_echec"].append({"echeance": e, "erreur": str(ex)})
            continue
        for type_, df in (("call", chaine.calls), ("put", chaine.puts)):
            for _, r in df.iterrows():
                dernier = r.get("lastTradeDate")
                contrats.append(
                    {
                        "symbole": r.get("contractSymbol", INDISPO),
                        "type": type_,
                        "echeance": e,
                        "strike": nombre(r.get("strike")),
                        "volume": nombre(r.get("volume"), entier=True),
                        "open_interest": nombre(r.get("openInterest"), entier=True),
                        "dernier_echange": str(dernier) if dernier is not None and not pd.isna(dernier) else INDISPO,
                    }
                )
        time.sleep(PAUSE)

    res["contrats"] = contrats
    for type_ in ("call", "put"):
        vols = [c["volume"] for c in contrats if c["type"] == type_ and isinstance(c["volume"], int)]
        ois = [c["open_interest"] for c in contrats if c["type"] == type_ and isinstance(c["open_interest"], int)]
        res[f"volume_{type_}s"] = sum(vols) if vols else INDISPO
        res[f"open_interest_{type_}s"] = sum(ois) if ois else INDISPO
    res["contrats_sans_volume"] = sum(1 for c in contrats if c["volume"] == INDISPO)
    res["note"] = (
        "Le volume des contrats est sommé sur les échéances retenues uniquement. "
        "Un volume INDISPONIBLE signifie en général aucun échange sur ce contrat."
    )
    return res


def en_date(v):
    try:
        return pd.Timestamp(v).date()
    except (TypeError, ValueError):
        return None


def collecter_evenements(t, jours=30, aujourdhui=None):
    res = {"source": SOURCE, "horodatage": maintenant(), "evenements": []}
    try:
        cal = t.calendar
    except Exception as e:
        res.update(statut=INDISPO, erreur=str(e))
        return res
    if not isinstance(cal, dict) or not cal:
        res["statut"] = INDISPO
        return res

    aujourdhui = aujourdhui or date.today()
    limite = aujourdhui + timedelta(days=jours)
    for cle, libelle in (
        ("Earnings Date", "resultats"),
        ("Ex-Dividend Date", "detachement_dividende"),
        ("Dividend Date", "paiement_dividende"),
    ):
        valeurs = cal.get(cle)
        if valeurs is None:
            continue
        for v in valeurs if isinstance(valeurs, list) else [valeurs]:
            d = en_date(v)
            if d and aujourdhui <= d <= limite:
                res["evenements"].append({"type": libelle, "date": d.isoformat()})
    res["calendrier_brut"] = {k: str(v) for k, v in cal.items()}
    res["note"] = "Absence d'événement dans la source ne prouve pas l'absence d'événement : à vérifier sur le site de l'émetteur."
    return res


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--horizon", type=int, default=60)
    p.add_argument("--forcer", action="store_true", help="collecter même pendant la séance américaine")
    args = p.parse_args()

    en_seance = seance_en_cours()
    if en_seance and not args.forcer:
        sys.exit(
            "La séance américaine est ouverte (9 h 30 – 16 h, heure de New York) : les volumes du jour seraient partiels. "
            "Relance après la clôture ou demain matin. Jour férié aux États-Unis ? Relance avec --forcer."
        )

    tickers = lire_watchlist()
    print(f"vigie-options : collecte de {len(tickers)} ticker(s)", file=sys.stderr)
    if not tickers:
        sys.exit("watchlist.txt est vide ou absent : ajoute un ticker par ligne (ex. AAPL).")

    DOSSIER.mkdir(exist_ok=True)
    jour = date.today().isoformat()
    donnees = {
        "date_collecte": jour,
        "horodatage_debut": maintenant(),
        "source": SOURCE,
        "horizon_echeances_jours": args.horizon,
        "collecte_pendant_seance": en_seance,
        "tickers": {},
    }

    for tk in tickers:
        print(f"Collecte {tk}...", file=sys.stderr)
        t = yf.Ticker(tk)
        donnees["tickers"][tk] = {
            "cours": collecter_cours(t),
            "options": collecter_options(t, args.horizon),
            "evenements": collecter_evenements(t),
        }
        time.sleep(PAUSE)

    donnees["horodatage_fin"] = maintenant()
    sortie = DOSSIER / f"brut-{jour}.json"
    sortie.write_text(json.dumps(donnees, ensure_ascii=False, indent=1, default=str), encoding="utf-8")

    print(f"Fichier : {sortie.relative_to(RACINE)}")
    if en_seance:
        print("  ATTENTION : collecte pendant la séance, fichier exclu de l'historique par compare.py")
    for tk, d in donnees["tickers"].items():
        manquants = [bloc for bloc in ("cours", "options", "evenements") if d[bloc].get("statut") == INDISPO]
        seance = d["cours"].get("date_seance", INDISPO)
        print(f"  {tk} : séance {seance}" + (f" | INDISPONIBLE : {', '.join(manquants)}" if manquants else ""))


if __name__ == "__main__":
    main()
