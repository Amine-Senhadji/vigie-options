import types
from datetime import date

import pytest

import collect
from conftest import FakeTicker

INDISPO = collect.INDISPO
JOUR = date(2026, 8, 20)


class Panne:
    """Imite yf.Ticker quand Yahoo ne répond pas du tout."""

    def history(self, **_):
        raise ConnectionError("Yahoo injoignable")

    @property
    def options(self):
        raise ConnectionError("Yahoo injoignable")

    @property
    def calendar(self):
        raise ConnectionError("Yahoo injoignable")


def capricieux(reponses):
    """Fonction qui lève ou renvoie tour à tour les éléments de `reponses`, et compte ses appels."""
    etat = types.SimpleNamespace(appels=0)

    def appel():
        r = reponses[etat.appels]
        etat.appels += 1
        if isinstance(r, Exception):
            raise r
        return r

    return appel, etat


@pytest.fixture
def pauses(monkeypatch):
    """Rétablit la vraie pause de reprise et enregistre les attentes au lieu de dormir."""
    attentes = []
    monkeypatch.setattr(collect, "PAUSE_REPRISE", 2.0)
    monkeypatch.setattr(collect.time, "sleep", attentes.append)
    return attentes


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
    assert collect.collecter_cours(Panne())["statut"] == INDISPO
    assert collect.collecter_options(Panne(), 60)["statut"] == INDISPO
    assert collect.collecter_evenements(Panne())["statut"] == INDISPO


def test_seance_en_cours_selon_l_heure_de_new_york():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    paris, ny = ZoneInfo("Europe/Paris"), ZoneInfo("America/New_York")
    assert collect.seance_en_cours(datetime(2026, 10, 13, 9, 0, tzinfo=paris)) is False  # avant l'ouverture
    assert collect.seance_en_cours(datetime(2026, 10, 13, 17, 0, tzinfo=paris)) is True  # 11 h à New York
    assert collect.seance_en_cours(datetime(2026, 10, 13, 16, 0, tzinfo=ny)) is False  # clôture
    assert collect.seance_en_cours(datetime(2026, 10, 17, 11, 0, tzinfo=ny)) is False  # samedi


def test_collecte_refusee_pendant_la_seance(monkeypatch, tmp_path):
    monkeypatch.setattr(collect, "seance_en_cours", lambda: True)
    monkeypatch.setattr(collect, "lire_watchlist", lambda: ["AAPL"])
    monkeypatch.setattr(collect, "DOSSIER", tmp_path)
    monkeypatch.setattr("sys.argv", ["collect.py"])
    with pytest.raises(SystemExit, match="séance américaine est ouverte"):
        collect.main()
    assert not list(tmp_path.iterdir())


def test_nouvelle_tentative_apres_une_pause_qui_double(pauses):
    appel, etat = capricieux([ConnectionError("Yahoo injoignable"), TimeoutError("trop long"), "réponse"])
    assert collect.avec_reprises(appel, "cours") == "réponse"
    assert etat.appels == 3
    assert pauses == [2.0, 4.0]


def test_abandon_apres_le_dernier_essai(pauses, monkeypatch):
    monkeypatch.setattr(collect, "NB_TENTATIVES", 4)
    appel, etat = capricieux([ConnectionError(f"échec {i}") for i in range(1, 5)])
    with pytest.raises(ConnectionError, match="échec 4"):
        collect.avec_reprises(appel, "cours")
    assert etat.appels == 4
    assert pauses == [2.0, 4.0, 8.0]  # aucune attente après le dernier essai


def test_reponse_vide_retentee_puis_rendue_telle_quelle(pauses):
    appel, etat = capricieux([[], [], []])
    assert collect.avec_reprises(appel, "échéances", est_vide=lambda r: not r) == []
    assert etat.appels == collect.NB_TENTATIVES
    assert pauses == [2.0, 4.0]

    appel, etat = capricieux([[], ["2026-08-28"]])
    assert collect.avec_reprises(appel, "échéances", est_vide=lambda r: not r) == ["2026-08-28"]
    assert etat.appels == 2


def test_pas_de_nouvelle_tentative_quand_yahoo_repond(pauses):
    res = collect.collecter_cours(FakeTicker("AAPL", JOUR))
    assert res["date_seance"] == "2026-08-20"
    assert pauses == []


