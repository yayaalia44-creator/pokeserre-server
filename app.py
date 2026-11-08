from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from datetime import datetime, timezone
import secrets
import os
import json
import hmac
import math
import urllib.request
from datetime import timedelta

# --- CONFIGURATION ---
app = Flask(__name__)
# Render est derrière un proxy https : on lui fait confiance pour avoir les bonnes URL (QR codes en https)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
SECRET_KEY = os.environ.get('SECRET_KEY', '')
if not SECRET_KEY:
    # repli aléatoire : ça marche, mais les sessions sont perdues à chaque redémarrage
    print('ATTENTION : SECRET_KEY non définie, clé aléatoire utilisée (sessions perdues au redémarrage)')
    SECRET_KEY = secrets.token_hex(32)
app.secret_key = SECRET_KEY
# cookies de session : pas lisibles en JavaScript, pas envoyés par d'autres sites
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
# https seulement sur Render (la variable RENDER y est définie automatiquement), pas en local
app.config['SESSION_COOKIE_SECURE'] = 'RENDER' in os.environ
DB_URL = os.environ.get('DATABASE_URL', 'sqlite:///pokeserre.db')
# Render/Neon donnent postgres://, postgresql:// ou postgresql+psycopg2:// : on force le pilote psycopg (v3),
# seul installé via requirements.txt (psycopg2 n'est plus installé). postgresql+psycopg:// est laissé tel quel.
for prefix in ('postgresql+psycopg2://', 'postgres://', 'postgresql://'):
    if DB_URL.startswith(prefix):
        DB_URL = 'postgresql+psycopg://' + DB_URL[len(prefix):]
        break
app.config['SQLALCHEMY_DATABASE_URI'] = DB_URL
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'pool_pre_ping': True, 'pool_recycle': 280}  # base qui s'endort (Neon)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', '')              # vide = admin désactivé
if not ADMIN_PASSWORD:
    print('ATTENTION : ADMIN_PASSWORD non définie, la connexion admin est désactivée')
CRON_TOKEN = os.environ.get('CRON_TOKEN', '')                       # secret du contrôle automatique
BUREAU_TOKEN = os.environ.get('BUREAU_TOKEN', '')                   # secret du hook « bureau des agents » (vide = désactivé)
DISCORD_WEBHOOK_URL = os.environ.get('DISCORD_WEBHOOK_URL', '')    # alertes serveur (optionnel)
HEURES_SILENCE = 7        # alerte si une serre n'a rien envoyé depuis 7 h (cycle normal : 3 h)
SEUIL_BATTERIE = 20       # alerte quand la batterie passe sous 20 %
SEUIL_SEC = 40            # alerte « a soif » quand l'humidité passe sous 40 %

def maintenant_utc():
    # heure UTC sans fuseau (comme les dates déjà en base) ; remplace datetime.utcnow (obsolète)
    return datetime.now(timezone.utc).replace(tzinfo=None)

def secret_ok(recu, attendu):
    # comparaison en temps constant ; refuse toujours si le secret attendu n'est pas configuré
    if not attendu or not isinstance(recu, str):
        return False
    return hmac.compare_digest(recu.encode('utf-8'), attendu.encode('utf-8'))

