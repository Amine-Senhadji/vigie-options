from datetime import date

import collect
from conftest import FakeTicker

INDISPO = collect.INDISPO
JOUR = date(2026, 8, 20)


def test_nombre_remplace_les_trous_par_indisponible():
    assert collect.nombre(float("nan")) == INDISPO
    assert collect.nombre(None) == INDISPO
    assert collect.nombre("abc") == INDISPO
    assert collect.nombre(12.7, entier=True) == 12
    assert collect.nombre(1.234567) == 1.2346


def test_watchlist_ignore_commentaires_et_doublons(tmp_path, monkeypatch):
    f = tmp_path / "watchlist.txt"
    f.write_text("# commentaire\naapl\n\nMSFT  # Microsoft\nAAPL\n", encoding="utf-8")
    monkeypatch.setattr(collect, "WATCHLIST", f)
    assert collect.lire_watchlist() == ["AAPL", "MSFT"]


def test_cours_calcule_volume_relatif():
    res = collect.collecter_cours(FakeTicker("AAPL", JOUR))
    assert res["date_seance"] == "2026-08-20"
    assert res["nb_seances_moyenne"] == 30
    assert isinstance(res["ratio_volume_vs_moyenne_30"], float)
    assert all("date" in x for x in res["historique_90j"])


def test_options_filtre_horizon_et_ne_comble_pas_les_trous(monkeypatch):
    monkeypatch.setattr(collect, "PAUSE", 0)
    res = collect.collecter_options(FakeTicker("AAPL", JOUR), 60, aujourdhui=JOUR)
    assert res["echeances_retenues"] == ["2026-08-28", "2026-09-18"]
    assert len(res["contrats"]) == 2 * 2 * 3
    assert res["contrats_sans_volume"] == 4
    assert all(c["volume"] == INDISPO for c in res["contrats"] if c["strike"] == 90.0)


def test_evenements_dans_les_30_jours_seulement():
    res = collect.collecter_evenements(FakeTicker("AAPL", JOUR), aujourdhui=JOUR)
    assert res["evenements"] == [{"type": "resultats", "date": "2026-09-09"}]


def test_source_en_panne_donne_indisponible():
    class Panne:
        def history(self, **_):
            raise ConnectionError("Yahoo injoignable")

        @property
        def options(self):
            raise ConnectionError("Yahoo injoignable")

        @property
        def calendar(self):
            raise ConnectionError("Yahoo injoignable")

    assert collect.collecter_cours(Panne())["statut"] == INDISPO
    assert collect.collecter_options(Panne(), 60)["statut"] == INDISPO
    assert collect.collecter_evenements(Panne())["statut"] == INDISPO
