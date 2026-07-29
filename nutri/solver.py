"""Bilanciamento di un pasto: scelta alimenti + grammature con errore kcal ~0.

Idea: per un pasto con target (C, P, F) grammi scegliamo 1 alimento-fonte per
ciascun macro attivo (carbo/proteine/grassi) e risolviamo il sistema lineare

    M @ x = t

dove le colonne di M sono i macro-per-grammo degli alimenti scelti, t è il
vettore target in grammi e x sono le grammature da assumere. Alimenti "puri"
(macro dominante alto, altri ~0) rendono M diagonalmente dominante -> x > 0 e
realistico, con errore residuo dovuto solo all'arrotondamento delle grammature.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np

from .config import (
    KCAL_PER_G,
    MAX_PORTION_G,
    MIN_PORTION_G,
    TOP_K_PER_POOL,
)
from .food_db import Food, FoodDB
from .models import FoodPortion, MacroOption, MacroTargets, MealResult

MACROS = ("carbo", "proteine", "grassi")
_ATTR = {"carbo": "carbo_100", "proteine": "proteine_100", "grassi": "grassi_100"}
# Sotto questa soglia di grammi target il macro è considerato "non attivo".
_MIN_TARGET_G = 1.0


def _round_portion(grams, step: float = 5.0):
    """Arrotonda al multiplo di `step` g. Funziona su scalari e array numpy."""
    return np.round(grams / step) * step


def _achieved(foods: List[Food], grams: List[float]) -> Dict[str, float]:
    """Macro e kcal totali ottenuti dalle porzioni (su tutti e 3 i macro)."""
    out = {"carbo": 0.0, "proteine": 0.0, "grassi": 0.0, "kcal": 0.0}
    for f, g in zip(foods, grams):
        out["carbo"] += f.per_gram("carbo") * g
        out["proteine"] += f.per_gram("proteine") * g
        out["grassi"] += f.per_gram("grassi") * g
        out["kcal"] += f.kcal_per_gram() * g
    return out


@dataclass
class Candidate:
    foods: List[Food]
    grams: List[float]
    kcal_err: float       # ottenute - target (con segno)
    macro_l1: float       # somma |errori| sui 3 macro in grammi
    mean_purity: float


def _search_candidates(
    db: FoodDB,
    target: MacroTargets,
    *,
    esclusi: Optional[List[str]] = None,
    categorie_escluse: Optional[List[str]] = None,
    categorie_incluse: Optional[List[str]] = None,
    pasto: Optional[str] = None,
    preferiti: Optional[List[str]] = None,
    top_k: int = TOP_K_PER_POOL,
    max_results: int = 8,
) -> List[Candidate]:
    """Cerca le migliori combinazioni di alimenti per il pasto."""
    target_map = {
        "carbo": target.carbo_g,
        "proteine": target.proteine_g,
        "grassi": target.grassi_g,
    }
    active = [m for m in MACROS if target_map[m] >= _MIN_TARGET_G]
    if not active:
        return []

    pools = [
        db.pool(
            m,
            esclusi=esclusi,
            categorie_escluse=categorie_escluse,
            categorie_incluse=categorie_incluse,
            pasto=pasto,
        )[:top_k]
        for m in active
    ]
    if any(len(p) == 0 for p in pools):
        return []

    m = len(active)
    active_idx = [MACROS.index(a) for a in active]   # righe macro attive (0=carbo,1=prot,2=grassi)
    t = np.array([target_map[a] for a in active], dtype=float)
    target_full = np.array([target.carbo_g, target.proteine_g, target.grassi_g])
    preferiti_l = {p.lower().strip() for p in (preferiti or []) if p and p.strip()}

    # Per ogni pool: macro-per-grammo completi (L,3), kcal/g (L,), purezza (L,), flag preferito (L,).
    def pool_arrays(pool):
        macro = np.array(
            [[f.per_gram("carbo"), f.per_gram("proteine"), f.per_gram("grassi")] for f in pool]
        )
        kcalpg = np.array([f.kcal_per_gram() for f in pool])
        purity = np.array([f.purezza for f in pool])
        pref = np.array(
            [any(term in f.nome.lower() for term in preferiti_l) for f in pool], dtype=bool
        )
        return macro, kcalpg, purity, pref

    arrays = [pool_arrays(p) for p in pools]

    # Griglia di indici: una combinazione = (i0, i1, ...) un alimento per macro attivo.
    grids = np.meshgrid(*[np.arange(len(p)) for p in pools], indexing="ij")
    idxs = [g.ravel() for g in grids]
    n = idxs[0].size

    # Costruzione vettoriale delle matrici Ms (n, m, m): colonna j = macro dell'alimento j.
    Ms = np.empty((n, m, m))
    full_macro_sel = [arrays[j][0][idxs[j]] for j in range(m)]   # ogni (n,3)
    for j in range(m):
        Ms[:, :, j] = full_macro_sel[j][:, active_idx]

    # Risolvi M @ x = t per tutte le combo non singolari in un solo batch.
    dets = np.linalg.det(Ms)
    ok = np.abs(dets) > 1e-9
    xs = np.full((n, m), np.nan)
    if np.any(ok):
        b = np.broadcast_to(t.reshape(m, 1), (int(ok.sum()), m, 1))
        xs[ok] = np.linalg.solve(Ms[ok], b)[:, :, 0]

    # Arrotonda le grammature e filtra per vincoli di porzione (vettoriale).
    grams = _round_portion(xs)
    valid = (
        np.all(np.isfinite(grams), axis=1)
        & np.all(grams >= MIN_PORTION_G, axis=1)
        & np.all(grams <= MAX_PORTION_G, axis=1)
    )
    if not np.any(valid):
        return []

    # Macro e kcal ottenuti (da grammi arrotondati), errori e purezza media — vettoriale.
    ach = np.zeros((n, 3))
    kcal = np.zeros(n)
    purity_sum = np.zeros(n)
    pref_any = np.zeros(n, dtype=bool)
    for j in range(m):
        ach += full_macro_sel[j] * grams[:, j : j + 1]
        kcal += arrays[j][1][idxs[j]] * grams[:, j]
        purity_sum += arrays[j][2][idxs[j]]
        pref_any |= arrays[j][3][idxs[j]]
    kcal_err = kcal - target.kcal
    macro_l1 = np.abs(ach - target_full).sum(axis=1)
    mean_purity = purity_sum / m

    # Ordina le combo valide: preferiti, errore kcal, errore macro, purezza.
    vi = np.where(valid)[0]
    order = sorted(
        vi,
        key=lambda i: (
            0 if pref_any[i] else 1,
            round(abs(float(kcal_err[i])), 1),
            round(float(macro_l1[i]), 1),
            -float(mean_purity[i]),
        ),
    )

    candidates: List[Candidate] = []
    for i in order[:max_results]:
        foods = [pools[j][idxs[j][i]] for j in range(m)]
        candidates.append(
            Candidate(
                foods=foods,
                grams=[float(grams[i, j]) for j in range(m)],
                kcal_err=float(kcal_err[i]),
                macro_l1=float(macro_l1[i]),
                mean_purity=float(mean_purity[i]),
            )
        )
    return candidates


_MACRO_ATTR = {"carbo": "carbo_100", "proteine": "proteine_100", "grassi": "grassi_100"}


def contribution_targets(
    db: FoodDB,
    target: MacroTargets,
    *,
    max_per_macro: Dict[str, int],
    esclusi: Optional[List[str]] = None,
    categorie_escluse: Optional[List[str]] = None,
    categorie_incluse: Optional[List[str]] = None,
    pasto: Optional[str] = None,
) -> Dict[str, float]:
    """Quanto deve fornire ciascun macro dal "proprio" alimento, al netto degli
    incidentali apportati dagli altri due.

    Risolve un sistema 3x3 sulle MEDIE dei pool (alimento medio per macro): la
    soluzione dà le grammature rappresentative, da cui il contributo proprio di
    ogni macro. Usando questi contributi (anziché il target pieno) per dimensionare
    le opzioni, la media "1 alimento per macro" torna ~ target.
    """
    target_map = {"carbo": target.carbo_g, "proteine": target.proteine_g, "grassi": target.grassi_g}
    pools = {
        m: db.pool(
            m, esclusi=esclusi, categorie_escluse=categorie_escluse,
            categorie_incluse=categorie_incluse, pasto=pasto,
        )[: max_per_macro.get(m, TOP_K_PER_POOL)]
        for m in MACROS
    }
    active = [m for m in MACROS if target_map[m] >= _MIN_TARGET_G and pools[m]]
    contrib = dict(target_map)  # default: target pieno (nessuna compensazione)
    if not active:
        return contrib

    idx = {"carbo": 0, "proteine": 1, "grassi": 2}

    def meanvec(pool):  # media [carbo, proteine, grassi] per grammo
        arr = np.array([[f.per_gram("carbo"), f.per_gram("proteine"), f.per_gram("grassi")] for f in pool])
        return arr.mean(axis=0)

    means = {m: meanvec(pools[m]) for m in active}
    # M[riga macro][colonna alimento]: contributo del macro 'riga' dall'alimento 'colonna'
    M = np.array([[means[col][idx[row]] for col in active] for row in active])
    b = np.array([target_map[m] for m in active])
    try:
        x = np.linalg.solve(M, b)
    except np.linalg.LinAlgError:
        return contrib
    for j, m in enumerate(active):
        own = means[m][idx[m]] * x[j]  # macro proprio fornito dall'alimento medio
        contrib[m] = float(own) if own > 0 else target_map[m]
    return contrib


def macro_equivalents(
    db: FoodDB,
    target: MacroTargets,
    macro: str,
    *,
    n: int = 8,
    esclusi: Optional[List[str]] = None,
    categorie_escluse: Optional[List[str]] = None,
    categorie_incluse: Optional[List[str]] = None,
    pasto: Optional[str] = None,
    preferiti: Optional[List[str]] = None,
    target_g_override: Optional[float] = None,
) -> List[MacroOption]:
    """Lista di alimenti-fonte per `macro`, ciascuno con la grammatura che fornisce
    il target (o il contributo) di quel macro nel pasto.

    grammi = target_g / (macro_per_100g / 100). Se `target_g_override` è dato
    (contributo compensato), si usa quello al posto del target pieno.
    Le opzioni restituite sono ordinate per contenuto del macro crescente.
    """
    target_g = target_g_override if target_g_override is not None else {
        "carbo": target.carbo_g,
        "proteine": target.proteine_g,
        "grassi": target.grassi_g,
    }[macro]
    if target_g < _MIN_TARGET_G:
        return []

    pool = db.pool(
        macro,
        esclusi=esclusi,
        categorie_escluse=categorie_escluse,
        categorie_incluse=categorie_incluse,
        pasto=pasto,
    )
    pref_l = {p.lower().strip() for p in (preferiti or []) if p and p.strip()}
    if pref_l:  # alimenti preferiti in cima, mantenendo l'ordine relativo
        pool = sorted(
            pool, key=lambda f: 0 if any(t in f.nome.lower() for t in pref_l) else 1
        )

    out: List[MacroOption] = []
    for f in pool:
        pg = f.per_gram(macro)
        if pg <= 0:
            continue
        grams = float(_round_portion(target_g / pg))
        if grams < MIN_PORTION_G or grams > MAX_PORTION_G:
            continue
        out.append(
            MacroOption(
                nome=f.nome,
                categoria=f.categoria,
                grammi=grams,
                kcal=round(f.kcal_per_gram() * grams, 1),
                carbo_g=round(f.per_gram("carbo") * grams, 1),
                proteine_g=round(f.per_gram("proteine") * grams, 1),
                grassi_g=round(f.per_gram("grassi") * grams, 1),
                carbo_100=f.carbo_100,
                proteine_100=f.proteine_100,
                grassi_100=f.grassi_100,
            )
        )
        if len(out) >= n:
            break
    # ordina per contenuto del macro crescente (porzioni decrescenti)
    out.sort(key=lambda o: getattr(o, _MACRO_ATTR[macro]))
    return out


def diagnose_infeasibility(
    db: FoodDB,
    target: MacroTargets,
    *,
    esclusi: Optional[List[str]] = None,
    categorie_escluse: Optional[List[str]] = None,
    categorie_incluse: Optional[List[str]] = None,
    pasto: Optional[str] = None,
) -> str:
    """Spiega perché un pasto non è bilanciabile con 1 alimento per macro.

    Per ogni macro confronta i grammi target con quelli ottenibili dall'alimento
    più "denso" disponibile, dato il limite MAX_PORTION_G per porzione.
    """
    target_map = {
        "carbo": target.carbo_g,
        "proteine": target.proteine_g,
        "grassi": target.grassi_g,
    }
    problemi: List[str] = []
    for m in MACROS:
        tg = target_map[m]
        if tg < _MIN_TARGET_G:
            continue
        # Stesso spazio di ricerca del solver: solo i primi TOP_K_PER_POOL alimenti.
        pool = db.pool(
            m,
            esclusi=esclusi,
            categorie_escluse=categorie_escluse,
            categorie_incluse=categorie_incluse,
            pasto=pasto,
        )[:TOP_K_PER_POOL]
        if not pool:
            extra = f" per il pasto '{pasto}'" if pasto else ""
            problemi.append(f"nessun alimento disponibile come fonte di {m}{extra}")
            continue
        best_dens = max(f.per_gram(m) for f in pool)  # g macro per g alimento
        min_g = tg / best_dens if best_dens else float("inf")
        if min_g > MAX_PORTION_G:
            top = max(pool, key=lambda f: f.per_gram(m))
            problemi.append(
                f"servono {tg:.0f}g di {m}: anche con l'alimento più ricco "
                f"('{top.nome}', {top.per_gram(m)*100:.1f}g/100g) servirebbero "
                f"~{min_g:.0f}g, oltre il limite di {MAX_PORTION_G:.0f}g per porzione"
            )
    if not problemi:
        return (
            "nessuna combinazione valida trovata (prova ad allargare TOP_K_PER_POOL "
            "o a rivedere le esclusioni)"
        )
    return "; ".join(problemi)


def _candidate_to_result(name: str, target: MacroTargets, c: Candidate) -> MealResult:
    portions: List[FoodPortion] = []
    for f, g in zip(c.foods, c.grams):
        portions.append(
            FoodPortion(
                nome=f.nome,
                categoria=f.categoria,
                ruolo=f.ruolo,
                grammi=g,
                kcal=round(f.kcal_per_gram() * g, 1),
                carbo_g=round(f.per_gram("carbo") * g, 1),
                proteine_g=round(f.per_gram("proteine") * g, 1),
                grassi_g=round(f.per_gram("grassi") * g, 1),
            )
        )
    ach = _achieved(c.foods, c.grams)
    err_pct = (c.kcal_err / target.kcal * 100.0) if target.kcal else 0.0
    return MealResult(
        nome=name,
        target=target,
        alimenti=portions,
        kcal_ottenute=round(ach["kcal"], 1),
        carbo_ottenuti=round(ach["carbo"], 1),
        proteine_ottenute=round(ach["proteine"], 1),
        grassi_ottenuti=round(ach["grassi"], 1),
        errore_kcal=round(c.kcal_err, 1),
        errore_pct=round(err_pct, 2),
    )


def balance_meal(
    db: FoodDB,
    nome: str,
    target: MacroTargets,
    *,
    esclusi: Optional[List[str]] = None,
    categorie_escluse: Optional[List[str]] = None,
    categorie_incluse: Optional[List[str]] = None,
    pasto: Optional[str] = None,
    preferiti: Optional[List[str]] = None,
    variant: int = 0,
) -> Optional[MealResult]:
    """Bilancia un pasto e restituisce un MealResult.

    `variant` seleziona alternative diverse (per la varietà settimanale):
    0 = combinazione migliore, 1 = seconda, ecc. (con wrap-around).
    """
    candidates = _search_candidates(
        db,
        target,
        esclusi=esclusi,
        categorie_escluse=categorie_escluse,
        categorie_incluse=categorie_incluse,
        pasto=pasto,
        preferiti=preferiti,
    )
    if not candidates:
        return None
    chosen = candidates[variant % len(candidates)]
    return _candidate_to_result(nome, target, chosen)


def meal_alternatives(
    db: FoodDB,
    nome: str,
    target: MacroTargets,
    *,
    esclusi: Optional[List[str]] = None,
    categorie_escluse: Optional[List[str]] = None,
    categorie_incluse: Optional[List[str]] = None,
    pasto: Optional[str] = None,
    preferiti: Optional[List[str]] = None,
    n: int = 5,
) -> List[MealResult]:
    """Restituisce fino a `n` alternative equivalenti per lo stesso pasto."""
    candidates = _search_candidates(
        db,
        target,
        esclusi=esclusi,
        categorie_escluse=categorie_escluse,
        categorie_incluse=categorie_incluse,
        pasto=pasto,
        preferiti=preferiti,
        max_results=n,
    )
    return [_candidate_to_result(nome, target, c) for c in candidates]