# --- MODÈLES ---
class Utilisateur(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    username     = db.Column(db.String(80), unique=True, nullable=False)
    password     = db.Column(db.String(200), nullable=False)
    serre_id     = db.Column(db.Integer, db.ForeignKey('serre.id'), nullable=False)

class Serre(db.Model):
    id           = db.Column(db.Integer, primary_key=True)
    nom          = db.Column(db.String(100), nullable=False)
    token        = db.Column(db.String(64), unique=True, nullable=False)
    token_used   = db.Column(db.Boolean, default=False)
    mesures      = db.relationship('Mesure', backref='serre', lazy=True)
    utilisateurs = db.relationship('Utilisateur', backref='serre', lazy=True)

class Mesure(db.Model):
    id        = db.Column(db.Integer, primary_key=True)
    humidite  = db.Column(db.Float, nullable=False)
    batterie  = db.Column(db.Float, nullable=False)
    date      = db.Column(db.DateTime, default=maintenant_utc)
    serre_id  = db.Column(db.Integer, db.ForeignKey('serre.id'), nullable=False)

class BureauEtat(db.Model):
    # une seule ligne (id=1) : dernier état des agents envoyé par le hook Claude Code
    id        = db.Column(db.Integer, primary_key=True)
    contenu   = db.Column(db.Text, nullable=False)        # JSON {"maj": ..., "agents": {...}}
    maj       = db.Column(db.DateTime, default=maintenant_utc)

# --- ROUTE PRINCIPALE ---
@app.route('/')
def index():
    return redirect(url_for('login'))

# --- INSCRIPTION VIA QR CODE ---
@app.route('/register/<token>', methods=['GET', 'POST'])
def register(token):
    serre = Serre.query.filter_by(token=token).first_or_404()
    if serre.token_used:
        return render_template('token_used.html', serre=serre)
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = (request.form.get('password') or '').strip()
        # vérifications AVANT de consommer le token de la serre
        if not username:
            return render_template('register.html', serre=serre, erreur="Choisis un nom d'utilisateur")
        if len(password) < 6:
            return render_template('register.html', serre=serre, erreur="Mot de passe trop court (6 caractères minimum)")
        if Utilisateur.query.filter_by(username=username).first():
            return render_template('register.html', serre=serre, erreur="Ce nom d'utilisateur est déjà pris")
        user = Utilisateur(
            username = username,
            password = generate_password_hash(password),
            serre_id = serre.id
        )
        serre.token_used = True
        db.session.add(user)
        db.session.commit()
        session['user_id'] = user.id
        return redirect(url_for('dashboard'))
    return render_template('register.html', serre=serre, erreur=None)

# --- CONNEXION UTILISATEUR ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        password = (request.form.get('password') or '').strip()
        user = Utilisateur.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            session['user_id'] = user.id
            return redirect(url_for('dashboard'))
        return render_template('login.html', erreur="Nom d'utilisateur ou mot de passe incorrect")
    return render_template('login.html', erreur=None)

# --- DASHBOARD UTILISATEUR ---
@app.route('/serre')
def dashboard():
    if not session.get('user_id'):
        return redirect(url_for('login'))
    user    = db.session.get(Utilisateur, session['user_id'])
    if not user:
        # compte supprimé (ex. serre supprimée par l'admin) : on vide la session
        session.pop('user_id', None)
        return redirect(url_for('login'))
    serre   = user.serre
    mesures = Mesure.query.filter_by(serre_id=serre.id).order_by(Mesure.date.desc()).limit(8).all()
    mesures.reverse()
    derniere = mesures[-1] if mesures else None
    return render_template('dashboard.html', serre=serre, mesures=mesures, derniere=derniere)

# --- DÉCONNEXION UTILISATEUR ---
@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('login'))

# --- API ESP32 ---
@app.route('/api/data', methods=['POST'])
def recevoir_data():
    # attendu : {"token": "...", "humidite": 35, "batterie": 75}
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'error': 'JSON attendu'}), 400
    token = data.get('token')
    if not isinstance(token, str) or not token:
        return jsonify({'error': 'Token invalide'}), 401
    serre = Serre.query.filter_by(token=token).first()
    if not serre:
        return jsonify({'error': 'Token invalide'}), 401
    valeurs = {}
    for champ in ('humidite', 'batterie'):
        v = data.get(champ)
        if v is None or isinstance(v, bool):
            return jsonify({'error': f'{champ} manquant ou invalide'}), 400
        try:
            v = float(v)
        except (TypeError, ValueError):
            return jsonify({'error': f'{champ} doit être un nombre'}), 400
        if not math.isfinite(v) or not 0 <= v <= 100:
            return jsonify({'error': f'{champ} doit être entre 0 et 100'}), 400
        valeurs[champ] = v
    # mesure précédente (lue avant d'ajouter la nouvelle) pour l'alerte « a soif »
    precedente = Mesure.query.filter_by(serre_id=serre.id).order_by(Mesure.date.desc(), Mesure.id.desc()).first()
    mesure = Mesure(
        humidite = valeurs['humidite'],
        batterie = valeurs['batterie'],
        serre_id = serre.id
    )
    db.session.add(mesure)
    db.session.commit()
    # une seule alerte au passage sous le seuil (pas à chaque mesure) ; alerte_discord ne plante jamais
    if mesure.humidite < SEUIL_SEC and (precedente is None or precedente.humidite >= SEUIL_SEC):
        alerte_discord(f"💧 **{serre.nom}** a soif : humidité {int(mesure.humidite)} %")
    return jsonify({'status': 'ok'}), 200

