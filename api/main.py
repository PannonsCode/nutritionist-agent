"""Mock FE / API per testare il motore di pianificazione nutrizionale.

Endpoint:
  GET  /                  -> health check + info
  POST /plan              -> piano giornaliero deterministico (no LLM, istantaneo)
  POST /plan/week         -> piano settimanale deterministico
  POST /meal/alternatives -> alternative equivalenti per un pasto
  GET  /foods/{macro}     -> alimenti-fonte per un macro
  POST /chat              -> dialogo con il team Agno (richiede ANTHROPIC_API_KEY)

Avvio:  uvicorn api.main:app --reload
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from nutri.config import LLM_API_KEY_ENV, LLM_PROVIDER
from nutri.food_db import get_db
from nutri.models import DayOptions, DayPlan, MealResult, PlanRequest, WeekPlan
from nutri.planner import build_day, build_day_options, build_week
from nutri.solver import meal_alternatives
from nutri.macros import kcal_to_macro_targets

load_dotenv()

app = FastAPI(
    title="Nutritionist Agent API",
    description="Genera piani alimentari bilanciati a partire da kcal e percentuali.",
    version="0.1.0",
)


WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@app.get("/", include_in_schema=False)
def ui() -> FileResponse:
    """Mock FE: form per /plan/options."""
    return FileResponse(
        WEB_DIR / "index.html",
        headers={"Cache-Control": "no-store"},  # in dev: niente cache del browser
    )


@app.get("/categories")
def categories() -> dict:
    """Categorie alimentari del CSV + quelle 'consigliate' + i tipi di pasto."""
    from nutri.config import MEAL_TYPES, SUGGESTED_CATEGORIES

    db = get_db()
    present = {f.categoria for f in db.foods if f.categoria}
    cats = sorted(present)
    consigliate = [c for c in SUGGESTED_CATEGORIES if c in present]
    tipi_pasto = db.meal_types() or MEAL_TYPES
    return {"categorie": cats, "consigliate": consigliate, "tipi_pasto": tipi_pasto}


@app.get("/food")
def food_lookup(nome: str) -> dict:
    """Cerca un alimento per nome e restituisce i macro per 100g (per add_food del FE)."""
    db = get_db()
    f = db.get(nome)
    if f is None:
        # match a token: tutti i termini della query devono comparire nel nome
        import re
        tokens = [t for t in re.split(r"[^a-zà-ù0-9]+", nome.strip().lower()) if t]
        cand = [x for x in db.foods if all(t in x.nome.lower() for t in tokens)] if tokens else []
        if cand:
            f = min(cand, key=lambda x: len(x.nome))  # match più "stretto"
    if f is None:
        raise HTTPException(status_code=404, detail=f"Alimento non trovato: {nome}")
    return {
        "nome": f.nome,
        "categoria": f.categoria,
        "carbo_100": f.carbo_100,
        "proteine_100": f.proteine_100,
        "grassi_100": f.grassi_100,
        "kcal_100": round(f.kcal_100_atwater(), 1),
    }


class AssistantRequest(BaseModel):
    messaggio: str
    stato: Optional[dict] = None
    session_id: Optional[str] = None


@app.post("/assistant")
def assistant(req: AssistantRequest) -> dict:
    """Dialoga con l'agente e restituisce testo + azioni strutturate per il FE."""
    if not os.getenv(LLM_API_KEY_ENV):
        raise HTTPException(
            status_code=503,
            detail=f"{LLM_API_KEY_ENV} non impostata: l'assistente richiede una chiave per il provider '{LLM_PROVIDER}'.",
        )
    import asyncio
    import json

    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    from nutri.agents import build_assistant_agent
    from nutri.models import AssistantResponse

    stato_json = json.dumps(req.stato or {}, ensure_ascii=False)
    prompt = f"STATO ATTUALE DEL PIANO (JSON):\n{stato_json}\n\nMESSAGGIO UTENTE:\n{req.messaggio}"
    sid = (req.session_id or "").strip() or None

    agent = build_assistant_agent()
    run = agent.run(prompt, session_id=sid)
    content = getattr(run, "content", run)
    return _parse_assistant(content, AssistantResponse)


