# Pokéserre - code de la carte ESP32

Programme du capteur d'humidité de la Pokéserre (terrarium Pokéball).
La carte mesure l'humidité de la terre (et la batterie si câblée), envoie
la mesure au serveur Pokéserre, puis se rendort (deep sleep) pour tenir
plusieurs semaines sur batterie.

- Carte : ESP32-C3 SuperMini
- Langage : MicroPython 1.22 ou plus récent

## Fichiers

| Fichier | Rôle |
|---|---|
| `pokeserre.py` | programme principal (à copier sous le nom `main.py`) |
| `wifi_manager.py` | connexion WiFi + page de configuration au premier démarrage |
| `config_exemple.json` | modèle du fichier `config.json` (token de la serre) |

## Câblage

- Capteur d'humidité capacitif :
  - VCC -> GPIO10 (la carte l'allume seulement pendant la mesure)
  - signal -> GPIO1
  - GND -> GND
- Batterie (optionnel) : pont diviseur 2 x 100 kOhm entre B+ et GND,
  point milieu -> GPIO3, puis mettre `PONT_BATTERIE_CABLE = True`
  dans `pokeserre.py`.
- Autonomie : dessouder/couper la LED rouge d'alimentation de la carte.

## Installation avec Thonny

1. Copier sur la carte :
   - `pokeserre.py` sous le nom `main.py` (démarrage automatique)
   - `wifi_manager.py` (même nom)
2. Créer sur la carte un fichier `config.json` à partir de
   `config_exemple.json`, avec le vrai token de la serre :
   `{"token": "..."}`. Ce fichier ne doit jamais être mis dans git.
3. Premier démarrage : la carte crée un WiFi nommé **PokeSerre-Config**.
   Le mot de passe s'affiche dans la console Thonny. Se connecter à ce
   WiFi, ouvrir http://192.168.4.1 et entrer le WiFi de la maison.

Astuce : pour reprendre la main dans Thonny, appuyer sur RST puis tout
de suite sur Stop (pendant le deep sleep la carte ne répond pas).

## Calibration du capteur

1. Lancer le programme dans Thonny et noter la valeur « Capteur brut ».
2. Capteur à l'air libre (sec) -> recopier la valeur dans `BRUT_SEC`.
3. Capteur dans un verre d'eau (mouillé) -> recopier dans `BRUT_MOUILLE`.
