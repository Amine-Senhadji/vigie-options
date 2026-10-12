import json
from datetime import timedelta

import pytest

from conftest import ecrire_jour, jours_ouvres, lancer_compare


def resultat(dossier, jour):
    return json.loads((dossier / f"comparaison-{jour.isoformat()}.json").read_text(encoding="utf-8"))


def test_historique_trop_court_non_evaluable(dossier, debut, monkeypatch):
    jours = jours_ouvres(debut, 5)
    for j in jours:
        ecrire_jour(dossier, j, ["AAPL"], choc={"AAPL"} if j == jours[-1] else ())
    lancer_compare(monkeypatch)
    r = resultat(dossier, jours[-1])["tickers"]["AAPL"]
    assert r["fiabilite_historique"] == "insuffisante"
    assert r["candidat"] == "NON EVALUABLE"


def test_choc_de_volume_avec_ouverture_de_positions_est_candidat(dossier, debut, monkeypatch):
    jours = jours_ouvres(debut, 15)
    for j in jours:
        ecrire_jour(dossier, j, ["AAPL", "MSFT"], choc={"AAPL"} if j == jours[-1] else ())
    lancer_compare(monkeypatch)
    t = resultat(dossier, jours[-1])["tickers"]
    assert t["AAPL"]["volume_options"]["rang_percentile"] == 100.0
    assert t["AAPL"]["open_interest"]["delta_total_calls"] > 0
    assert t["AAPL"]["candidat"] is True


def test_gros_mouvement_du_cours_n_est_pas_candidat(dossier, debut, monkeypatch):
    jours = jours_ouvres(debut, 15)
    for j in jours:
        dernier = j == jours[-1]
        ecrire_jour(dossier, j, ["AAPL"], choc={"AAPL"} if dernier else (), mouvement=0.15 if dernier else 0.0)
    lancer_compare(monkeypatch)
    assert resultat(dossier, jours[-1])["tickers"]["AAPL"]["candidat"] is False


def test_open_interest_compare_contrat_par_contrat(dossier, debut, monkeypatch):
    jours = jours_ouvres(debut, 2)
    for j in jours:
        ecrire_jour(dossier, j, ["AAPL"], choc={"AAPL"} if j == jours[-1] else ())
    lancer_compare(monkeypatch)
    oi = resultat(dossier, jours[-1])["tickers"]["AAPL"]["open_interest"]
    assert oi["contrats_compares"] == 12
    for c in oi["strikes_les_plus_actifs"]:
        assert c["delta_open_interest"] == c["open_interest"] - c["open_interest_veille"]


def test_meme_seance_que_la_veille_pas_de_variation(dossier, debut, monkeypatch):
    vendredi = jours_ouvres(debut, 5)[-1]
    samedi = vendredi + timedelta(days=1)
    ecrire_jour(dossier, vendredi, ["AAPL"])
    ecrire_jour(dossier, samedi, ["AAPL"])  # week-end : même dernière séance
    lancer_compare(monkeypatch)
    r = resultat(dossier, samedi)["tickers"]["AAPL"]
    assert "même séance" in r["open_interest"]["statut"]
    assert r["volume_options"]["nb_jours"] == 0


@pytest.mark.parametrize("jour_vide", ["jour", "veille"])
def test_open_interest_majoritairement_a_zero_non_fiable(dossier, debut, monkeypatch, jour_vide):
    jours = jours_ouvres(debut, 15)
    for j in jours:
        ecrire_jour(dossier, j, ["AAPL"], choc={"AAPL"} if j == jours[-1] else ())
    cible = dossier / f"brut-{(jours[-1] if jour_vide == 'jour' else jours[-2]).isoformat()}.json"
    data = json.loads(cible.read_text(encoding="utf-8"))
    for c in data["tickers"]["AAPL"]["options"]["contrats"][:10]:  # 10 contrats sur 12 à 0
        c["open_interest"] = 0
    cible.write_text(json.dumps(data), encoding="utf-8")
    lancer_compare(monkeypatch)
    r = resultat(dossier, jours[-1])["tickers"]["AAPL"]
    assert r["qualite_open_interest"][f"part_oi_zero_{jour_vide}"] == 0.8333
    assert r["open_interest"]["fiabilite"] == "non fiable"
    assert f"{jour_vide} : 83%" in r["open_interest"]["raison"]
    assert r["candidat"] == "NON EVALUABLE"
