import json
import math
import statistics
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


def test_seances_consecutives_et_week_end_aucune_seance_manquante(dossier, debut, monkeypatch):
    jours = jours_ouvres(debut, 6)  # du lundi au lundi suivant
    for j in jours:
        ecrire_jour(dossier, j, ["AAPL"])
    lancer_compare(monkeypatch)
    r = resultat(dossier, jours[-1])["tickers"]["AAPL"]
    assert r["seances_manquantes"] == {
        "seance_veille": jours[-2].isoformat(),  # vendredi : le week-end n'est pas une séance
        "nb": 0,
        "dates": [],
        "decompte_minimal": False,
    }
    assert not any("manquantes" in a.lower() for a in r["avertissements"])


def test_seances_manquantes_entre_la_veille_et_le_jour(dossier, debut, monkeypatch, capsys):
    jours = jours_ouvres(debut, 11)  # dernier jour : lundi 17 août
    sautes = jours[-3:-1]  # jeudi 13 et vendredi 14 : aucune collecte
    for j in jours:
        if j not in sautes:
            ecrire_jour(dossier, j, ["AAPL"])
    lancer_compare(monkeypatch)
    r = resultat(dossier, jours[-1])["tickers"]["AAPL"]
    assert r["seances_manquantes"] == {
        "seance_veille": "2026-08-12",
        "nb": 2,
        "dates": ["2026-08-13", "2026-08-14"],
        "decompte_minimal": False,
    }
    alerte = next(a for a in r["avertissements"] if a.startswith("SÉANCES MANQUANTES"))
    assert "2 séance(s) de bourse sans collecte exploitable entre la veille (2026-08-12) et le jour (2026-08-17)" in alerte
    assert "2026-08-13, 2026-08-14" in alerte
    assert "couvre 3 séances" in alerte
    assert "ATTENTION : 2 séance(s) manquante(s) depuis la veille (2026-08-13, 2026-08-14)" in capsys.readouterr().out


def test_collecte_pendant_seance_exclue_compte_comme_seance_manquante(dossier, debut, monkeypatch):
    jours = jours_ouvres(debut, 4)
    for j in jours:
        ecrire_jour(dossier, j, ["AAPL"])
    modifier(dossier, jours[-2], lambda d: d.update(collecte_pendant_seance=True))
    lancer_compare(monkeypatch)
    r = resultat(dossier, jours[-1])["tickers"]["AAPL"]
    assert r["seances_manquantes"]["dates"] == [jours[-2].isoformat()]
    assert any(a.startswith("SÉANCES MANQUANTES") for a in r["avertissements"])


def test_meme_seance_que_la_veille_aucune_seance_manquante(dossier, debut, monkeypatch):
    vendredi = jours_ouvres(debut, 5)[-1]
    ecrire_jour(dossier, vendredi, ["AAPL"])
    ecrire_jour(dossier, vendredi + timedelta(days=1), ["AAPL"])
    lancer_compare(monkeypatch)
    r = resultat(dossier, vendredi + timedelta(days=1))["tickers"]["AAPL"]
    assert r["seances_manquantes"]["nb"] == 0
    assert not any("manquantes" in a.lower() for a in r["avertissements"])


def test_seances_manquantes_jamais_estimees():
    cours = {"historique_90j": [{"date": d} for d in ("2026-08-10", "2026-08-11", "2026-08-12")]}
    # Sans calendrier des séances ou sans date de veille : INDISPONIBLE, pas de décompte en jours ouvrés
    assert compare.seances_manquantes({}, "2026-08-12", "2026-08-10") == {"statut": "INDISPONIBLE"}
    assert compare.seances_manquantes(cours, "INDISPONIBLE", "2026-08-10") == {"statut": "INDISPONIBLE"}
    assert compare.seances_manquantes(cours, "2026-08-12", None) == {"statut": "INDISPONIBLE"}
    # Veille plus ancienne que l'historique des cours : le décompte est un minimum, et il le dit
    r = compare.seances_manquantes(cours, "2026-08-12", "2026-03-02")
    assert (r["nb"], r["decompte_minimal"]) == (2, True)


def test_premiere_collecte_pas_de_veille(dossier, debut, monkeypatch):
    ecrire_jour(dossier, debut, ["AAPL"])
    lancer_compare(monkeypatch)
    r = resultat(dossier, debut)["tickers"]["AAPL"]
    assert "pas de collecte de la veille" in r["seances_manquantes"]["statut"]
    assert not any("manquantes" in a.lower() for a in r["avertissements"])


