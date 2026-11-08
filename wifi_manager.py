import network
import socket
import time
import json
import os

# Fichier de config WiFi enregistré sur la carte (jamais versionné)
CONFIG_FILE = 'wifi_config.json'

# Durée maximale du portail de configuration (5 minutes)
PORTAIL_DUREE_MAX_MS = 5 * 60 * 1000

# Taille maximale acceptée pour le corps d'un POST (protection mémoire)
CORPS_MAX = 1024


# --- PAGES HTML DU PORTAIL ---
# Dans des fonctions : les textes ne sont créés qu'au moment où on en a besoin.
def html_formulaire():
    return """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PokeSerre — Configuration WiFi</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;}
body{background:#111;min-height:100vh;font-family:'Courier New',monospace;color:#fff;display:flex;flex-direction:column;align-items:center;justify-content:center;padding:20px;}
.divider{width:100%;height:5px;background:linear-gradient(90deg,#E3000F 47%,#111 47%,#111 50%,#fff 50%,#fff 53%,#111 53%);position:fixed;top:0;}
.box{display:flex;flex-direction:column;align-items:center;gap:20px;width:100%;max-width:320px;}
.ball{width:70px;height:70px;border-radius:50%;border:4px solid #fff;position:relative;overflow:hidden;}
.ball-top{background:#E3000F;height:50%;}
.ball-bot{background:#1a1a1a;height:50%;}
.ball::after{content:'';position:absolute;top:47%;left:0;right:0;height:6%;background:#111;}
.ball-btn{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:12px;height:12px;background:#fff;border:3px solid #111;border-radius:50%;z-index:2;}
.title{font-size:11px;color:#fff;letter-spacing:3px;text-align:center;text-transform:uppercase;}
.subtitle{font-size:10px;color:rgba(255,255,255,0.35);letter-spacing:1px;text-align:center;}
form{width:100%;display:flex;flex-direction:column;gap:10px;}
input{background:rgba(255,255,255,0.06);border:1px solid rgba(255,255,255,0.15);color:#fff;font-family:'Courier New',monospace;font-size:13px;padding:12px 16px;border-radius:4px;width:100%;}
input::placeholder{color:rgba(255,255,255,0.3);}
button{background:#E3000F;color:#fff;border:none;font-size:11px;padding:14px;cursor:pointer;border-radius:4px;letter-spacing:2px;width:100%;text-transform:uppercase;}
</style>
</head>
<body>
<div class="divider"></div>
<div class="box">
  <div class="ball"><div class="ball-top"></div><div class="ball-bot"></div><div class="ball-btn"></div></div>
  <div class="title">PokeSerre</div>
  <div class="subtitle">Configuration WiFi</div>
  <form method="POST" action="/save">
    <input type="text" name="ssid" placeholder="Nom de ton WiFi (SSID)" required/>
    <input type="password" name="password" placeholder="Mot de passe WiFi" required/>
    <button type="submit">CONNECTER</button>
  </form>
</div>
</body>
</html>"""


def html_ok():
    return """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PokeSerre — Connexion en cours</title>
<style>
*{margin:0;padding:0;box-sizing:border-box;}
body{background:#111;min-height:100vh;font-family:'Courier New',monospace;color:#fff;display:flex;align-items:center;justify-content:center;padding:20px;}
.box{text-align:center;display:flex;flex-direction:column;align-items:center;gap:16px;}
.ball{width:70px;height:70px;border-radius:50%;border:4px solid #00C853;position:relative;overflow:hidden;}
.ball-top{background:#E3000F;height:50%;}
.ball-bot{background:#1a1a1a;height:50%;}
.ball::after{content:'';position:absolute;top:47%;left:0;right:0;height:6%;background:#111;}
.ball-btn{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:12px;height:12px;background:#fff;border:3px solid #111;border-radius:50%;z-index:2;}
.msg{font-size:11px;color:#00C853;letter-spacing:2px;}
.sub{font-size:10px;color:rgba(255,255,255,0.3);letter-spacing:1px;}
</style>
</head>
<body>
<div class="box">
  <div class="ball"><div class="ball-top"></div><div class="ball-bot"></div><div class="ball-btn"></div></div>
  <div class="msg">WIFI SAUVEGARDE !</div>
  <div class="sub">La PokeSerre se connecte...<br>Tu peux fermer cette page.</div>
</div>
</body>
</html>"""


# --- SAUVEGARDE CONFIG ---
def sauvegarder_config(ssid, password):
    with open(CONFIG_FILE, 'w') as f:
        json.dump({'ssid': ssid, 'password': password}, f)


# --- LE FICHIER DE CONFIG EXISTE-T-IL ? ---
def config_existe():
    try:
        os.stat(CONFIG_FILE)
        return True
    except OSError:
        return False


# --- CHARGER CONFIG ---
def charger_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except Exception:
        return None


# --- CONNEXION WIFI ---
def connecter_wifi(ssid, password, timeout=20):
    wlan = network.WLAN(network.STA_IF)
    wlan.active(False)
    time.sleep(0.5)
    wlan.active(True)
    try:
        wlan.disconnect()
    except Exception:
        pass
    time.sleep(0.5)
    wlan.connect(ssid, password)
    print("Connexion à", ssid, "...")
    while not wlan.isconnected() and timeout > 0:
        print(".", end="")
        time.sleep(1)
        timeout -= 1
    if wlan.isconnected():
        ip = wlan.ifconfig()[0]
        print("\nConnecté ! IP :", ip)
        return ip
    print("\nÉchec connexion WiFi")
    return None


