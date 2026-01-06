import os, uuid
from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
from sqlalchemy import inspect, text

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'save_money_safe_final_2026')

# --- 資料庫連線設定 ---
db_url = os.environ.get('DATABASE_URL')
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)
app.config['SQLALCHEMY_DATABASE_URI'] = db_url or 'sqlite:///savings_v21.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024 

db = SQLAlchemy(app)
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# --- 資料庫模型 ---
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
    note = db.Column(db.String(200))
    photo = db.Column(db.String(200)) 
    save_date = db.Column(db.String(10))
    created_at = db.Column(db.DateTime, default=datetime.now)

with app.app_context():
    db.create_all()

# --- 路由與邏輯 ---
@app.route('/')
def index():
    if 'user_id' not in session: return redirect(url_for('login'))
    curr_user = User.query.get(session['user_id'])
    if not curr_user: return redirect(url_for('logout'))
    group = Group.query.filter_by(group_uuid=curr_user.group_uuid).first()
    my_records = SavingRecord.query.filter_by(user_id=curr_user.id).all()
    saved_days = {r.day_number: {'id': r.id, 'amount': r.amount, 'note': (r.note or "").replace("'", "\\'"), 'date': r.save_date or "", 'photo': r.photo or ""} for r in my_records}
    my_current = sum(r.amount for r in my_records)
    my_target = 66795 * curr_user.multiplier
    my_pct = round((my_current / my_target * 100), 1) if my_target > 0 else 0
    return render_template('index.html', user=curr_user, group=group, current=my_current, target=my_target, my_pct=my_pct, saved_days=saved_days, today=datetime.now().strftime('%Y-%m-%d'))

@app.route('/update_profile', methods=['POST'])
def update_profile():
    user = User.query.get(session['user_id'])
    new_m = int(request.form.get('multiplier', 1))
    if user.multiplier != new_m:
        SavingRecord.query.filter_by(user_id=user.id).delete()
        flash('倍率已變更，紀錄已清空重置。')
    user.multiplier = new_m
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/update_password', methods=['POST'])
def update_password():
    user = User.query.get(session['user_id'])
    if check_password_hash(user.password, request.form.get('old_password')):
        user.password = generate_password_hash(request.form.get('new_password'), method='pbkdf2:sha256')
        db.session.commit(); flash('密碼修改成功！')
    else: flash('舊密碼錯誤。')
    return redirect(url_for('index'))

@app.route('/delete_account', methods=['POST'])
def delete_account():
    user = User.query.get(session.get('user_id'))
    if user:
        SavingRecord.query.filter_by(user_id=user.id).delete()
        db.session.delete(user); db.session.commit(); session.clear(); flash('帳號已永久刪除。')
    return redirect(url_for('login'))

@app.route('/reset_all_records')
def reset_all_records():
    SavingRecord.query.filter_by(user_id=session.get('user_id')).delete()
    db.session.commit(); flash('紀錄已全部清空。')
    return redirect(url_for('index'))

@app.route('/quick_update_name', methods=['POST'])
def quick_update_name():
    user = User.query.get(session.get('user_id'))
    g = Group.query.filter_by(group_uuid=user.group_uuid).first()
    if g:
        g.name = request.form.get('new_group_name')
        db.session.commit()
    return redirect(url_for('index'))

@app.route('/save', methods=['POST'])
def save():
    user = User.query.get(session['user_id'])
    f = request.files.get('photo_file')
    fname = f"{uuid.uuid4().hex}.{f.filename.rsplit('.', 1)[1].lower()}" if f and f.filename != '' else None
    if fname: f.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
    new_rec = SavingRecord(user_id=user.id, day_number=int(request.form['day_number']), amount=int(request.form['day_number']) * user.multiplier, note=request.form.get('note'), save_date=request.form.get('save_date'), photo=fname)
    db.session.add(new_rec); db.session.commit()
    return redirect(url_for('index'))

@app.route('/update', methods=['POST'])
def update():
    record = SavingRecord.query.get(request.form.get('record_id'))
    if record and record.user_id == session.get('user_id'):
        record.note = request.form.get('note'); record.save_date = request.form.get('save_date')
        f = request.files.get('photo_file')
        if f and f.filename != '':
            fname = f"{uuid.uuid4().hex}.{f.filename.rsplit('.', 1)[1].lower()}"
            f.save(os.path.join(app.config['UPLOAD_FOLDER'], fname)); record.photo = fname
        db.session.commit()
    return redirect(url_for('index'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = User.query.filter_by(username=request.form['username']).first()
        if u and check_password_hash(u.password, request.form['password']):
            session['user_id'] = u.id; return redirect(url_for('index'))
        flash('帳號或密碼錯誤')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        uname = request.form['username'].strip()
        if User.query.filter_by(username=uname).first():
            flash('此帳號已存在'); return redirect(url_for('register'))
        pwd = generate_password_hash(request.form['password'], method='pbkdf2:sha256')
        juuid = request.form.get('join_uuid', '').strip()
        m = int(request.form.get('multiplier', 1))
        if juuid:
            g = Group.query.filter_by(group_uuid=juuid).first()
            if not g: flash('邀請碼無效'); return redirect(url_for('register'))
            new_u = User(username=uname, password=pwd, group_uuid=juuid, multiplier=m)
        else:
            new_uuid = str(uuid.uuid4())[:8]
            db.session.add(Group(group_uuid=new_uuid, name=f'{uname}的計畫'))
            new_u = User(username=uname, password=pwd, group_uuid=new_uuid, multiplier=m)
        db.session.add(new_u); db.session.commit(); return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5001, debug=True)