def test_dernier_echange_date_a_l_heure_de_new_york():
    def contrat(dernier, volume=40):
        return {"volume": volume, "dernier_echange": dernier}

    assert compare.volume_seance(contrat("2026-08-20 19:59:00+00:00"), "2026-08-20") == 40  # 15 h 59 à New York
    assert compare.volume_seance(contrat("2026-08-21 00:10:00+00:00"), "2026-08-20") == 40  # 20 h 10 à New York, le 20
    assert compare.volume_seance(contrat("2026-08-21 00:10:00+00:00"), "2026-08-21") == 0
    assert compare.volume_seance(contrat("2026-08-20 19:59:00"), "2026-08-20") == 40  # sans fuseau : UTC, comme Yahoo
    assert compare.volume_seance(contrat("2026-07-30 14:40:00+00:00"), "2026-08-20") == 0  # volume d'une séance passée
    assert compare.volume_seance(contrat("INDISPONIBLE"), "2026-08-20") == 0  # date inconnue : pas compté
    assert compare.volume_seance(contrat("2026-08-20 19:59:00+00:00", volume="INDISPONIBLE"), "2026-08-20") is None


def vieillir(data, nb, dernier="2026-07-30 14:40:00+00:00", volume=None):
    """Donne aux `nb` premiers contrats échangés un dernier échange ancien ; renvoie leur volume total."""
    cibles = [c for c in contrats(data) if isinstance(c["volume"], int)][:nb]
    for c in cibles:
        c["dernier_echange"] = dernier
        if volume is not None:
            c["volume"] = volume
    return sum(c["volume"] for c in cibles)


def test_volume_ancien_exclu_du_volume_du_jour(dossier, debut, monkeypatch):
    jours = jours_ouvres(debut, 2)
    for j in jours:
        ecrire_jour(dossier, j, ["AAPL"])
    brut = json.loads((dossier / f"brut-{jours[-1]}.json").read_text())
    total_affiche = brut["tickers"]["AAPL"]["options"]["volume_calls"] + brut["tickers"]["AAPL"]["options"]["volume_puts"]
    ecarte = {}
    modifier(dossier, jours[-1], lambda d: ecarte.update(volume=vieillir(d, 3)))
    lancer_compare(monkeypatch)
    vo = resultat(dossier, jours[-1])["tickers"]["AAPL"]["volume_options"]
    assert ecarte["volume"] > 0
    assert vo["jour"] == total_affiche - ecarte["volume"]
    assert vo["calls"] + vo["puts"] == vo["jour"]
    assert vo["volume_ancien_ecarte"] == ecarte["volume"]
    assert vo["contrats_au_volume_ancien"] == 3
    assert vo["contrats_au_dernier_echange_inconnu"] == 0


def test_dernier_echange_inconnu_pas_compte_mais_signale(dossier, debut, monkeypatch):
    jours = jours_ouvres(debut, 2)
    for j in jours:
        ecrire_jour(dossier, j, ["AAPL"])
    modifier(dossier, jours[-1], lambda d: vieillir(d, 2, dernier="INDISPONIBLE"))
    lancer_compare(monkeypatch)
    vo = resultat(dossier, jours[-1])["tickers"]["AAPL"]["volume_options"]
    assert vo["contrats_au_volume_ancien"] == 2
    assert vo["contrats_au_dernier_echange_inconnu"] == 2


def test_historique_recalcule_depuis_les_fichiers_bruts(dossier, debut, monkeypatch):
    jours = jours_ouvres(debut, 12)
    for j in jours:
        ecrire_jour(dossier, j, ["AAPL"])
    attendus = []
    for j in jours[:-1]:  # fichiers déjà collectés : totaux gonflés par du volume ancien

        def gonfler(d, attendus=attendus):
            vieillir(d, 1, volume=50_000)
            o = d["tickers"]["AAPL"]["options"]
            o["volume_calls"] += 50_000
            du_jour = [c for c in o["contrats"] if isinstance(c["volume"], int) and "2026-07-30" not in c["dernier_echange"]]
            attendus.append(sum(c["volume"] for c in du_jour))

        modifier(dossier, j, gonfler)
    lancer_compare(monkeypatch)
    vo = resultat(dossier, jours[-1])["tickers"]["AAPL"]["volume_options"]
    assert vo["nb_jours"] == 11
    assert (vo["min"], vo["max"]) == (min(attendus), max(attendus))  # aucun des 50 000 contrats anciens n'y figure
    assert vo["max"] < 50_000


def test_un_gros_volume_ancien_n_entre_pas_dans_les_strikes_actifs(dossier, debut, monkeypatch):
    jours = jours_ouvres(debut, 2)
    for j in jours:
        ecrire_jour(dossier, j, ["AAPL"])
    modifier(dossier, jours[-1], lambda d: vieillir(d, 1, volume=50_000))
    lancer_compare(monkeypatch)
    oi = resultat(dossier, jours[-1])["tickers"]["AAPL"]["open_interest"]
    assert all(c["volume_seance"] < 50_000 for c in oi["strikes_les_plus_actifs"])
    assert all(c["volume_seance"] == c["volume"] for c in oi["strikes_les_plus_actifs"])
    assert oi["strikes_actifs"]["volume"] < 50_000


