"""Conversione kcal -> grammi di macronutrienti (sezioni 3 e 4 dei requisiti)."""
from __future__ import annotations

from .config import KCAL_PER_G
from .models import MacroTargets, MealSpec


def kcal_to_macro_targets(kcal_pasto: float, macro_split: dict) -> MacroTargets:
    """Converte le kcal di un pasto in grammi target per ciascun macro.

    Carboidrati = kcal * %carbo / 4
    Proteine    = kcal * %proteine / 4
    Grassi      = kcal * %grassi / 9
    """
    carbo_g = kcal_pasto * macro_split["carbo"] / KCAL_PER_G["carbo"]
    prot_g = kcal_pasto * macro_split["proteine"] / KCAL_PER_G["proteine"]
    fat_g = kcal_pasto * macro_split["grassi"] / KCAL_PER_G["grassi"]
    return MacroTargets(
        kcal=kcal_pasto,
        carbo_g=round(carbo_g, 2),
        proteine_g=round(prot_g, 2),
        grassi_g=round(fat_g, 2),
    )


def meal_targets(kcal_giornaliere: float, meal: MealSpec) -> MacroTargets:
    """Target in grammi per un pasto a partire dalle kcal giornaliere."""
    kcal_pasto = kcal_giornaliere * meal.kcal_percent
    return kcal_to_macro_targets(kcal_pasto, meal.macro_split.as_dict())