def _parse_assistant(content, AssistantResponse) -> dict:
    """Estrae e valida il JSON prodotto dall'agente; fallback a solo testo."""
    import json
    import re

    if not isinstance(content, str):
        content = str(content)
    txt = content.strip()
    # rimuovi eventuali fence markdown
    txt = re.sub(r"^```(?:json)?|```$", "", txt, flags=re.MULTILINE).strip()
    start, end = txt.find("{"), txt.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            data = json.loads(txt[start : end + 1])
            return AssistantResponse.model_validate(data).model_dump()
        except Exception:
            pass
    return {"risposta": content, "azioni": []}


@app.get("/health")
def health() -> dict:
    db = get_db()
    return {
        "status": "ok",
        "alimenti_caricati": len(db.foods),
        "pool_per_macro": db.stats(),
        "endpoints": ["/plan", "/plan/options", "/plan/week", "/meal/alternatives", "/foods/{macro}", "/chat"],
    }


@app.post("/plan", response_model=DayPlan)
def plan_day(req: PlanRequest) -> DayPlan:
    """Piano giornaliero deterministico."""
    try:
        return build_day(req)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.post("/plan/options", response_model=DayOptions)
def plan_options(
    req: PlanRequest,
    max_carbo: Optional[int] = None,
    max_proteine: Optional[int] = None,
    max_grassi: Optional[int] = None,
) -> DayOptions:
    """Per ogni pasto, liste di alimenti equivalenti per categoria (carbo/proteine/grassi).

    Il nutrizionista sceglie 1 alimento per categoria: ogni opzione della stessa
    lista fornisce la stessa quantità di quel macro. I parametri max_* limitano il
    numero di opzioni per ciascun macro (ognuno il suo); se ne trova meno, ok.
    Se omessi si usano i default di MAX_OPTIONS_PER_MACRO.
    """
    max_per_macro = {
        "carbo": max_carbo,
        "proteine": max_proteine,
        "grassi": max_grassi,
    }
    try:
        return build_day_options(req, max_per_macro=max_per_macro)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.post("/plan/week", response_model=WeekPlan)
def plan_week(req: PlanRequest) -> WeekPlan:
    """Piano settimanale deterministico (7 giorni vari ed equivalenti)."""
    try:
        return build_week(req)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


class MealAltRequest(BaseModel):
    nome: str = "Pasto"
    kcal_pasto: float
    perc_carboidrati: float
    perc_proteine: float
    perc_grassi: float
    n: int = 5


@app.post("/meal/alternatives", response_model=List[MealResult])
def meal_alts(req: MealAltRequest) -> List[MealResult]:
    """Alternative equivalenti per un singolo pasto."""
    target = kcal_to_macro_targets(
        req.kcal_pasto,
        {"carbo": req.perc_carboidrati, "proteine": req.perc_proteine, "grassi": req.perc_grassi},
    )
    return meal_alternatives(get_db(), req.nome, target, n=req.n)


@app.get("/foods/{macro}")
def foods_for_macro(macro: str, n: int = 20) -> dict:
    """Elenco degli alimenti-fonte migliori per un macro."""
    if macro not in ("carbo", "proteine", "grassi"):
        raise HTTPException(status_code=400, detail="macro deve essere carbo|proteine|grassi")
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


class ChatRequest(BaseModel):
    messaggio: str
    # Opzionale: etichetta libera per mantenere la memoria della conversazione tra
    # più messaggi (es. "paziente-123"). Lascialo vuoto/ometti per una domanda secca.
    session_id: Optional[str] = None


@app.post("/chat")
def chat(req: ChatRequest) -> dict:
    """Dialogo in linguaggio naturale con il team Agno (stile chatbot)."""
    if not os.getenv(LLM_API_KEY_ENV):
        raise HTTPException(
            status_code=503,
            detail=f"{LLM_API_KEY_ENV} non impostata: l'endpoint /chat richiede una chiave per il provider '{LLM_PROVIDER}'.",
        )
    # Python 3.9: FastAPI esegue gli endpoint sync in un thread del threadpool
    # privo di event loop; agno crea asyncio.Lock() (all'import e durante run),
    # il cui costruttore su 3.9 richiede un loop. Garantiamone uno nel thread.
    import asyncio

    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    # Import lazy: il team carica il modello solo quando serve.
    from nutri.agents import build_nutrition_team

    sid = (req.session_id or "").strip() or None  # "" -> None
    team = build_nutrition_team()
    run = team.run(req.messaggio, session_id=sid)
    return {"risposta": getattr(run, "content", str(run))}
