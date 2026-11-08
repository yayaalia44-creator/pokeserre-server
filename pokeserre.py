# =====================================================================
#  POKÉSERRE - programme de la carte ESP32-C3 SuperMini (MicroPython)
# =====================================================================
#  À FAIRE AVANT DE COPIER
#  1. Câblage :
#     - capteur d'humidité : VCC -> GPIO10 (la carte l'allume seulement
#       pendant la mesure), GND -> GND, signal -> GPIO1
#     - batterie (si câblé) : pont diviseur 2 x 100 kOhm entre B+ et GND,
#       point milieu -> GPIO3, puis mettre PONT_BATTERIE_CABLE = True
#  2. Calibration : lancer le programme dans Thonny, noter la valeur
#     "Capteur brut" capteur à l'air (sec) puis dans un verre d'eau
#     (mouillé), et les recopier dans BRUT_SEC et BRUT_MOUILLE.
#  3. Créer sur la carte un fichier config.json (modèle :
#     config_exemple.json) avec le vrai token : {"token": "..."}
#  4. Avec Thonny, copier sur la carte :
#       pokeserre.py  sous le nom  main.py   (démarrage automatique)
#       wifi_manager.py            (même nom)
#     MicroPython 1.22 ou plus récent.
#  5. Autonomie : dessouder/couper la LED rouge d'alimentation de la carte.
#  Astuce : pour reprendre la main dans Thonny, appuie sur RST puis tout
#  de suite sur Stop (pendant le deep sleep la carte ne répond pas).
# =====================================================================

import time
import json
import gc
import machine
import network
from machine import Pin, ADC
from wifi_manager import initialiser_wifi
gc.collect()

try:
    import requests as urequests
except ImportError:
    import urequests

# --- CONFIGURATION ---
SERVER_URL  = "https://pokeserre-server.onrender.com/api/data"
TOKEN_FILE  = "config.json"   # {"token": "..."} sur la carte, jamais dans git
TOKEN_EXEMPLE = "COLLE_LE_TOKEN_DE_TA_SERRE_ICI"

# -- intervalle de deep sleep normal en millisecondes (3h = 10800000ms) --
SLEEP_MS    = 10800000
# -- en cas d'échec : 5 min, puis 30 min, puis 3 h --
ESSAIS_MS   = (300000, 1800000, 10800000)

# --- CAPTEUR D'HUMIDITÉ ---
PIN_CAPTEUR      = 1    # signal du capteur (ADC)
PIN_ALIM_CAPTEUR = 10   # alimente le capteur seulement pendant la mesure
# Valeurs brutes (read_u16, 0-65535) À CALIBRER (voir en-tête) :
BRUT_SEC         = 45000  # capteur à l'air libre (0 %)
BRUT_MOUILLE     = 20000  # capteur dans l'eau (100 %)

# --- BATTERIE ---
PIN_BATTERIE        = 3      # point milieu du pont 2 x 100 kOhm
PONT_BATTERIE_CABLE = False  # passer à True quand le pont est soudé
BATTERIE_MANUELLE   = 75     # valeur envoyée tant que le pont n'est pas câblé
# Courbe LiPo simplifiée : (tension minimale en V, pourcentage)
PALIERS_LIPO = ((4.15, 100), (4.05, 90), (3.97, 80), (3.90, 70),
                (3.84, 60), (3.79, 50), (3.75, 40), (3.71, 30),
                (3.67, 20), (3.61, 10), (3.50, 5))


# --- OUTIL : bornage 0-100 ---
def borner(valeur):
    return max(0, min(100, int(valeur)))


# --- LECTURE DU CAPTEUR D'HUMIDITÉ ---
def lire_capteur():
    alim = Pin(PIN_ALIM_CAPTEUR, Pin.OUT)
    alim.value(1)  # on allume le capteur
    try:
        time.sleep_ms(500)  # le temps que le signal se stabilise
        adc = ADC(Pin(PIN_CAPTEUR))
        adc.atten(ADC.ATTN_11DB)
        lectures = []
        for _ in range(16):
            lectures.append(adc.read_u16())
            time.sleep_ms(10)
    finally:
        alim.value(0)  # on éteint le capteur, même en cas d'erreur
    # On retire les 2 plus basses et les 2 plus hautes, puis moyenne
    lectures.sort()
    utiles = lectures[2:-2]
    brut = sum(utiles) // len(utiles)
    print("Capteur brut :", brut, "(pour la calibration)")
    # Sec = valeur haute, mouillé = valeur basse
    pourcent = (BRUT_SEC - brut) * 100 // (BRUT_SEC - BRUT_MOUILLE)
    return borner(pourcent)


