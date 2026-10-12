"""Données simulées : aucun test n'appelle Yahoo Finance."""

import json
import types
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

import collect
import compare
import suivi

ECHEANCES = ["2026-08-28", "2026-09-18", "2026-12-18"]


class FakeTicker:
    """Imite yf.Ticker. `choc=True` multiplie le volume et ouvre des positions."""

    def __init__(self, tk, jour, choc=False, graine=0, mouvement=0.0):
        self.tk, self.jour, self.choc = tk, jour, choc
        rng = np.random.default_rng(graine)
        idx = pd.bdate_range(end=jour, periods=120, tz="America/New_York")
        px = 100 + np.cumsum(rng.normal(0, 1, len(idx)))
        px[-1] = px[-2] * (1 + mouvement)
        self._h = pd.DataFrame({"Close": px, "Volume": rng.integers(1_000_000, 2_000_000, len(idx)).astype(float)}, index=idx)
        self._rng = rng
        self.options = ECHEANCES
        self.calendar = {"Earnings Date": [jour + timedelta(days=20)], "Ex-Dividend Date": jour + timedelta(days=90)}

    def history(self, **_):
        return self._h

    def option_chain(self, echeance):
        def tableau(type_):
            strikes = [90.0, 100.0, 110.0]
            volumes = [float(self._rng.integers(10, 100)) * (20 if self.choc else 1) for _ in strikes]
            volumes[0] = float("nan")  # contrat sans échange
            oi = [1000 + (500 if self.choc else int(self._rng.integers(-20, 20))) for _ in strikes]
            return pd.DataFrame(
                {
                    "contractSymbol": [f"{self.tk}{echeance}{type_}{s:g}" for s in strikes],
                    "strike": strikes,
                    "volume": volumes,
                    "openInterest": oi,
                    "lastTradeDate": pd.Timestamp(self.jour),
                }
            )

        return types.SimpleNamespace(calls=tableau("C"), puts=tableau("P"))


def ecrire_jour(dossier, jour, tickers, choc=(), mouvement=0.0):
    data = {"date_collecte": jour.isoformat(), "tickers": {}}
    for tk in tickers:
        t = FakeTicker(tk, jour, choc=tk in choc, graine=jour.toordinal() * 100 + sum(map(ord, tk)), mouvement=mouvement)
        data["tickers"][tk] = {
            "cours": collect.collecter_cours(t),
            "options": collect.collecter_options(t, 60, aujourdhui=jour),
            "evenements": collect.collecter_evenements(t, aujourdhui=jour),
        }
    (dossier / f"brut-{jour.isoformat()}.json").write_text(json.dumps(data, default=str), encoding="utf-8")


def jours_ouvres(debut, n):
    jours, d = [], debut
    while len(jours) < n:
        if d.weekday() < 5:
            jours.append(d)
        d += timedelta(days=1)
    return jours


@pytest.fixture
def dossier(tmp_path, monkeypatch):
    monkeypatch.setattr(collect, "PAUSE", 0)
    monkeypatch.setattr(compare, "DOSSIER", tmp_path)
    monkeypatch.setattr(compare, "RACINE", tmp_path)
    return tmp_path


@pytest.fixture
def projet(tmp_path, monkeypatch):
    """Arborescence complète pour suivi.py : donnees/, rapports/, suivi/."""
    for nom in ("donnees", "rapports", "suivi"):
        (tmp_path / nom).mkdir()
    monkeypatch.setattr(suivi, "RACINE", tmp_path)
    monkeypatch.setattr(suivi, "DONNEES", tmp_path / "donnees")
    monkeypatch.setattr(suivi, "RAPPORTS", tmp_path / "rapports")
    monkeypatch.setattr(suivi, "JOURNAL", tmp_path / "suivi" / "journal.csv")
    return tmp_path


@pytest.fixture
def debut():
    return date(2026, 8, 3)


def lancer_compare(monkeypatch, *args):
    monkeypatch.setattr("sys.argv", ["compare.py", *args])
    compare.main()
