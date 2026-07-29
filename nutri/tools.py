"""Tool deterministici esposti agli agenti Agno.

Tutta la logica numerica vive qui sotto (macros/solver/planner): gli agenti LLM
si limitano a orchestrare, interpretare le richieste del nutrizionista in
linguaggio naturale e chiamare questi tool. Ogni funzione restituisce dict/JSON
serializzabili così l'LLM può ragionarci sopra.
"""
from __future__ import annotations

import json
from typing import List

from .food_db import get_db
from .macros import kcal_to_macro_targets
from .models import MacroSplit, MealSpec, PlanRequest
from .planner import build_day, build_week
from .solver import balance_meal, meal_alternatives


def calcola_macronutrienti(
    kcal_pasto: float,
    perc_carboidrati: float,
    perc_proteine: float,
    perc_grassi: float,
) -> dict:
    """Calcola i grammi target di carboidrati, proteine e grassi per un pasto.

    Args:
        kcal_pasto: kcal totali del pasto.
        perc_carboidrati: frazione di kcal da carboidrati (0-1, es. 0.5).
        perc_proteine: frazione di kcal da proteine (0-1).
        perc_grassi: frazione di kcal da grassi (0-1).

    Returns:
        dict con kcal e grammi target per ciascun macronutriente.
    """
    target = kcal_to_macro_targets(
        kcal_pasto,
        {"carbo": perc_carboidrati, "proteine": perc_proteine, "grassi": perc_grassi},
    )
    return target.model_dump()


def bilancia_pasto(
    nome_pasto: str,
    kcal_pasto: float,
    perc_carboidrati: float,
    perc_proteine: float,
    perc_grassi: float,
    alimenti_esclusi: str = "",
    alimenti_preferiti: str = "",
) -> dict:
    """Seleziona gli alimenti (1 per macro) e le grammature che bilanciano un pasto.

    Risolve il sistema lineare carbo/proteine/grassi così l'errore sulle kcal del
    pasto tende a zero. Restituisce gli alimenti scelti con grammatura e macro.

    Args:
        nome_pasto: etichetta del pasto (es. "Pranzo").
        kcal_pasto: kcal totali del pasto.
        perc_carboidrati: frazione kcal da carboidrati (0-1).
        perc_proteine: frazione kcal da proteine (0-1).
        perc_grassi: frazione kcal da grassi (0-1).
        alimenti_esclusi: nomi (o parti di nome) separati da virgola da escludere.
        alimenti_preferiti: nomi separati da virgola da preferire.
    """
    target = kcal_to_macro_targets(
        kcal_pasto,
        {"carbo": perc_carboidrati, "proteine": perc_proteine, "grassi": perc_grassi},
    )
    result = balance_meal(
        get_db(),
        nome_pasto,
        target,
        esclusi=_split(alimenti_esclusi),
        preferiti=_split(alimenti_preferiti),
    )
    if result is None:
        return {"errore": "Nessuna combinazione trovata con i vincoli forniti."}
    return result.model_dump()


def alternative_pasto(
    nome_pasto: str,
    kcal_pasto: float,
    perc_carboidrati: float,
    perc_proteine: float,
    perc_grassi: float,
    n: int = 5,
) -> dict:
    """Propone fino a `n` alternative nutrizionalmente equivalenti per un pasto."""
    target = kcal_to_macro_targets(
        kcal_pasto,
        {"carbo": perc_carboidrati, "proteine": perc_proteine, "grassi": perc_grassi},
    )
    alts = meal_alternatives(get_db(), nome_pasto, target, n=n)
    return {"alternative": [a.model_dump() for a in alts]}


def genera_piano(richiesta_json: str) -> dict:
    """Genera un piano giornaliero completo da una richiesta in formato JSON.

    Args:
        richiesta_json: JSON con i campi:
            kcal_target (float), pasti (lista di
            {nome, kcal_percent, macro_split:{carbo,proteine,grassi}}),
            e opzionali alimenti_preferiti / alimenti_esclusi / categorie_escluse.

    Returns:
        Il piano giornaliero con alimenti, grammature, kcal ed errori.
    """
    req = PlanRequest.model_validate_json(richiesta_json)
    return build_day(req).model_dump()


def genera_piano_settimanale(richiesta_json: str) -> dict:
    """Come genera_piano ma produce 7 giorni vari ma nutrizionalmente equivalenti."""
    req = PlanRequest.model_validate_json(richiesta_json)
    return build_week(req).model_dump()


def cerca_alimenti_fonte(macro: str, n: int = 15) -> dict:
    """Elenca i migliori alimenti-fonte per un macro ('carbo'|'proteine'|'grassi').

    Utile quando il nutrizionista chiede "quali alimenti posso usare per i grassi?".
    """
    if macro not in ("carbo", "proteine", "grassi"):
        return {"errore": "macro deve essere 'carbo', 'proteine' o 'grassi'"}
    foods = get_db().pool(macro)[:n]
    return {
        "macro": macro,
        "alimenti": [
            {
                "nome": f.nome,
                "categoria": f.categoria,
                "carbo_100g": f.carbo_100,
                "proteine_100g": f.proteine_100,
                "grassi_100g": f.grassi_100,
                "kcal_100g": round(f.kcal_100_atwater(), 1),
                "purezza": round(f.purezza, 2),
            }
            for f in foods
        ],
    }


def _split(s: str) -> List[str]:
    return [x.strip() for x in (s or "").split(",") if x.strip()]


# Liste di tool per gli agenti
MACRO_TOOLS = [calcola_macronutrienti, cerca_alimenti_fonte]
SELECTION_TOOLS = [bilancia_pasto, alternative_pasto, cerca_alimenti_fonte]
PLAN_TOOLS = [genera_piano, genera_piano_settimanale, alternative_pasto]
