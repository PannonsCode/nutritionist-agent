"""Caricamento del database alimenti e classificazione per macro dominante.

Il CSV originale ha categorie merceologiche (Verdure, Carni, ...) che NON
corrispondono al macronutriente dominante. Qui ricaviamo, per ogni alimento,
quale macro è dominante e quanto è "puro" (frazione di kcal-da-macro fornite
dal macro dominante). I pool puri rendono il sistema lineare 3x3 del solver
ben condizionato -> soluzione positiva con errore ~0.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .config import (
    COLUMN_ALIASES,
    COOKED_TERMS,
    CSV_SEPARATOR,
    DEFAULT_FOOD_CSV,
    KCAL_PER_G,
    MIN_DENSITY,
    MIN_PURITY,
    PREFER_RAW,
    PREFERRED_CATEGORIES,
    RAW_TERMS,
    UNCOMMON_TERMS,
)

MACROS = ("carbo", "proteine", "grassi")


def _cooked_rank(nome: str) -> int:
    """0 = crudo, 1 = neutro, 2 = cotto/lavorato (per preferire il crudo)."""
    if not PREFER_RAW:
        return 0
    n = nome.lower()
    if any(t in n for t in RAW_TERMS):
        return 0
    if any(t in n for t in COOKED_TERMS):
        return 2
    return 1


def _uncommon_rank(nome: str) -> int:
    """1 se l'alimento contiene un termine 'esotico'/poco comune, altrimenti 0."""
    n = nome.lower()
    return 1 if any(t in n for t in UNCOMMON_TERMS) else 0


@dataclass(frozen=True)
class Food:
    """Un alimento con i macro per 100g e l'etichetta di macro dominante."""

    nome: str
    categoria: str
    kcal_100: float
    carbo_100: float       # g carboidrati / 100g
    proteine_100: float    # g proteine / 100g
    grassi_100: float      # g grassi / 100g
    ruolo: str             # macro dominante: "carbo" | "proteine" | "grassi"
    purezza: float         # frazione kcal-da-macro fornite dal macro dominante
    pasti: tuple = ()      # pasti consigliati (lowercase): es. ("pranzo","cena")

    def per_gram(self, macro: str) -> float:
        """Grammi del macro indicato per 1g di alimento."""
        return {
            "carbo": self.carbo_100,
            "proteine": self.proteine_100,
            "grassi": self.grassi_100,
        }[macro] / 100.0

    def kcal_per_gram(self) -> float:
        """Kcal per 1g, calcolate dai macro (Atwater 4/4/9).

        NB: NON si usa la colonna energia_kcal del CSV: ~58 righe la hanno
        corrotta (gonfiata ~x10, es. yogurt/verdure cotte/salumi). I macro sono
        invece coerenti, e usare 4/4/9 è anche allineato a come si derivano i
        target in kcal dai macronutrienti.
        """
        return (
            KCAL_PER_G["carbo"] * self.carbo_100
            + KCAL_PER_G["proteine"] * self.proteine_100
            + KCAL_PER_G["grassi"] * self.grassi_100
        ) / 100.0

    def kcal_100_atwater(self) -> float:
        """Kcal per 100g calcolate dai macro (Atwater)."""
        return self.kcal_per_gram() * 100.0


def _to_float(value) -> float:
    """Converte un valore del CSV in float, gestendo 'tr' (tracce) e nan."""
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return 0.0 if (isinstance(value, float) and np.isnan(value)) else float(value)
    s = str(value).strip().lower().replace(",", ".")
    if s in ("", "tr", "tracce", "nan", "n.d.", "nd"):
        return 0.05 if s in ("tr", "tracce") else 0.0
    try:
        return float(s)
    except ValueError:
        return 0.0


def _parse_pasti(value) -> tuple:
    """Converte 'cena,pranzo' (o lista) nei pasti consigliati lowercased."""
    if value is None:
        return ()
    s = str(value).strip()
    if not s or s.lower() in ("nan", "n.d.", "nd"):
        return ()
    parti = s.replace(";", ",").replace("/", ",").split(",")
    return tuple(p.strip().lower() for p in parti if p.strip())


def _classify(carbo: float, proteine: float, grassi: float) -> "tuple[str, float]":
    """Determina macro dominante e purezza dai grammi per 100g."""
    kcal_macro = {
        "carbo": carbo * KCAL_PER_G["carbo"],
        "proteine": proteine * KCAL_PER_G["proteine"],
        "grassi": grassi * KCAL_PER_G["grassi"],
    }
    total = sum(kcal_macro.values())
    if total <= 0:
        return "carbo", 0.0
    ruolo = max(kcal_macro, key=kcal_macro.get)
    purezza = kcal_macro[ruolo] / total
    return ruolo, purezza


def _read_csv_auto(path: Path) -> pd.DataFrame:
    """Legge il CSV rilevando il separatore se CSV_SEPARATOR è None."""
    if CSV_SEPARATOR:
        return pd.read_csv(path, sep=CSV_SEPARATOR)
    # Prova ';' poi ',' poi tab: vince quello che produce più colonne.
    best, best_df = -1, None
    for sep in (";", ",", "\t"):
        try:
            df = pd.read_csv(path, sep=sep)
        except Exception:
            continue
        if df.shape[1] > best:
            best, best_df = df.shape[1], df
    if best_df is None:
        raise ValueError(f"Impossibile leggere il CSV {path}.")
    return best_df


