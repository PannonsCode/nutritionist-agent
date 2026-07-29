import numpy as np

class MacroNutrienti:

    def __init__(self, carbo_percent, proteine_percent, grassi_percent):
        self.percent = {
            "carbo": carbo_percent,
            "proteine": proteine_percent,
            "grassi": grassi_percent
        }

        self.grams = {
            "carbo": 0,
            "proteine": 0,
            "grassi": 0
        }

        self.grams_error = {
            "carbo": 0,
            "proteine": 0,
            "grassi": 0}
    
    def update_macros_to_grams(self, kcal_target):
        self.grams["carbo"] = int((kcal_target * self.percent["carbo"]) / 4)
        self.grams["proteine"] = int((kcal_target * self.percent["proteine"]) / 4)
        self.grams["grassi"] = int((kcal_target * self.percent["grassi"]) / 9)
    
    def arrondisci_grams(self):
        app = self.grams.copy()
        self.grams["carbo"] = int(np.round(self.grams["carbo"] / 5) * 5)
        self.grams_error["carbo"] = self.grams["carbo"] - app["carbo"]

        self.grams["proteine"] = int(np.round(self.grams["proteine"] / 5) * 5)
        self.grams_error["proteine"] = self.grams["proteine"] - app["proteine"]

        self.grams["grassi"] = int(np.round(self.grams["grassi"] / 5) * 5)
        self.grams_error["grassi"] = self.grams["grassi"] - app["grassi"]

class Pasto:

    def __init__(self, nome_pasto, kcal_target, kcal_percent, carbo_percent=0, proteine_percent=0, grassi_percent=0):
        self.nome_pasto = nome_pasto
        self.kcal_pasto = kcal_target * kcal_percent
        self.macronutrienti_pasto = MacroNutrienti(carbo_percent=carbo_percent, proteine_percent=proteine_percent, grassi_percent=grassi_percent)
        self.macronutrienti_pasto.update_macros_to_grams(self.kcal_pasto)
        self.macronutrienti_pasto.arrondisci_grams()