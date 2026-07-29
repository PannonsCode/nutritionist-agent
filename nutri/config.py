"""Configurazione centrale del progetto."""
from __future__ import annotations

import os
from pathlib import Path

# --- Percorsi ---
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
# File del database in uso. Metti il CSV che vuoi usare in data/alimenti.csv,
# oppure punta a un altro percorso con la variabile d'ambiente NUTRI_FOOD_CSV.
DEFAULT_FOOD_CSV = Path(os.getenv("NUTRI_FOOD_CSV", DATA_DIR / "alimenti.csv"))
# Separatore: se è None viene rilevato automaticamente (';' o ',').
CSV_SEPARATOR = None

# Alias dei nomi di colonna: il loader prova questi nomi nell'ordine, così CSV
# con intestazioni diverse funzionano senza modificare il codice. La colonna kcal
# è facoltativa (le kcal si ricalcolano dai macro con Atwater 4/4/9).
COLUMN_ALIASES = {
    "nome": ["nome", "name", "alimento"],
    "categoria": ["categoria", "category", "gruppo"],
    "kcal": ["energia_kcal", "kcal", "energy_kcal", "energia", "calorie"],
    "proteine": ["proteine", "proteins", "protein", "prot"],
    "lipidi": ["lipidi", "grassi", "lipids", "fat", "fats"],
    "carbo": [
        "carboidrati_disponibili", "carboidrati", "carbs", "carbohydrates",
        "available_carbohydrates", "glucidi",
    ],
    # Lista (separata da virgola) dei pasti per cui l'alimento è consigliato.
    # Facoltativa: se assente, il filtro per tipo di pasto non viene applicato.
    "pasto": ["pasto_consigliato", "pasti_consigliati", "pasto", "pasti", "meal", "meals"],
}

# Tipi di pasto standard (fallback se il CSV non contiene la colonna pasto).
MEAL_TYPES = ["colazione", "pranzo", "cena", "spuntino"]

# --- Costanti nutrizionali (kcal per grammo di macronutriente) ---
KCAL_PER_G = {"carbo": 4.0, "proteine": 4.0, "grassi": 9.0}

# --- Classificazione alimenti per macro dominante ---
# Un alimento entra nel pool di un macro se quel macro fornisce almeno questa
# frazione delle kcal "da macro" dell'alimento (purezza minima).
MIN_PURITY = 0.55
# Densità minima del macro dominante (g per 100g) per evitare alimenti "vuoti".
MIN_DENSITY = {"carbo": 10.0, "proteine": 8.0, "grassi": 8.0}

# --- Vincoli sulle porzioni (grammi di alimento) ---
MIN_PORTION_G = 5.0
MAX_PORTION_G = 400.0

# --- Ricerca combinazioni nel solver ---
# Quanti alimenti più "puri" considerare per ciascun pool prima di combinarli.
TOP_K_PER_POOL = 25

# Numero MASSIMO di alimenti-opzione da mostrare per ciascun macro in /plan/options.
# Ogni macro ha il suo limite; se ne vengono trovati di meno non è un problema.
MAX_OPTIONS_PER_MACRO = {"carbo": 10, "proteine": 10, "grassi": 6}

# Categorie "staple" preferite come fonte primaria di ciascun macro. Gli alimenti
# di queste categorie vengono ordinati per primi nel pool: evita che fonti pure
# ma poco sensate (zucchero, canditi, alcolici) dominino la selezione.
# Impostare prefer_categories=None nel pool per tornare al puro criterio di purezza.
PREFERRED_CATEGORIES = {
    "carbo": ["Cereali e derivati", "Legumi", "Verdure e ortaggi", "Frutta"],
    "proteine": [
        "Carni fresche", "Prodotti della pesca", "Uova",
        "Formaggi e latticini", "Legumi", "Latte e yogurt",
    ],
    "grassi": ["Oli e grassi", "Frutta secca a guscio e semi oleaginosi"],
}

# Categorie "sensate" pre-selezionate di default nel FE (unione delle preferite):
# esclude dolci, alcolici, frattaglie, fast-food, ecc. L'utente può modificarle.
SUGGESTED_CATEGORIES = sorted({c for cats in PREFERRED_CATEGORIES.values() for c in cats})

