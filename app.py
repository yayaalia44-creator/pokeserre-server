from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import secrets
import os
 
# --- CONFIGURATION ---
app = Flask(__name__)
app.secret_key = secrets.token_hex(32)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///pokeserre.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
 
db = SQLAlchemy(app)
 
# --- MODELES BASE DE DONNÉES ---
class Serre(db.Model):
    id       = db.Column(db.Integer, primary_key=True)
    nom      = db.Column(db.String(100), nullable=False)
    token    = db.Column(db.String(64), unique=True, nullable=False)
    données  = db.relationship('Mesure', backref='serre', lazy=True)
 
class Mesure(db.Model):
    id        = db.Column(db.Integer, primary_key=True)
    humidite  = db.Column(db.Float, nullable=False)
    batterie  = db.Column(db.Float, nullable=False)
    date      = db.Column(db.DateTime, default=datetime.utcnow)
    serre_id  = db.Column(db.Integer, db.ForeignKey('serre.id'), nullable=False)
 
# --- ADMIN ---
ADMIN_PASSWORD = "Yasser44340"
 
# --- ROUTES ESP32 ---
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
 
# --- ROUTE DASHBOARD UTILISATEUR ---
@app.route('/serre/<token>')
def dashboard_serre(token):
    serre   = Serre.query.filter_by(token=token).first_or_404()
    mesures = Mesure.query.filter_by(serre_id=serre.id).order_by(Mesure.date.desc()).limit(8).all()
    mesures.reverse()
    derniere = mesures[-1] if mesures else None
    return render_template('dashboard.html', serre=serre, mesures=mesures, derniere=derniere)
 
# --- ROUTE LOGIN ADMIN ---
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        if request.form.get('password') == ADMIN_PASSWORD:
            session['admin'] = True
            return redirect(url_for('admin_dashboard'))
        return render_template('admin_login.html', erreur=True)
    return render_template('admin_login.html', erreur=False)
 
# --- ROUTE DASHBOARD ADMIN ---
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
 
# --- ROUTE AJOUTER SERRE (ADMIN) ---
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
 
# --- ROUTE LOGOUT ADMIN ---
@app.route('/admin/logout')
def admin_logout():
    session.pop('admin', None)
    return redirect(url_for('admin_login'))
 
# --- DÉMARRAGE ---
if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)