def _resolve_columns(df: pd.DataFrame, path: Path) -> Dict[str, str]:
    """Mappa i campi logici (nome/categoria/kcal/proteine/lipidi/carbo) sui nomi
    reali delle colonne del CSV, usando COLUMN_ALIASES. I macro sono obbligatori."""
    lower = {c.lower().strip(): c for c in df.columns}
    resolved: Dict[str, str] = {}
    for field, aliases in COLUMN_ALIASES.items():
        for a in aliases:
            if a.lower() in lower:
                resolved[field] = lower[a.lower()]
                break
    mancanti = [f for f in ("proteine", "lipidi", "carbo") if f not in resolved]
    if mancanti:
        raise ValueError(
            f"Nel CSV {path.name} mancano le colonne per: {', '.join(mancanti)}. "
            f"Colonne trovate: {list(df.columns)}. "
            f"Aggiungi un alias in COLUMN_ALIASES (nutri/config.py) se hanno un altro nome."
        )
    return resolved


class FoodDB:
    """Database alimenti in memoria con i pool per macro."""

    def __init__(self, foods: List[Food]):
        self.foods = foods
        self._by_name = {f.nome.lower(): f for f in foods}

    @classmethod
    def from_csv(cls, path: Optional[Path] = None) -> "FoodDB":
        path = Path(path) if path else DEFAULT_FOOD_CSV
        if not path.exists():
            raise FileNotFoundError(
                f"Database non trovato: {path}. Metti il CSV in {path} oppure "
                f"imposta la variabile d'ambiente NUTRI_FOOD_CSV."
            )
        df = _read_csv_auto(path)
        cols = _resolve_columns(df, path)  # logico -> nome reale della colonna

        def cell(row, key):
            name = cols.get(key)
            return row.get(name) if name else None

        foods: List[Food] = []
        for _, row in df.iterrows():
            carbo = _to_float(cell(row, "carbo"))
            proteine = _to_float(cell(row, "proteine"))
            grassi = _to_float(cell(row, "lipidi"))
            kcal = _to_float(cell(row, "kcal"))  # solo riferimento; si usa Atwater
            if carbo + proteine + grassi <= 0:
                continue
            ruolo, purezza = _classify(carbo, proteine, grassi)
            foods.append(
                Food(
                    nome=str(cell(row, "nome") or "").strip(),
                    categoria=str(cell(row, "categoria") or "").strip(),
                    kcal_100=kcal,
                    carbo_100=carbo,
                    proteine_100=proteine,
                    grassi_100=grassi,
                    ruolo=ruolo,
                    purezza=purezza,
                    pasti=_parse_pasti(cell(row, "pasto")),
                )
            )
        if not foods:
            raise ValueError(
                f"Nessun alimento valido caricato da {path}: controlla i nomi delle "
                f"colonne (vedi COLUMN_ALIASES) e il separatore."
            )
        return cls(foods)

    def pool(
        self,
        macro: str,
        *,
        min_purity: float = MIN_PURITY,
        esclusi: Optional[List[str]] = None,
        categorie_escluse: Optional[List[str]] = None,
        categorie_incluse: Optional[List[str]] = None,
        pasto: Optional[str] = None,
        prefer_categories: Optional[List[str]] = "default",
    ) -> List[Food]:
        """Alimenti la cui fonte dominante è `macro`.

        Ordinamento: prima le categorie "staple" preferite (nell'ordine indicato),
        poi per purezza decrescente. Così pasta/riso/legumi vengono prima dello
        zucchero puro. `prefer_categories=None` disattiva la preferenza.
        Filtra per purezza/densità minima e per le esclusioni del paziente.
        `categorie_incluse` (se non vuoto) è una whitelist: passano solo gli
        alimenti di quelle categorie.
        """
        if prefer_categories == "default":
            prefer_categories = PREFERRED_CATEGORIES.get(macro, [])
        prio = {c.lower(): i for i, c in enumerate(prefer_categories or [])}

        esclusi_l = {e.lower().strip() for e in (esclusi or []) if e and e.strip()}
        cat_escl_l = {c.lower().strip() for c in (categorie_escluse or []) if c and c.strip()}
        cat_incl_l = {c.lower().strip() for c in (categorie_incluse or []) if c and c.strip()}
        pasto_l = (pasto or "").strip().lower() or None
        min_dens = MIN_DENSITY[macro]
        out: List[Food] = []
        for f in self.foods:
            if f.ruolo != macro or f.purezza < min_purity:
                continue
            if f.per_gram(macro) * 100 < min_dens:
                continue
            if pasto_l and pasto_l not in f.pasti:
                continue
            if cat_incl_l and f.categoria.lower() not in cat_incl_l:
                continue
            if f.categoria.lower() in cat_escl_l:
                continue
            if any(term in f.nome.lower() for term in esclusi_l):
                continue
            out.append(f)
        # Ordine: categoria staple -> alimenti comuni -> crudi -> purezza desc.
        out.sort(
            key=lambda x: (
                prio.get(x.categoria.lower(), 999),
                _uncommon_rank(x.nome),
                _cooked_rank(x.nome),
                -x.purezza,
            )
        )
        return out

    def get(self, nome: str) -> Optional[Food]:
        return self._by_name.get(nome.lower())

    def stats(self) -> Dict[str, int]:
        counts = {m: 0 for m in MACROS}
        for f in self.foods:
            counts[f.ruolo] += 1
        return counts

    def meal_types(self) -> List[str]:
        """Tipi di pasto presenti nella colonna pasto_consigliato del CSV."""
        tipi = sorted({p for f in self.foods for p in f.pasti})
        return tipi


@lru_cache(maxsize=1)
def get_db() -> FoodDB:
    """Singleton del database (caricato una sola volta)."""
    return FoodDB.from_csv()
