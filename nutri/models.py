"""Schemi dati (Pydantic v2) usati da motore, API e agenti."""
from __future__ import annotations

from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

Macro = str  # "carbo" | "proteine" | "grassi"


class MacroSplit(BaseModel):
    """Suddivisione percentuale tra i macronutrienti (frazioni che sommano a 1)."""

    carbo: float = Field(ge=0, le=1)
    proteine: float = Field(ge=0, le=1)
    grassi: float = Field(ge=0, le=1)

    @model_validator(mode="after")
    def _check_sum(self) -> "MacroSplit":
        total = self.carbo + self.proteine + self.grassi
        if abs(total - 1.0) > 0.02:
            raise ValueError(
                f"Le percentuali dei macro devono sommare a 1 (trovato {total:.3f})"
            )
        return self

    def as_dict(self) -> Dict[Macro, float]:
        return {"carbo": self.carbo, "proteine": self.proteine, "grassi": self.grassi}


class MealSpec(BaseModel):
    """Specifica di un singolo pasto inserita dal nutrizionista."""

    nome: str
    kcal_percent: float = Field(gt=0, le=1, description="Frazione delle kcal giornaliere")
    macro_split: MacroSplit
    # Categorie del CSV da includere SOLO per questo pasto (whitelist).
    # Vuoto = tutte le categorie ammesse.
    categorie_incluse: List[str] = Field(default_factory=list)
    # Tipo di pasto (colazione/pranzo/cena/spuntino): filtra gli alimenti la cui
    # colonna pasto_consigliato contiene questo valore. None = nessun filtro.
    tipo_pasto: Optional[str] = None

    @field_validator("categorie_incluse", mode="before")
    @classmethod
    def _clean_categorie(cls, v):
        if not isinstance(v, list):
            return v
        return [s.strip() for s in v if isinstance(s, str) and s.strip()]

    @field_validator("tipo_pasto", mode="before")
    @classmethod
    def _clean_tipo_pasto(cls, v):
        if not isinstance(v, str):
            return v
        return v.strip().lower() or None


class PlanRequest(BaseModel):
    """Input dell'intero piano (ciò che arriva dal mock FE)."""

    kcal_target: float = Field(gt=0, description="Kcal giornaliere totali")
    pasti: List[MealSpec] = Field(min_length=1)

    # Preferenze alimentari (opzionali)
    alimenti_preferiti: List[str] = Field(default_factory=list)
    alimenti_esclusi: List[str] = Field(default_factory=list)
    categorie_escluse: List[str] = Field(default_factory=list)

    @field_validator("alimenti_preferiti", "alimenti_esclusi", "categorie_escluse", mode="before")
    @classmethod
    def _drop_empty(cls, v):
        """Rimuove stringhe vuote/spazi (la UI mette [""] come default)."""
        if not isinstance(v, list):
            return v
        return [s.strip() for s in v if isinstance(s, str) and s.strip()]

    @model_validator(mode="after")
    def _check_kcal_percent(self) -> "PlanRequest":
        total = sum(p.kcal_percent for p in self.pasti)
        if abs(total - 1.0) > 0.02:
            raise ValueError(
                f"Le percentuali kcal dei pasti devono sommare a 1 (trovato {total:.3f})"
            )
        return self


class MacroTargets(BaseModel):
    """Target in grammi (e kcal) di un pasto."""

    kcal: float
    carbo_g: float
    proteine_g: float
    grassi_g: float

    def as_vector(self) -> List[float]:
        return [self.carbo_g, self.proteine_g, self.grassi_g]


class FoodPortion(BaseModel):
    """Un alimento selezionato con la grammatura da assumere."""

    nome: str
    categoria: str
    ruolo: Macro = Field(description="Macro di cui questo alimento è la fonte")
    grammi: float
    # Macro effettivamente apportati da questa porzione
    kcal: float
    carbo_g: float
    proteine_g: float
    grassi_g: float


class MealResult(BaseModel):
    """Risultato del bilanciamento di un pasto."""

    nome: str
    target: MacroTargets
    alimenti: List[FoodPortion]
    # Totali ottenuti
    kcal_ottenute: float
    carbo_ottenuti: float
    proteine_ottenute: float
    grassi_ottenuti: float
    # Errore (ottenuto - target)
    errore_kcal: float
    errore_pct: float = Field(description="Errore kcal in percentuale del target")


class MacroOption(BaseModel):
    """Un alimento-opzione per un macro, con la grammatura che ne fornisce il target.

    Tutte le opzioni della stessa lista forniscono la STESSA quantità del macro di
    riferimento (sono equivalenti): basta sceglierne una.
    """

    nome: str
    categoria: str
    grammi: float
    # Macro e kcal effettivamente apportati da questa porzione
    kcal: float
    carbo_g: float
    proteine_g: float
    grassi_g: float
    # Macro per 100g (per il ricalcolo live lato FE quando si modificano i grammi)
    carbo_100: float
    proteine_100: float
    grassi_100: float


class MealOptions(BaseModel):
    """Per un pasto: target dei macro + liste di alimenti equivalenti per macro."""

    nome: str
    target: MacroTargets
    # chiavi: "carbo" | "proteine" | "grassi"
    opzioni: Dict[Macro, List[MacroOption]]


class DayOptions(BaseModel):
    """Giornata espressa come liste di opzioni equivalenti per ogni pasto."""

    etichetta: str = "Giorno"
    pasti: List[MealOptions]


class DayPlan(BaseModel):
    """Piano di una giornata."""

    etichetta: str = "Giorno"
    pasti: List[MealResult]
    kcal_totali: float
    errore_kcal_giorno: float


class WeekPlan(BaseModel):
    """Piano settimanale (7 giorni vari ma equivalenti)."""

    giorni: List[DayPlan]


# ----- Protocollo di azioni dell'assistente AI -----

class MealConfig(BaseModel):
    """Configurazione di un pasto proposta dall'assistente (per set_config)."""

    nome: str
    tipo_pasto: Optional[str] = None
    kcal_percent: float = Field(description="Frazione delle kcal giornaliere (0-1)")
    carbo: float = Field(description="Frazione kcal da carboidrati (0-1)")
    proteine: float = Field(description="Frazione kcal da proteine (0-1)")
    grassi: float = Field(description="Frazione kcal da grassi (0-1)")
    categorie_incluse: List[str] = Field(default_factory=list)


class AssistantAction(BaseModel):
    """Una singola azione che il FE deve applicare al piano."""

    tipo: str = Field(
        description="set_config | add_food | remove_food | set_grams | toggle_food"
    )
    # targeting alimento
    pasto: Optional[str] = Field(default=None, description="nome del pasto")
    macro: Optional[str] = Field(default=None, description="carbo | proteine | grassi")
    nome: Optional[str] = Field(default=None, description="nome dell'alimento")
    grammi: Optional[float] = None
    selezionato: Optional[bool] = None
    # macro per 100g (solo per alimenti custom non in database)
    carbo_100: Optional[float] = None
    proteine_100: Optional[float] = None
    grassi_100: Optional[float] = None
    # set_config
    kcal_target: Optional[float] = None
    pasti: Optional[List[MealConfig]] = None


class AssistantResponse(BaseModel):
    """Risposta dell'assistente: testo per l'utente + azioni da applicare."""

    risposta: str
    azioni: List[AssistantAction] = Field(default_factory=list)