# --- DÉCODAGE D'UN TEXTE DE FORMULAIRE (%XX en UTF-8 et +) ---
def decoder_url(texte):
    octets = bytearray()
    i = 0
    n = len(texte)
    while i < n:
        c = texte[i]
        if c == '+':
            octets.append(32)  # '+' = espace
            i += 1
        elif c == '%' and i + 2 < n:  # il reste bien 2 caractères après '%'
            try:
                octets.append(int(texte[i + 1:i + 3], 16))
                i += 3
            except ValueError:
                # '%' isolé : on le garde tel quel
                octets.extend(c.encode('utf-8'))
                i += 1
        else:
            octets.extend(c.encode('utf-8'))
            i += 1
    try:
        return bytes(octets).decode('utf-8')
    except Exception:
        return texte


# --- LIRE UNE REQUÊTE HTTP COMPLÈTE (en-têtes + corps selon Content-Length) ---
def lire_requete(conn):
    donnees = b''
    # 1. On lit jusqu'à la fin des en-têtes
    while b'\r\n\r\n' not in donnees and len(donnees) < 4096:
        morceau = conn.recv(512)
        if not morceau:
            break
        donnees += morceau
    fin = donnees.find(b'\r\n\r\n')
    if fin < 0:
        return donnees.decode('utf-8'), b''
    entetes = donnees[:fin].decode('utf-8')
    corps = donnees[fin + 4:]
    # 2. On cherche la taille du corps annoncée
    longueur = 0
    for ligne in entetes.split('\r\n'):
        if ligne.lower().startswith('content-length:'):
            try:
                longueur = int(ligne.split(':', 1)[1].strip())
            except ValueError:
                longueur = 0
    longueur = min(longueur, CORPS_MAX)
    # 3. On lit le reste du corps si besoin
    while len(corps) < longueur:
        morceau = conn.recv(longueur - len(corps))
        if not morceau:
            break
        corps += morceau
    return entetes, corps


# --- MOT DE PASSE DU POINT D'ACCÈS (dérivé de la MAC, pas en dur) ---
def mot_de_passe_ap(ap):
    mac = ap.config('mac')
    return 'poke' + '%02x%02x' % (mac[-2], mac[-1])  # 8 caractères


# --- POINT D'ACCÈS + PAGE DE CONFIG (5 minutes max) ---
# Renvoie l'IP si le WiFi a été configuré et connecté, sinon None.
def lancer_portail_config():
    print("Lancement du portail de configuration WiFi (5 min max)...")

    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    mdp = mot_de_passe_ap(ap)
    ap.config(essid='PokeSerre-Config', password=mdp, authmode=3)
    print("Point d'accès : PokeSerre-Config")
    print("Mot de passe  :", mdp)
    print("Ouvre         : http://192.168.4.1")

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('', 80))
    s.listen(2)
    s.settimeout(1)  # accept() ne bloque jamais plus d'1 s

    ssid_recu = None
    password_recu = ''
    debut = time.ticks_ms()

    try:
        while time.ticks_diff(time.ticks_ms(), debut) < PORTAIL_DUREE_MAX_MS:
            try:
                conn, addr = s.accept()
            except OSError:
                continue  # personne ne s'est connecté pendant cette seconde

            try:
                conn.settimeout(3)
                entetes, corps = lire_requete(conn)

                if entetes.startswith('POST /save'):
                    params = {}
                    for p in corps.decode('utf-8').split('&'):
                        if '=' in p:
                            k, v = p.split('=', 1)
                            params[decoder_url(k)] = decoder_url(v)
                    ssid_recu = params.get('ssid', '')
                    password_recu = params.get('password', '')

                if ssid_recu:
                    page = html_ok()
                else:
                    page = html_formulaire()
                conn.sendall(b'HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nConnection: close\r\n\r\n')
                conn.sendall(page.encode('utf-8'))
                page = None
            except Exception as e:
                print("Erreur portail :", e)
            finally:
                try:
                    conn.close()
                except Exception:
                    pass

            if ssid_recu:
                time.sleep(2)  # laisse le temps au téléphone d'afficher la page
                break
    finally:
        s.close()
        ap.active(False)

    if not ssid_recu:
        print("Portail fermé : aucune config reçue en 5 min.")
        return None

    sauvegarder_config(ssid_recu, password_recu)
    print("Config sauvegardée pour :", ssid_recu)
    return connecter_wifi(ssid_recu, password_recu)


# --- FONCTION PRINCIPALE ---
# Le portail n'est lancé QUE s'il n'y a aucun fichier wifi_config.json.
# Si la config existe mais que la connexion échoue -> None (la serre se rendort).
def initialiser_wifi():
    if not config_existe():
        print("Pas de config WiFi : lancement du portail...")
        return lancer_portail_config()

    config = charger_config()
    if not config:
        print("wifi_config.json illisible : supprime-le avec Thonny pour relancer le portail.")
        return None

    ip = connecter_wifi(config.get('ssid', ''), config.get('password', ''))
    if not ip:
        print("WiFi injoignable : nouvel essai plus tard (config conservée).")
    return ip