# --- LOGIN ADMIN ---
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        # si ADMIN_PASSWORD n'est pas définie, secret_ok refuse toujours (admin désactivé)
        if secret_ok(request.form.get('password'), ADMIN_PASSWORD):
            session['admin'] = True
            return redirect(url_for('admin_dashboard'))
        if not ADMIN_PASSWORD:
            return render_template('admin_login.html', erreur="Admin désactivé (ADMIN_PASSWORD non définie)")
        return render_template('admin_login.html', erreur=True)
    return render_template('admin_login.html', erreur=False)

# --- DASHBOARD ADMIN ---
@app.route('/admin')
def admin_dashboard():
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    serres = Serre.query.all()
    data = []
    for s in serres:
        derniere = Mesure.query.filter_by(serre_id=s.id).order_by(Mesure.date.desc()).first()
        data.append({'serre': s, 'derniere': derniere})
    return render_template('admin.html', data=data)

# --- BUREAU DES AGENTS (ADMIN) ---
@app.route('/admin/bureau')
def admin_bureau():
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    return render_template('bureau.html')

# Les 6 personnages du bureau et la taille maximale acceptée pour l'état envoyé
BUREAU_AGENTS = ('coordinateur', 'designer-site', 'backend-flask', 'esp32', 'impression-3d', 'terminal')
BUREAU_TAILLE_MAX = 10 * 1024   # 10 Ko (un état normal fait ~1 Ko)

def entier(v, defaut):
    # renvoie v si c'est un vrai entier (pas un booléen), sinon la valeur par défaut
    return v if isinstance(v, int) and not isinstance(v, bool) else defaut