# --- LECTURE DE LA BATTERIE ---
def lire_batterie():
    if not PONT_BATTERIE_CABLE:
        print("Attention : pont batterie non câblé, valeur fixe", BATTERIE_MANUELLE, "%")
        return BATTERIE_MANUELLE
    adc = ADC(Pin(PIN_BATTERIE))
    adc.atten(ADC.ATTN_11DB)
    total = 0
    for _ in range(16):
        total += adc.read_uv()
        time.sleep_ms(5)
    # Moyenne en volts, x2 à cause du pont diviseur
    tension = total / 16 / 1000000 * 2
    print("Tension batterie :", tension, "V")
    for seuil, pourcent in PALIERS_LIPO:
        if tension >= seuil:
            return pourcent
    return 0


# --- TOKEN DE LA SERRE (fichier config.json sur la carte) ---
def charger_token():
    try:
        with open(TOKEN_FILE, 'r') as f:
            token = json.load(f).get('token')
    except Exception:
        token = None
    if not token or token == TOKEN_EXEMPLE:
        return None
    return str(token)


# --- ENVOI SERVEUR CLOUD ---
# Renvoie "ok" (200), "refuse" (400/401, inutile de réessayer) ou "echec".
def envoyer_serveur(token, h, b):
    corps_json = json.dumps({"token": token, "humidite": borner(h), "batterie": borner(b)}).encode('utf-8')
    for essai in range(2):
        if essai == 1:
            print("Nouvel essai dans 10 s (serveur Render en train de se réveiller ?)")
            time.sleep(10)
        gc.collect()
        response = None
        try:
            response = urequests.post(
                SERVER_URL,
                data=corps_json,
                headers={'Content-Type': 'application/json'},
                timeout=60
            )
            code = response.status_code
            if code == 200:
                print("Données envoyées au serveur !")
                return "ok"
            if code in (400, 401):
                print("Serveur a refusé (", code, ") :", response.text)
                return "refuse"
            print("Erreur serveur :", code)
        except Exception as e:
            print("Erreur envoi serveur :", e)
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass
    return "echec"


# --- COMPTEUR D'ÉCHECS (mémoire RTC, survit au deep sleep) ---
def lire_echecs():
    try:
        m = machine.RTC().memory()
        return m[0] if len(m) > 0 else 0
    except Exception:
        return 0


def ecrire_echecs(n):
    try:
        machine.RTC().memory(bytes([min(n, 255)]))
    except Exception:
        pass


# --- COUPER LE WIFI AVANT DE DORMIR ---
def couper_wifi():
    try:
        wlan = network.WLAN(network.STA_IF)
        try:
            wlan.disconnect()
        except Exception:
            pass
        wlan.active(False)
    except Exception:
        pass


# --- PROGRAMME PRINCIPAL ---
print("Démarrage...")
etat = "echec"          # "ok", "definitif" (inutile de réessayer vite) ou "echec"
arret_manuel = False    # True si on appuie sur Stop dans Thonny

try:
    # 1. Mesures AVANT le WiFi (moins de bruit, moins de consommation)
    humidite = lire_capteur()
    batterie = lire_batterie()
    print("Humidité :", humidite, "%")
    print("Batterie :", batterie, "%")
    gc.collect()

    # 2. Token de la serre
    token = charger_token()
    if token is None:
        print("Pas de token : crée config.json sur la carte (voir config_exemple.json). Pas d'envoi.")
        etat = "definitif"
    else:
        # 3. WiFi puis envoi
        ip = initialiser_wifi()
        gc.collect()
        if ip:
            resultat = envoyer_serveur(token, humidite, batterie)
            if resultat == "ok":
                etat = "ok"
            elif resultat == "refuse":
                etat = "definitif"
        else:
            print("Pas de WiFi.")

except KeyboardInterrupt:
    arret_manuel = True
    print("Arrêt manuel : pas de deep sleep.")
except Exception as e:
    print("Erreur inattendue :", e)

finally:
    if arret_manuel:
        couper_wifi()
    else:
        try:
            echecs = lire_echecs()
            if etat == "echec":
                echecs += 1
                duree = ESSAIS_MS[min(echecs, len(ESSAIS_MS)) - 1]
            else:
                echecs = 0
                duree = SLEEP_MS
            ecrire_echecs(echecs)
            print("Échecs consécutifs :", echecs)
        except Exception:
            duree = SLEEP_MS
        couper_wifi()
        gc.collect()
        print("Deep sleep", duree // 60000, "min...")
        machine.deepsleep(duree)