def test_sans_date_de_seance_le_volume_reste_indisponible():
    contrat = {"type": "call", "volume": 10, "dernier_echange": "2026-08-20 19:59:00+00:00"}
    d = {"cours": {"date_seance": "INDISPONIBLE"}, "options": {"contrats": [contrat]}}
    assert compare.volume_options(d) == (None, None, None)
    assert compare.volume_options({"cours": {"date_seance": "2026-08-20"}, "options": {"statut": "INDISPONIBLE"}}) == (None,) * 3


def test_rang_eleve_sans_z_score_suffisant_n_est_pas_candidat(dossier, debut, monkeypatch):
    """Une journée banale au sommet de l'historique : rang 100, mais à peine au-dessus de la médiane."""
    jours = jours_ouvres(debut, 15)
    for j in jours:
        ecrire_jour(dossier, j, ["AAPL"], choc={"AAPL"} if j == jours[-1] else ())
    histo = []
    for j in jours[:-1]:
        d = json.loads((dossier / f"brut-{j}.json").read_text())
        histo.append(compare.volume_options(d["tickers"]["AAPL"])[0])

    def juste_au_dessus(data):
        cs = [c for c in contrats(data) if isinstance(c["volume"], int)]
        cible = max(histo) + 1  # nouveau maximum, d'une seule unité
        for c in cs:
            c["volume"] = 0
        cs[0]["volume"] = cible

    modifier(dossier, jours[-1], juste_au_dessus)
    lancer_compare(monkeypatch)
    sortie = resultat(dossier, jours[-1])
    vo = sortie["tickers"]["AAPL"]["volume_options"]
    assert vo["rang_percentile"] == 100.0
    assert vo["z_score_robuste"] < compare.SEUIL_Z_VOLUME
    assert sortie["tickers"]["AAPL"]["candidat"] is False
    assert sortie["criteres_candidat"]["z_score_robuste_volume_options_min"] == 3.5


def test_le_choc_franchit_aussi_le_z_score(dossier, debut, monkeypatch):
    jours = jours_ouvres(debut, 15)
    for j in jours:
        ecrire_jour(dossier, j, ["AAPL"], choc={"AAPL"} if j == jours[-1] else ())
    lancer_compare(monkeypatch)
    r = resultat(dossier, jours[-1])["tickers"]["AAPL"]
    assert r["volume_options"]["z_score_robuste"] >= compare.SEUIL_Z_VOLUME
    assert r["candidat"] is True
    # Le z sur le logarithme est enregistré, à titre d'information seulement
    assert "z_score_robuste_log" in r["volume_options"]
    assert not any("log" in k for k in resultat(dossier, jours[-1])["criteres_candidat"])


# --- z-score robuste (Iglewicz et Hoaglin), mêmes cas que le skill ---

BASE = [120, 80, 100, 140, 90, 110, 130, 100, 95, 135]


def test_z_robuste_valeurs_de_reference():
    assert compare.z_robuste(150, BASE) == pytest.approx(2.023, abs=1e-3)
    assert compare.z_robuste(130, BASE) == pytest.approx(1.124, abs=1e-3)
    zl = compare.z_robuste(math.log1p(150), [math.log1p(b) for b in BASE])
    assert zl == pytest.approx(1.681, abs=1e-3)


def test_z_robuste_repli_quand_la_mad_est_nulle():
    base = [100, 100, 100, 100, 100, 100, 90, 110, 120, 80]  # MAD 0, écart moyen 6
    assert compare.z_robuste(150, base) == pytest.approx(6.649, abs=1e-3)


def test_z_robuste_historique_plat_ou_trop_court():
    assert compare.z_robuste(150, [100] * 10) is None
    assert compare.z_robuste(150, BASE[:9]) is None


def test_choc_modeste_apres_un_tres_gros_choc_reste_visible():
    # Un très gros choc dans l'historique gonfle l'écart-type classique et masquait le suivant
    base = [100, 110, 90, 105, 95, 100, 108, 92, 102, 98, 20000]
    classique = (300 - statistics.mean(base)) / statistics.pstdev(base)
    assert classique < 0
    assert compare.z_robuste(300, base) >= compare.SEUIL_Z_VOLUME


def test_journee_banale_ecartee_par_le_z_robuste():
    # Nouveau maximum, donc rang 100, mais à peine au-dessus de la dispersion habituelle
    stats = compare.stats_historique(150, BASE, avec_log=True)
    assert stats["rang_percentile"] == 100.0
    assert stats["z_score_robuste"] < compare.SEUIL_Z_VOLUME
    assert stats["z_score_robuste_log"] == pytest.approx(1.681, abs=1e-3)