# --- RÉCEPTION DE L'ÉTAT DU BUREAU (envoyé par le hook Claude Code du PC) ---
@app.route('/api/bureau', methods=['POST'])
def recevoir_bureau():
    if not secret_ok(request.headers.get('X-Bureau-Token'), BUREAU_TOKEN):
        return jsonify({'error': 'non autorisé'}), 401
    # taille limitée : on refuse avant de tout lire
    if request.content_length is not None and request.content_length > BUREAU_TAILLE_MAX:
        return jsonify({'error': 'trop gros'}), 413
    brut = request.stream.read(BUREAU_TAILLE_MAX + 1)
    if len(brut) > BUREAU_TAILLE_MAX:
        return jsonify({'error': 'trop gros'}), 413
    try:
        data = json.loads(brut.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return jsonify({'error': 'JSON attendu'}), 400
    if not isinstance(data, dict) or not isinstance(data.get('agents'), dict):
        return jsonify({'error': 'champ agents manquant'}), 400
    # on ne garde que les agents connus et les champs utiles (rien d'autre n'est stocké)
    agents = {}
    for nom in BUREAU_AGENTS:
        a = data['agents'].get(nom)
        if not isinstance(a, dict):
            continue
        tache = a.get('tache')
        agents[nom] = {
            'etat':   a.get('etat') if a.get('etat') in ('working', 'idle') else 'idle',
            'tache':  tache[:120] if isinstance(tache, str) else 'Au repos',
            'nb':     max(0, min(99, entier(a.get('nb'), 0))),
            'depuis': entier(a.get('depuis'), 0),
        }
    if not agents:
        return jsonify({'error': 'aucun agent connu'}), 400
    maj = entier(data.get('maj'), int(datetime.now(timezone.utc).timestamp() * 1000))
    ligne = db.session.get(BureauEtat, 1)
    if ligne is None:
        ligne = BureauEtat(id=1, contenu='{}')
        db.session.add(ligne)
    else:
        # les envois partent en parallèle : on ignore un état plus ancien que celui déjà en base
        try:
            ancien = json.loads(ligne.contenu).get('maj', 0)
        except (ValueError, AttributeError):
            ancien = 0
        if isinstance(ancien, int) and ancien > maj:
            return jsonify({'status': 'ok'}), 200
    ligne.contenu = json.dumps({'maj': maj, 'agents': agents}, ensure_ascii=False)
    ligne.maj = maintenant_utc()
    db.session.commit()
    return jsonify({'status': 'ok'}), 200

# --- ÉTAT DU BUREAU LU PAR LA PAGE /admin/bureau (chargé comme un script) ---
@app.route('/admin/etat.js')
def bureau_etat_js():
    # pas de redirection vers une page HTML : la page charge ce fichier comme un script
    if not session.get('admin'):
        return 'interdit', 403, {'Content-Type': 'text/plain; charset=utf-8', 'Cache-Control': 'no-store'}
    ligne = db.session.get(BureauEtat, 1)
    if ligne is None:
        # rien reçu : la page reste en simulation
        return 'aucun état', 404, {'Content-Type': 'text/plain; charset=utf-8', 'Cache-Control': 'no-store'}
    # contenu déjà nettoyé à l'enregistrement ; on échappe « < » pour ne jamais fermer une balise script
    texte = 'window.POKESERRE_ETAT = ' + ligne.contenu.replace('<', '\\u003c') + ';\n'
    reponse = app.response_class(texte, mimetype='application/javascript')
    reponse.headers['Cache-Control'] = 'no-store'
    return reponse

# --- AJOUTER SERRE (ADMIN) ---
@app.route('/admin/ajouter', methods=['POST'])
def ajouter_serre():
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    nom   = (request.form.get('nom') or '').strip()
    if not nom:
        return redirect(url_for('admin_dashboard'))   # nom vide : on ne crée rien
    token = secrets.token_hex(8)
    serre = Serre(nom=nom, token=token)
    db.session.add(serre)
    db.session.commit()
    return redirect(url_for('admin_dashboard'))

# --- SUPPRIMER SERRE (ADMIN) ---
@app.route('/admin/supprimer/<int:serre_id>', methods=['POST'])
def supprimer_serre(serre_id):
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    serre = db.get_or_404(Serre, serre_id)
    Mesure.query.filter_by(serre_id=serre.id).delete()
    Utilisateur.query.filter_by(serre_id=serre.id).delete()
    db.session.delete(serre)
    db.session.commit()
    return redirect(url_for('admin_dashboard'))

# --- LOGOUT ADMIN ---
@app.route('/admin/logout')
def admin_logout():
    session.pop('admin', None)
    return redirect(url_for('admin_login'))

# --- SANTÉ (pour UptimeRobot / garder le serveur éveillé) ---
@app.route('/health')
def health():
    return 'ok', 200

# --- CONTRÔLE AUTOMATIQUE (appelé toutes les heures par GitHub Actions) ---
def alerte_discord(texte):
    if not DISCORD_WEBHOOK_URL:
        return
    try:
        req = urllib.request.Request(DISCORD_WEBHOOK_URL, data=json.dumps({'content': texte}).encode('utf-8'),
                                     headers={'Content-Type': 'application/json', 'User-Agent': 'pokeserre'})
        urllib.request.urlopen(req, timeout=10).close()
    except Exception as e:
        print('Erreur Discord :', e)

@app.route('/api/watchdog')
def watchdog():
    if not secret_ok(request.headers.get('X-Cron-Token'), CRON_TOKEN):
        return jsonify({'error': 'non autorisé'}), 401
    maintenant = maintenant_utc()
    alertes = []
    for s in Serre.query.all():
        mesures = Mesure.query.filter_by(serre_id=s.id).order_by(Mesure.date.desc()).limit(2).all()
        if not mesures:
            continue
        derniere = mesures[0]
        age = maintenant - derniere.date
        # une seule alerte par panne : on ne prévient que dans l'heure qui suit le seuil
        if timedelta(hours=HEURES_SILENCE) <= age < timedelta(hours=HEURES_SILENCE + 1):
            alertes.append(f"📡 **{s.nom}** n'a rien envoyé depuis {int(age.total_seconds() // 3600)} h (batterie vide ou WiFi perdu ?)")
        # batterie : seulement au moment où elle passe sous le seuil, et sur une mesure récente (< 1 h)
        # (le contrôle tourne toutes les heures : sinon la même mesure redéclencherait l'alerte à chaque passage)
        if age < timedelta(hours=1) and derniere.batterie < SEUIL_BATTERIE and (len(mesures) < 2 or mesures[1].batterie >= SEUIL_BATTERIE):
            alertes.append(f"🔋 **{s.nom}** : batterie à {int(derniere.batterie)} %, pense à la recharger")
    for a in alertes:
        alerte_discord(a)
    return jsonify({'status': 'ok', 'alertes': len(alertes)}), 200

# --- DÉMARRAGE ---
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=False)