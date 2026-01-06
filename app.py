import os, uuid
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'save_money_2026_final')

# --- 資料庫設定 ---
db_url = os.environ.get('DATABASE_URL')
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url or 'sqlite:///savings.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

class Group(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_uuid = db.Column(db.String(8), unique=True, nullable=False)
    name = db.Column(db.String(100))

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False) 
    group_uuid = db.Column(db.String(8), db.ForeignKey('group.group_uuid'))
    multiplier = db.Column(db.Integer, default=1)

class SavingRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    day_number = db.Column(db.Integer)
    amount = db.Column(db.Integer)
    save_date = db.Column(db.String(10))

with app.app_context():
    db.create_all()

@app.route('/')
def index():
    if 'user_id' not in session: return redirect(url_for('login'))
    u = User.query.get(session['user_id'])
    if not u: return redirect(url_for('logout'))
    g = Group.query.filter_by(group_uuid=u.group_uuid).first()
    recs = SavingRecord.query.filter_by(user_id=u.id).all()
    
    # 建立已存天數的 Set，方便前端判斷
    saved = {r.day_number for r in recs}
    cur = sum(r.amount for r in recs)
    tar = 66795 * u.multiplier
    pct = round((cur / tar * 100), 1) if tar > 0 else 0
    
    return render_template('index.html', user=u, group=g, current=cur, target=tar, my_pct=pct, saved_days=saved, today=datetime.now().strftime('%Y-%m-%d'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        uname = request.form['username'].strip()
        # 確保抓取自定義計畫名稱
        g_name = request.form.get('group_name', '').strip() or f'{uname}的計畫'
        pwd = generate_password_hash(request.form['password'], method='pbkdf2:sha256')
        m = int(request.form.get('multiplier') or 1)
        
        u_uuid = str(uuid.uuid4())[:8]
        db.session.add(Group(group_uuid=u_uuid, name=g_name))
        db.session.add(User(username=uname, password=pwd, group_uuid=u_uuid, multiplier=m))
        db.session.commit()
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = User.query.filter_by(username=request.form['username']).first()
        if u and check_password_hash(u.password, request.form['password']):
            session['user_id'] = u.id
            return redirect(url_for('index'))
    return render_template('login.html')

@app.route('/save', methods=['POST'])
def save():
    u = User.query.get(session['user_id'])
    day = int(request.form['day_number'])
    if not SavingRecord.query.filter_by(user_id=u.id, day_number=day).first():
        db.session.add(SavingRecord(user_id=u.id, day_number=day, amount=day * u.multiplier, save_date=request.form.get('save_date')))
        db.session.commit()
    return redirect(url_for('index'))

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001)