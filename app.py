from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import secrets
import os

# --- CONFIGURATION ---
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///pokeserre.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'pokeserre_admin')

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
    date      = db.Column(db.DateTime, default=datetime.utcnow)
    serre_id  = db.Column(db.Integer, db.ForeignKey('serre.id'), nullable=False)

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
        username = request.form.get('username').strip()
        password = request.form.get('password').strip()
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
        username = request.form.get('username').strip()
        password = request.form.get('password').strip()
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
    user    = Utilisateur.query.get(session['user_id'])
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
    data  = request.json
    token = data.get('token')
    serre = Serre.query.filter_by(token=token).first()
    if not serre:
        return jsonify({'error': 'Token invalide'}), 401
    mesure = Mesure(
        humidite = data.get('humidite'),
        batterie = data.get('batterie'),
        serre_id = serre.id
    )
    db.session.add(mesure)
    db.session.commit()
    return jsonify({'status': 'ok'}), 200

# --- LOGIN ADMIN ---
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['admin'] = True
            return redirect(url_for('admin_dashboard'))
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

# --- AJOUTER SERRE (ADMIN) ---
@app.route('/admin/ajouter', methods=['POST'])
def ajouter_serre():
    if not session.get('admin'):
        return redirect(url_for('admin_login'))
    nom   = request.form.get('nom')
    token = secrets.token_hex(8)
    serre = Serre(nom=nom, token=token)
    db.session.add(serre)
    db.session.commit()
    return redirect(url_for('admin_dashboard'))

# --- LOGOUT ADMIN ---
@app.route('/admin/logout')
def admin_logout():
    session.pop('admin', None)
    return redirect(url_for('admin_login'))

# --- DÉMARRAGE ---
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)