def test_collecte_reussie_apres_un_echec_passager(pauses):
    class Instable(FakeTicker):
        """Yahoo échoue une fois sur chaque type de requête, puis répond."""

        def __init__(self, *a, **k):
            self.deja = set()
            super().__init__(*a, **k)

        def _une_panne(self, quoi):
            if quoi not in self.deja:
                self.deja.add(quoi)
                raise ConnectionError(f"{quoi} : Yahoo injoignable")

        def history(self, **k):
            if "cours" not in self.deja:  # yfinance masque l'erreur et renvoie un tableau vide
                self.deja.add("cours")
                return super().history(**k).iloc[0:0]
            return super().history(**k)

        @property
        def options(self):
            self._une_panne("échéances")
            return self._echeances

        @options.setter
        def options(self, valeur):
            self._echeances = valeur

        def option_chain(self, echeance):
            self._une_panne(echeance)
            return super().option_chain(echeance)

    t = Instable("AAPL", JOUR)
    assert collect.collecter_cours(t)["date_seance"] == "2026-08-20"
    opts = collect.collecter_options(t, 60, aujourdhui=JOUR)
    assert opts["echeances_en_echec"] == []
    assert len(opts["contrats"]) == 2 * 2 * 3
    assert pauses.count(2.0) == 4  # cours, liste des échéances, puis chacune des deux chaînes
    assert 4.0 not in pauses


def test_chaine_vide_apres_tous_les_essais_notee_en_echec():
    class SansChaine(FakeTicker):
        def option_chain(self, echeance):
            return types.SimpleNamespace(calls=None, puts=None)

    opts = collect.collecter_options(SansChaine("AAPL", JOUR), 60, aujourdhui=JOUR)
    assert [e["echeance"] for e in opts["echeances_en_echec"]] == ["2026-08-28", "2026-09-18"]
    assert opts["contrats"] == []
    assert opts["volume_calls"] == INDISPO


@pytest.fixture
def collecte(monkeypatch, tmp_path):
    """Prépare main() : hors séance, dossier temporaire, Yahoo remplacé par `tickers[code]`."""

    def preparer(tickers):
        monkeypatch.setattr(collect, "seance_en_cours", lambda: False)
        monkeypatch.setattr(collect, "lire_watchlist", lambda: list(tickers))
        monkeypatch.setattr(collect, "RACINE", tmp_path)
        monkeypatch.setattr(collect, "DOSSIER", tmp_path / "donnees")
        monkeypatch.setattr(collect.yf, "Ticker", lambda code: tickers[code])
        monkeypatch.setattr("sys.argv", ["collect.py"])
        return tmp_path / "donnees" / f"brut-{date.today().isoformat()}.json"

    return preparer


def test_tous_les_tickers_en_echec_code_de_sortie_non_nul_et_rien_d_ecrit(collecte, capsys):
    sortie = collecte({"AAPL": Panne(), "MSFT": Panne()})
    with pytest.raises(SystemExit) as arret:
        collect.main()
    assert arret.value.code not in (0, None)
    assert "aucun des 2 ticker(s)" in str(arret.value.code)
    assert "AAPL : cours : Yahoo injoignable ; options : Yahoo injoignable" in str(arret.value.code)
    assert not sortie.exists()
    assert "Fichier :" not in capsys.readouterr().out


def test_echec_total_n_ecrase_pas_une_collecte_reussie_du_meme_jour(collecte):
    sortie = collecte({"AAPL": Panne()})
    sortie.parent.mkdir()
    sortie.write_text('{"collecte": "du matin"}', encoding="utf-8")
    with pytest.raises(SystemExit):
        collect.main()
    assert sortie.read_text(encoding="utf-8") == '{"collecte": "du matin"}'


def test_echec_partiel_fichier_ecrit_et_sortie_normale(collecte, capsys):
    import json

    sortie = collecte({"AAPL": Panne(), "MSFT": FakeTicker("MSFT", date.today())})
    collect.main()  # ne lève pas SystemExit : code de sortie 0
    data = json.loads(sortie.read_text(encoding="utf-8"))
    assert data["tickers"]["AAPL"]["cours"]["statut"] == INDISPO
    assert data["tickers"]["AAPL"]["options"]["erreur"] == "Yahoo injoignable"
    assert data["tickers"]["MSFT"]["options"]["contrats"]
    assert "AAPL : séance INDISPONIBLE | INDISPONIBLE : cours, options, evenements" in capsys.readouterr().out


def test_ticker_sans_aucun_contrat_compte_comme_un_echec():
    cours = {"cloture": 100.0}
    assert collect.motifs_d_echec({"cours": cours, "options": {"contrats": [{"symbole": "X"}]}}) == []
    assert collect.motifs_d_echec({"cours": cours, "options": {"contrats": []}}) == ["options : aucune chaîne lisible"]
    assert collect.motifs_d_echec({"cours": {"statut": INDISPO}, "options": {"contrats": [{}]}}) == ["cours : INDISPONIBLE"]
    vide = types.SimpleNamespace(history=lambda **_: FakeTicker("AAPL", JOUR).history().iloc[0:0])
    assert collect.collecter_cours(vide)["erreur"] == "aucun cours renvoyé par la source"
