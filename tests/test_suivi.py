import csv
import json
from datetime import date, timedelta

import pytest

import suivi

J0 = date(2026, 8, 3)  # lundi
PRIX = {"AAPL": (100.0, 110.0), "MSFT": (200.0, 202.0), "NVDA": (50.0, 45.0)}  # J0 puis J+14


def brut(projet, jour, seances, pendant_seance=False):
    """Fichier brut minimal : clôture linéaire de J0 à J+14 pour chaque ticker."""
    tickers = {}
    for tk, (debut, fin) in PRIX.items():
        hist = []
        for d in seances:
            k = (d - J0).days / 14
            hist.append({"date": d.isoformat(), "cloture": round(debut + (fin - debut) * k, 4), "volume": 1})
        tickers[tk] = {"cours": {"date_seance": seances[-1].isoformat(), "cloture": hist[-1]["cloture"], "historique_90j": hist}}
    data = {"date_collecte": jour.isoformat(), "collecte_pendant_seance": pendant_seance, "tickers": tickers}
    (projet / "donnees" / f"brut-{jour.isoformat()}.json").write_text(json.dumps(data), encoding="utf-8")


def ouvres(debut, fin):
    return [debut + timedelta(days=i) for i in range((fin - debut).days + 1) if (debut + timedelta(days=i)).weekday() < 5]


def signaler(projet, jour, *tickers):
    s = [
        {
            "ticker": tk,
            "ce_qui_est_inhabituel": "volume au 100e centile",
            "explication_banale_probable": "résultats",
            "confiance": "faible",
        }
        for tk in tickers
    ]
    (projet / "rapports" / f"signalements-{jour.isoformat()}.json").write_text(
        json.dumps({"date": jour.isoformat(), "signalements": s}), encoding="utf-8"
    )


def lancer(monkeypatch, *args):
    monkeypatch.setattr("sys.argv", ["suivi.py", *args])
    suivi.main()


def journal(projet):
    with (projet / "suivi" / "journal.csv").open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def test_ajout_lit_le_cours_dans_le_brut_et_ne_double_pas(projet, monkeypatch):
    brut(projet, J0, [J0])
    signaler(projet, J0, "AAPL")
    lancer(monkeypatch)
    lancer(monkeypatch)
    lignes = journal(projet)
    assert len(lignes) == 1
    assert lignes[0]["cours_au_signalement"] == "100.0"
    assert lignes[0]["date_seance"] == "2026-08-03"
    assert lignes[0]["cours_j+14"] == ""
    assert list(lignes[0]) == suivi.COLONNES


def test_ticker_invente_refuse_journal_inchange(projet, monkeypatch):
    brut(projet, J0, [J0])
    signaler(projet, J0, "AAPL", "GLOBEX")
    with pytest.raises(SystemExit, match="GLOBEX absent"):
        lancer(monkeypatch)
    assert not (projet / "suivi" / "journal.csv").exists()


def test_complete_j14_et_compare_aux_temoins(projet, monkeypatch):
    brut(projet, J0, [J0])
    signaler(projet, J0, "AAPL")
    lancer(monkeypatch)
    plus_tard = J0 + timedelta(days=15)
    brut(projet, plus_tard, ouvres(J0, plus_tard))
    lancer(monkeypatch)
    x = journal(projet)[0]
    assert x["date_j+14"] == "2026-08-17"
    assert x["cours_j+14"] == "110.0"
    assert x["variation_j+14_pct"] == "10.0"
    assert x["variation_abs_mediane_temoins_pct"] == "5.5"  # MSFT +1 %, NVDA -10 %
    assert x["nb_temoins"] == "2"


def test_j14_pas_encore_disponible(projet, monkeypatch):
    brut(projet, J0, [J0])
    signaler(projet, J0, "AAPL")
    lancer(monkeypatch)
    brut(projet, J0 + timedelta(days=7), ouvres(J0, J0 + timedelta(days=7)))
    lancer(monkeypatch)
    assert journal(projet)[0]["cours_j+14"] == ""


def test_collecte_pendant_seance_ignoree_pour_j14(projet, monkeypatch):
    brut(projet, J0, [J0])
    signaler(projet, J0, "AAPL")
    lancer(monkeypatch)
    plus_tard = J0 + timedelta(days=15)
    brut(projet, plus_tard, ouvres(J0, plus_tard), pendant_seance=True)
    lancer(monkeypatch)
    assert journal(projet)[0]["cours_j+14"] == ""


def test_ancien_journal_migre_sans_perte(projet, monkeypatch):
    f = projet / "suivi" / "journal.csv"
    f.write_text(
        '"date","ticker","cours_au_signalement","ce_qui_est_inhabituel","explication_banale_probable","confiance","cours_j+14","ce_qui_s_est_passe"\n'
        '"2026-07-01","MSFT","400","x","y","faible","410","rien"\n',
        encoding="utf-8",
    )
    brut(projet, J0, [J0])
    signaler(projet, J0, "AAPL")
    lancer(monkeypatch)
    lignes = journal(projet)
    assert [x["ticker"] for x in lignes] == ["MSFT", "AAPL"]
    assert lignes[0]["cours_j+14"] == "410" and lignes[0]["ce_qui_s_est_passe"] == "rien"


def test_bilan_decrit_sans_conclure(projet, monkeypatch, capsys):
    brut(projet, J0, [J0])
    signaler(projet, J0, "AAPL")
    lancer(monkeypatch)
    plus_tard = J0 + timedelta(days=15)
    brut(projet, plus_tard, ouvres(J0, plus_tard))
    lancer(monkeypatch)
    capsys.readouterr()
    lancer(monkeypatch, "bilan")
    sortie = capsys.readouterr().out
    assert "mouvement absolu médian à J+14 = 10.00 %" in sortie
    assert "témoins = 5.50 %" in sortie
    assert "ne permettent pas de conclusion" in sortie
