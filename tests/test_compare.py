import json
from datetime import timedelta

import pytest

import compare
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


def modifier(dossier, jour, fonction):
    f = dossier / f"brut-{jour.isoformat()}.json"
    data = json.loads(f.read_text(encoding="utf-8"))
    fonction(data)
    f.write_text(json.dumps(data), encoding="utf-8")


def contrats(data, tk="AAPL"):
    return data["tickers"][tk]["options"]["contrats"]


def test_ouverture_hors_des_strikes_actifs_ne_suffit_pas(dossier, debut, monkeypatch):
    jours = jours_ouvres(debut, 15)
    for j in jours:
        ecrire_jour(dossier, j, ["AAPL"], choc={"AAPL"} if j == jours[-1] else ())
    veille = {c["symbole"]: c for c in contrats(json.loads((dossier / f"brut-{jours[-2]}.json").read_text()))}

    def fermer_les_actifs(data):
        actifs = sorted(contrats(data), key=lambda c: c["volume"] if isinstance(c["volume"], int) else 0)[-5:]
        for c in actifs:
            c["open_interest"] = veille[c["symbole"]]["open_interest"] - 10

    modifier(dossier, jours[-1], fermer_les_actifs)
    lancer_compare(monkeypatch)
    r = resultat(dossier, jours[-1])["tickers"]["AAPL"]
    assert r["open_interest"]["delta_total_calls"] + r["open_interest"]["delta_total_puts"] > 0
    assert r["open_interest"]["strikes_actifs"]["delta_open_interest"] == -50
    assert r["candidat"] is False


def test_open_interest_fige_non_fiable(dossier, debut, monkeypatch):
    monkeypatch.setattr(compare, "MIN_CONTRATS_CONTROLE", 5)
    jours = jours_ouvres(debut, 15)
    for j in jours:
        ecrire_jour(dossier, j, ["AAPL"], choc={"AAPL"} if j == jours[-1] else ())
    veille = {c["symbole"]: c["open_interest"] for c in contrats(json.loads((dossier / f"brut-{jours[-2]}.json").read_text()))}

    def figer(data):
        for c in contrats(data):
            c["open_interest"] = veille[c["symbole"]]

    modifier(dossier, jours[-1], figer)
    lancer_compare(monkeypatch)
    r = resultat(dossier, jours[-1])["tickers"]["AAPL"]
    assert r["open_interest"]["part_oi_inchange_sur_contrats_echanges"] == 1.0
    assert r["open_interest"]["fiabilite"] == "non fiable"
    assert r["candidat"] == "NON EVALUABLE"


def test_open_interest_qui_suit_le_volume_de_la_veille(dossier, debut, monkeypatch):
    jours = jours_ouvres(debut, 15)
    for j in jours:
        ecrire_jour(dossier, j, ["AAPL"])
    veille = {c["symbole"]: c for c in contrats(json.loads((dossier / f"brut-{jours[-2]}.json").read_text()))}

    def decaler(data):
        for c in contrats(data):
            v = veille[c["symbole"]]
            vol_veille = v["volume"] if isinstance(v["volume"], int) else 0
            c["open_interest"] = v["open_interest"] + vol_veille
            c["volume"] = 5 if vol_veille else 500  # volume du jour sans rapport avec la variation d'OI

    modifier(dossier, jours[-1], decaler)
    lancer_compare(monkeypatch)
    r = resultat(dossier, jours[-1])["tickers"]["AAPL"]
    al = r["open_interest"]["alignement_volume"]
    assert al["correlation_avec_volume_de_la_veille"] == 1.0
    assert al["correlation_avec_volume_du_jour"] < 0
    assert any("séance précédente" in a for a in r["avertissements"])


def test_echeance_entree_dans_la_fenetre_signalee(dossier, debut, monkeypatch):
    jours = jours_ouvres(debut, 2)
    for j in jours:
        ecrire_jour(dossier, j, ["AAPL"])

    def retirer(data):
        o = data["tickers"]["AAPL"]["options"]
        o["echeances_retenues"].remove("2026-09-18")
        o["contrats"] = [c for c in o["contrats"] if c["echeance"] != "2026-09-18"]

    modifier(dossier, jours[0], retirer)
    lancer_compare(monkeypatch)
    r = resultat(dossier, jours[-1])["tickers"]["AAPL"]
    jour = json.loads((dossier / f"brut-{jours[-1]}.json").read_text())
    attendu = sum(c["volume"] for c in contrats(jour) if c["echeance"] == "2026-09-18" and isinstance(c["volume"], int))
    assert r["echeances"]["entrees_dans_la_fenetre"] == ["2026-09-18"]
    assert r["echeances"]["volume_echeances_entrees"] == attendu
    assert any("entrée(s) dans la fenêtre" in a for a in r["avertissements"])


def test_troisieme_vendredi():
    assert compare.troisieme_vendredi("2026-09-18") is True
    assert compare.troisieme_vendredi("2026-09-11") is False
    assert compare.troisieme_vendredi("2026-09-25") is False
    assert compare.troisieme_vendredi("INDISPONIBLE") is False


def test_collecte_pendant_seance_exclue_de_l_historique(dossier, debut, monkeypatch):
    jours = jours_ouvres(debut, 15)
    for j in jours:
        ecrire_jour(dossier, j, ["AAPL"])
    modifier(dossier, jours[-2], lambda d: d.update(collecte_pendant_seance=True))
    lancer_compare(monkeypatch)
    sortie = resultat(dossier, jours[-1])
    assert sortie["fichiers_exclus_collecte_pendant_seance"] == [f"brut-{jours[-2]}.json"]
    assert sortie["fichier_veille"] == f"brut-{jours[-3]}.json"
    assert sortie["tickers"]["AAPL"]["volume_options"]["nb_jours"] == 13


def test_jour_collecte_pendant_seance_non_evaluable(dossier, debut, monkeypatch):
    jours = jours_ouvres(debut, 15)
    for j in jours:
        ecrire_jour(dossier, j, ["AAPL"], choc={"AAPL"} if j == jours[-1] else ())
    modifier(dossier, jours[-1], lambda d: d.update(collecte_pendant_seance=True))
    lancer_compare(monkeypatch)
    r = resultat(dossier, jours[-1])["tickers"]["AAPL"]
    assert r["candidat"] == "NON EVALUABLE"
    assert "pendant la séance" in r["avertissements"][0]
