"""Team multi-agente Agno (Claude) sopra ai tool deterministici.

Architettura:
  - macro_agent     -> calcola macro e conosce le fonti alimentari
  - selection_agent -> bilancia singoli pasti e propone alternative
  - plan_agent      -> genera piani giornalieri/settimanali completi
  - nutrition_team  -> coordinatore che instrada la richiesta del nutrizionista

Gli agenti NON fanno calcoli "a mano": delegano sempre ai tool, che sono
deterministici e garantiscono errore kcal ~0. L'LLM serve per capire la
richiesta in linguaggio naturale e per il dialogo stile chatbot (sezione 8).
"""
from __future__ import annotations

from agno.agent import Agent
from agno.models.anthropic import Claude
from agno.team import Team

from .config import LLM_MODEL_ID
from .tools import MACRO_TOOLS, PLAN_TOOLS, SELECTION_TOOLS


def _model() -> Claude:
    return Claude(id=LLM_MODEL_ID)


def build_macro_agent() -> Agent:
    return Agent(
        name="MacroAgent",
        model=_model(),
        tools=MACRO_TOOLS,
        description="Esperto di calcolo dei macronutrienti a partire dalle kcal.",
        instructions=[
            "Converti kcal e percentuali in grammi di carboidrati, proteine e grassi.",
            "Usa SEMPRE il tool calcola_macronutrienti, non calcolare a mente.",
            "Le percentuali vanno espresse come frazioni (es. 50% -> 0.5).",
        ],
        markdown=True,
    )


def build_selection_agent() -> Agent:
    return Agent(
        name="SelectionAgent",
        model=_model(),
        tools=SELECTION_TOOLS,
        description="Seleziona alimenti e grammature per bilanciare un pasto.",
        instructions=[
            "Per bilanciare un pasto usa bilancia_pasto; per alternative usa alternative_pasto.",
            "Rispetta esclusioni, allergie e preferenze indicate dal nutrizionista.",
            "Riporta sempre l'errore in kcal del bilanciamento ottenuto.",
        ],
        markdown=True,
    )


def build_plan_agent() -> Agent:
    return Agent(
        name="PlanAgent",
        model=_model(),
        tools=PLAN_TOOLS,
        description="Genera piani alimentari giornalieri e settimanali completi.",
        instructions=[
            "Costruisci il JSON della richiesta (kcal_target, pasti con kcal_percent e "
            "macro_split) e chiama genera_piano o genera_piano_settimanale.",
            "Verifica che le percentuali kcal dei pasti sommino a 1 e i macro di ogni "
            "pasto sommino a 1.",
            "Presenta il piano in tabella con grammature, kcal per pasto ed errore totale.",
        ],
        markdown=True,
    )


ASSISTANT_INSTRUCTIONS = [
    "Sei l'assistente di un nutrizionista dentro un'app per piani alimentari.",
    "Ricevi: (1) lo STATO attuale del piano in JSON e (2) un messaggio dell'utente.",
    "Rispondi SEMPRE con: 'risposta' (testo in italiano, breve e chiaro) e 'azioni' "
    "(lista di azioni che l'app applicherà; vuota se non servono modifiche).",
    "",
    "Tipi di azione disponibili:",
    "- set_config: imposta/ricrea il piano. Campi: kcal_target (numero) e pasti = lista di "
    "{nome, tipo_pasto(colazione|pranzo|cena|spuntino), kcal_percent, carbo, proteine, grassi, "
    "categorie_incluse}. ATTENZIONE: kcal_percent e i macro vanno espressi come FRAZIONI 0-1 "
    "(es. 50% -> 0.5). I kcal_percent dei pasti devono sommare a 1; i macro di ogni pasto a 1.",
    "- add_food: aggiungi un alimento. Campi: pasto (nome), macro (carbo|proteine|grassi), "
    "nome (dell'alimento), grammi (opzionale). NON inventare i valori nutrizionali: l'app li "
    "ricava dal database dal nome. Specifica carbo_100/proteine_100/grassi_100 SOLO per un "
    "alimento personalizzato non presente in archivio.",
    "- remove_food: rimuovi un alimento. Campi: pasto, macro, nome.",
    "- set_grams: cambia i grammi. Campi: pasto, macro, nome, grammi.",
    "- toggle_food: seleziona/deseleziona. Campi: pasto, macro, nome, selezionato (true/false).",
    "",
    "Riferisciti ai pasti col loro 'nome' come appare nello stato. Se l'utente dà la "
    "configurazione iniziale (kcal, pasti, percentuali), usa una sola azione set_config. "
    "Se chiede di aggiungere/togliere/modificare alimenti, usa le azioni specifiche. "
    "Se è solo una domanda informativa, lascia 'azioni' vuota e rispondi nel testo.",
    "",
    "FORMATO DI RISPOSTA: restituisci ESCLUSIVAMENTE un oggetto JSON valido, senza testo "
    "prima o dopo e senza blocchi markdown, con questa forma:",
    '{"risposta": "...", "azioni": [{"tipo": "...", ...campi...}]}',
    'Esempio set_config: {"risposta":"Ecco la configurazione.","azioni":[{"tipo":"set_config",'
    '"kcal_target":2000,"pasti":[{"nome":"Colazione","tipo_pasto":"colazione","kcal_percent":0.25,'
    '"carbo":0.55,"proteine":0.25,"grassi":0.20,"categorie_incluse":[]}]}]}',
    'Esempio add_food: {"risposta":"Aggiungo il tonno.","azioni":[{"tipo":"add_food","pasto":"Pranzo",'
    '"macro":"proteine","nome":"Tonno in salamoia, sgocciolato","grammi":120}]}',
]


def build_assistant_agent() -> Agent:
    """Agente che dialoga e restituisce azioni in JSON (parsate dal server)."""
    return Agent(
        name="Assistant",
        model=_model(),
        description="Assistente che modifica il piano nutrizionale tramite azioni.",
        instructions=ASSISTANT_INSTRUCTIONS,
        use_json_mode=True,
    )


def build_nutrition_team() -> Team:
    """Team coordinatore che instrada le richieste del nutrizionista."""
    return Team(
        name="NutritionTeam",
        model=_model(),
        members=[build_macro_agent(), build_selection_agent(), build_plan_agent()],
        instructions=[
            "Sei l'assistente di un nutrizionista per la creazione di piani alimentari.",
            "Instrada il calcolo dei macro a MacroAgent, il bilanciamento dei singoli "
            "pasti a SelectionAgent e la generazione dei piani a PlanAgent.",
            "Quando il nutrizionista chiede di ribilanciare o sostituire un alimento, "
            "rigenera la parte interessata mantenendo i macro target.",
            "Rispondi in italiano, in modo chiaro e con tabelle quando utile.",
        ],
        markdown=True,
    )
