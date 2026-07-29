"""Orchestrazione: da PlanRequest a piano giornaliero/settimanale (sezioni 7, 9, 11)."""
from __future__ import annotations

from typing import Dict, List, Optional

from .config import MAX_OPTIONS_PER_MACRO
from .food_db import FoodDB, get_db
from .macros import meal_targets
from .models import DayOptions, DayPlan, MealOptions, MealResult, PlanRequest, WeekPlan
from .solver import balance_meal, contribution_targets, diagnose_infeasibility, macro_equivalents

_MACROS = ("carbo", "proteine", "grassi")


def build_day(
    req: PlanRequest,
    *,
    db: Optional[FoodDB] = None,
    variant: int = 0,
    etichetta: str = "Giorno",
) -> DayPlan:
    """Costruisce il piano di una giornata bilanciando ogni pasto.

    `variant` sceglie alternative diverse (per giorni vari ma equivalenti).
    """
    db = db or get_db()
    pasti: List[MealResult] = []
    for meal in req.pasti:
        target = meal_targets(req.kcal_target, meal)
        result = balance_meal(
            db,
            meal.nome,
            target,
            esclusi=req.alimenti_esclusi,
            categorie_escluse=req.categorie_escluse,
            categorie_incluse=meal.categorie_incluse,
            pasto=meal.tipo_pasto,
            preferiti=req.alimenti_preferiti,
            variant=variant,
        )
        if result is None:
            motivo = diagnose_infeasibility(
                db,
                target,
                esclusi=req.alimenti_esclusi,
                categorie_escluse=req.categorie_escluse,
                categorie_incluse=meal.categorie_incluse,
                pasto=meal.tipo_pasto,
            )
            raise ValueError(
                f"Impossibile bilanciare il pasto '{meal.nome}': {motivo}."
            )
        pasti.append(result)

    kcal_tot = sum(p.kcal_ottenute for p in pasti)
    return DayPlan(
        etichetta=etichetta,
        pasti=pasti,
        kcal_totali=round(kcal_tot, 1),
        errore_kcal_giorno=round(kcal_tot - req.kcal_target, 1),
    )


def build_day_options(
    req: PlanRequest,
    *,
    db: Optional[FoodDB] = None,
    max_per_macro: Optional[Dict[str, int]] = None,
    etichetta: str = "Giorno",
) -> DayOptions:
    """Per ogni pasto, liste di alimenti equivalenti per ciascun macro.

    `max_per_macro` è il numero MASSIMO di opzioni per ciascun macro (ognuno il
    suo); se ne vengono trovate di meno, restituisce quelle disponibili. I macro
    non specificati usano i default di MAX_OPTIONS_PER_MACRO.

    Il nutrizionista sceglie 1 alimento per categoria (carbo/proteine/grassi):
    qualunque combinazione rispetta i macro target del pasto.
    """
    db = db or get_db()
    limiti = dict(MAX_OPTIONS_PER_MACRO)
    if max_per_macro:
        limiti.update({k: v for k, v in max_per_macro.items() if v is not None})

    pasti: List[MealOptions] = []
    for meal in req.pasti:
        target = meal_targets(req.kcal_target, meal)
        # Contributi compensati: ogni macro fornito dal proprio alimento al netto
        # degli incidentali altrui -> la media "1 per macro" torna ~ target.
        contrib = contribution_targets(
            db,
            target,
            max_per_macro=limiti,
            esclusi=req.alimenti_esclusi,
            categorie_escluse=req.categorie_escluse,
            categorie_incluse=meal.categorie_incluse,
            pasto=meal.tipo_pasto,
        )
        opzioni = {
            macro: macro_equivalents(
                db,
                target,
                macro,
                n=limiti[macro],
                esclusi=req.alimenti_esclusi,
                categorie_escluse=req.categorie_escluse,
                categorie_incluse=meal.categorie_incluse,
                pasto=meal.tipo_pasto,
                preferiti=req.alimenti_preferiti,
                target_g_override=contrib[macro],
            )
            for macro in _MACROS
        }
        pasti.append(MealOptions(nome=meal.nome, target=target, opzioni=opzioni))
    return DayOptions(etichetta=etichetta, pasti=pasti)


_GIORNI = [
    "Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì", "Sabato", "Domenica",
]


def build_week(req: PlanRequest, *, db: Optional[FoodDB] = None) -> WeekPlan:
    """Costruisce 7 giorni vari ma nutrizionalmente equivalenti."""
    db = db or get_db()
    giorni = [
        build_day(req, db=db, variant=i, etichetta=_GIORNI[i])
        for i in range(7)
    ]
    return WeekPlan(giorni=giorni)