# (b) Preferenza per gli alimenti CRUDI: le versioni cotte/in scatola vengono
# spinte in fondo al pool. È anche la prassi nutrizionale (si prescrive il peso
# a crudo). Impostare PREFER_RAW=False per disattivare.
PREFER_RAW = True
RAW_TERMS = ("crudo", "cruda", "crudi", "crude")
COOKED_TERMS = (
    "cotto", "cotta", "cotti", "cotte", "bollit", "arrost", "forno", "fritt",
    "in scatola", "salamoia", "spiedo", "padella", "grigliat", "saltat",
    "brasato", "stufat", "affumicat", "essiccat", "disidratat", "sott'olio",
    "sottolio", "tostat",
)

# (a) Alimenti COMUNI: i nomi che contengono uno di questi termini "esotici"
# (selvaggina, animali insoliti, pesci/ingredienti poco usati) vengono demoti
# così la selezione preferisce alimenti di uso quotidiano. Lista editabile.
UNCOMMON_TERMS = (
    # carni esotiche / selvaggina
    "struzzo", "cervo", "capriolo", "daino", "camoscio", "renna", "alce",
    "capra", "capretto", "bufalo", "cavallo", "equino", "asino", "mulo",
    "cinghiale", "lepre", "montone", "castrato", "faraona", "fagiano",
    "quaglia", "piccione", "germano", "beccaccia", "tordo", "allodola",
    "canguro", "coccodrillo",
    # anfibi / molluschi insoliti
    "rana", "lumaca", "chiocciola", "tartaruga",
    # pesci / prodotti della pesca obscuri
    "melù", "melu", "molo", "palombo", "alaccia", "lampuga", "mormora",
    "menola", "boga", "suro", "sugarello", "leccia", "occhiata", "donzella",
    "scorfano", "gallinella", "grongo", "murena", "capitone", "aguglia",
    "lampreda", "cicerello", "latterino", "zerro",
    # ingredienti/derivati non "alimento da piatto"
    "amido", "manioca", "fecola", "glutine", "crusca", "germe di",
)

# --- Modello LLM (provider-agnostico) ---
# Il provider si sceglie con NUTRI_LLM_PROVIDER (groq | claude). Il lavoro pesante
# lo fanno i tool deterministici: all'LLM servono solo comprensione del linguaggio
# e tool calling, quindi un modello open-source gratuito è sufficiente per una demo.
#   - groq   -> Llama 3.3 70B servito da Groq (free tier), env GROQ_API_KEY
#   - claude -> Claude Haiku (a pagamento), env ANTHROPIC_API_KEY
LLM_PROVIDER = os.getenv("NUTRI_LLM_PROVIDER", "groq").strip().lower()

# Default per provider; sovrascrivibile con NUTRI_LLM_MODEL (utile se Groq ritira
# un modello: basta cambiare la env, senza toccare il codice né ridistribuire).
_DEFAULT_MODEL = {
    "groq": "llama-3.3-70b-versatile",
    "claude": "claude-haiku-4-5-20251001",
}
LLM_MODEL_ID = os.getenv("NUTRI_LLM_MODEL") or _DEFAULT_MODEL.get(
    LLM_PROVIDER, _DEFAULT_MODEL["groq"]
)

# Nome della variabile d'ambiente con la chiave richiesta dal provider scelto
# (usato dagli endpoint per un errore chiaro se manca la key).
LLM_API_KEY_ENV = {"groq": "GROQ_API_KEY", "claude": "ANTHROPIC_API_KEY"}.get(
    LLM_PROVIDER, "GROQ_API_KEY"
)

# Modello di fallback automatico usato se il provider primario (Groq) va in
# errore o in rate-limit (429). Attivo SOLO con provider=groq e con
# ANTHROPIC_API_KEY presente; altrimenti nessun fallback (vedi agents._fallback_config).
LLM_FALLBACK_MODEL = os.getenv("NUTRI_LLM_FALLBACK_MODEL", "claude-haiku-4-5-20251001")
