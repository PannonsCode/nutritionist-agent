"""Demo CLI del motore di pianificazione nutrizionale (senza LLM).

Esegui:  python main.py
Genera un piano giornaliero e ne stampa il bilanciamento con l'errore in kcal.
Per l'API/chatbot usa:  uvicorn api.main:app --reload
"""
from nutri.models import MacroSplit, MealSpec, PlanRequest
from nutri.planner import build_day


def stampa_pasto(p):
    t = p.target
    print(f"\n{p.nome}  | target {t.kcal:.0f} kcal  (C {t.carbo_g:.0f}g / P {t.proteine_g:.0f}g / G {t.grassi_g:.0f}g)")
    for a in p.alimenti:
        print(
            f"   - {a.grammi:6.0f} g  {a.nome[:40]:40s} [{a.ruolo:8s}]"
            f"  C{a.carbo_g}/P{a.proteine_g}/G{a.grassi_g}  {a.kcal} kcal"
        )
    print(f"   = ottenute {p.kcal_ottenute} kcal | errore {p.errore_kcal:+.1f} kcal ({p.errore_pct:+.2f}%)")


if __name__ == "__main__":
    req = PlanRequest(
        kcal_target=2500,
        pasti=[
            MealSpec(nome="Colazione", kcal_percent=0.25, macro_split=MacroSplit(carbo=0.6, proteine=0.3, grassi=0.1)),
            MealSpec(nome="Pranzo", kcal_percent=0.35, macro_split=MacroSplit(carbo=0.5, proteine=0.3, grassi=0.2)),
            MealSpec(nome="Cena", kcal_percent=0.40, macro_split=MacroSplit(carbo=0.45, proteine=0.35, grassi=0.2)),
        ],
        alimenti_preferiti=["pollo", "riso", "tonno"],
    )

    day = build_day(req)
    print(f"\n=== PIANO GIORNALIERO — {req.kcal_target:.0f} kcal target ===")
    for p in day.pasti:
        stampa_pasto(p)
    print(f"\nTOTALE GIORNO: {day.kcal_totali} kcal (target {req.kcal_target:.0f}) | errore {day.errore_kcal_giorno:+.1f} kcal")
