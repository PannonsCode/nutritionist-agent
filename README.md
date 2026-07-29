# Nutritionist Agent

Agente AI per la generazione automatica di piani alimentari bilanciati a partire
da kcal target e percentuali di macronutrienti per pasto.

## Idea chiave: il bilanciamento è un sistema lineare

Per ogni pasto si conoscono i grammi target di **carboidrati (C)**, **proteine (P)**
e **grassi (G)**. Scegliendo **un alimento-fonte per ciascun macro** (1 carbo, 1
proteina, 1 lipide) con grammature `x_C, x_P, x_G`, il bilanciamento diventa:

```
[carbo_carbo  carbo_prot  carbo_gras] [x_C]   [C]
[prot_carbo   prot_prot   prot_gras ] [x_P] = [P]
[gras_carbo   gras_prot   gras_gras ] [x_G]   [G]
```

dove i coefficienti sono i grammi di macro **per grammo di alimento**. Si risolve
con `numpy.linalg.solve`. Scegliere alimenti "puri" (macro dominante alto, altri
~0) rende la matrice **diagonalmente dominante** → soluzione positiva, realistica
e con **errore kcal ~0** (l'unico residuo viene dall'arrotondamento a 5 g).

Il sistema prova molte combinazioni dei pool più puri e ordina per: preferenze →
errore kcal → errore macro → purezza. Macro a 0 nel pasto riducono il sistema
(2×2 o 1×1) automaticamente.

## Struttura

```
nutri/
  config.py     parametri (purezza, porzioni, categorie preferite, modello LLM)
  models.py     schemi Pydantic (PlanRequest, MealSpec, FoodPortion, ...)
  macros.py     kcal -> grammi di macro (sezioni 3-4 dei requisiti)
  food_db.py    carica il CSV e classifica gli alimenti per macro dominante
  solver.py     sistema lineare 3x3 + ricerca combinazioni (vettoriale)
  planner.py    pasto -> piano giornaliero / settimanale con varietà
  tools.py      tool deterministici esposti agli agenti
  agents.py     team multi-agente Agno (Claude) sopra ai tool
api/
  main.py       mock FE / API FastAPI
web/index.html  mock FE (servito su / )
main.py         demo CLI del motore (senza LLM)
data/
  alimenti.csv  database nutrizionale IN USO (macro per 100 g)
filtra_alimenti.py   script che rigenera un CSV dal dataset grezzo
```

`provvisorio.py` è la bozza iniziale: la sua logica è stata rifattorizzata in
`nutri/macros.py` e `nutri/models.py`.

### Cambiare database alimenti

Metti il CSV che vuoi usare in **`data/alimenti.csv`** (oppure punta altrove con
la variabile d'ambiente `NUTRI_FOOD_CSV`). Il loader è tollerante:

- **separatore** rilevato automaticamente (`;`, `,` o tab);
- **nomi delle colonne** risolti via alias (`COLUMN_ALIASES` in `nutri/config.py`):
  es. la colonna kcal può chiamarsi `energia_kcal` o `kcal`, i carboidrati
  `carboidrati_disponibili` o `carboidrati`, ecc. Servono almeno le colonne di
  proteine, lipidi e carboidrati; la colonna kcal è facoltativa (le kcal si
  ricalcolano dai macro con Atwater 4/4/9). Se un file ha nomi diversi, aggiungi
  l'alias in `COLUMN_ALIASES`.

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # inserisci ANTHROPIC_API_KEY solo se vuoi usare /chat
```

## Uso

**Demo CLI (deterministica, nessuna API key):**
```bash
python main.py
```

**API / mock FE:**
```bash
uvicorn api.main:app --reload
# poi apri http://127.0.0.1:8000/docs per la UI interattiva
```

Esempio di richiesta a `POST /plan`:
```json
{
  "kcal_target": 2000,
  "pasti": [
    {"nome": "Colazione", "kcal_percent": 0.3, "macro_split": {"carbo": 0.55, "proteine": 0.25, "grassi": 0.20}},
    {"nome": "Pranzo",    "kcal_percent": 0.4, "macro_split": {"carbo": 0.50, "proteine": 0.30, "grassi": 0.20}},
    {"nome": "Cena",      "kcal_percent": 0.3, "macro_split": {"carbo": 0.45, "proteine": 0.35, "grassi": 0.20}}
  ],
  "alimenti_preferiti": ["pollo", "tonno"],
  "alimenti_esclusi": [],
  "categorie_escluse": []
}
```

| Endpoint | Descrizione |
|----------|-------------|
| `POST /plan` | piano giornaliero: 1 combinazione bilanciata (errore kcal ~0) |
| `POST /plan/options` | per ogni pasto, **liste di alimenti equivalenti per macro** (scegline 1 per categoria) |
| `POST /plan/week` | piano settimanale (7 giorni vari ed equivalenti) |
| `POST /meal/alternatives` | alternative equivalenti per un pasto |
| `GET /foods/{macro}` | alimenti-fonte per `carbo`/`proteine`/`grassi` |
| `POST /chat` | dialogo col team Agno (richiede `ANTHROPIC_API_KEY`) |

## Tuning della qualità degli alimenti

L'ordinamento di ogni pool segue 4 criteri (in `nutri/food_db.pool`):

1. **categoria staple** preferita per il macro (`PREFERRED_CATEGORIES`):
   cereali/legumi per i carbo, carni/pesce/uova/latticini per le proteine,
   oli/frutta secca per i grassi;
2. **alimenti comuni**: i termini "esotici" (`UNCOMMON_TERMS`: selvaggina,
   pesci/ingredienti insoliti) vengono demoti;
3. **crudo prima di cotto** (`PREFER_RAW`): le versioni cotte/in scatola vanno
   in fondo — è anche la prassi di prescrivere il peso a crudo;
4. **purezza** del macro dominante.

Puoi inoltre guidare la selezione con `alimenti_preferiti`, `alimenti_esclusi` e
`categorie_escluse` nella richiesta.

Parametri regolabili in `nutri/config.py`: `MIN_PURITY`, `MIN_DENSITY`,
`MIN_PORTION_G`, `MAX_PORTION_G`, `TOP_K_PER_POOL`, `PREFERRED_CATEGORIES`,
`PREFER_RAW`, `UNCOMMON_TERMS`.
