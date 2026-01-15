import os, uuid
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "savings_365_v13_datepick"
# 檢查是否有 Render 提供的資料庫網址環境變數
database_url = os.environ.get('DATABASE_URL')

if database_url:
    # 修正 Render 的網址開頭 (Render 給的是 postgres:// 但 SQLAlchemy 需要 postgresql://)
    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = database_url
else:
    # 如果沒有環境變數（例如在自己電腦測試時），才使用原本的 SQLite
    db_path = os.path.join(os.path.dirname(__file__), 'savings.db')
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + db_path
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# --- 資料模型 ---
class Group(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    group_uuid = db.Column(db.String(8), unique=True, nullable=False)
    name = db.Column(db.String(100))

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    group_uuid = db.Column(db.String(8))
    multiplier = db.Column(db.Integer, default=1)

class SavingRecord(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer)
    day_number = db.Column(db.Integer)
    amount = db.Column(db.Integer)
    note = db.Column(db.String(200), default="")
    saved_date = db.Column(db.DateTime, default=datetime.now)

with app.app_context():
    db.create_all()

# --- 核心邏輯 API ---
@app.route('/api/data')
def get_dashboard_data():
    if 'user_id' not in session: return jsonify({'error': 'unauthorized'}), 401
    u = User.query.get(session['user_id'])
    if not u:
        session.clear()
        return jsonify({'error': 'user_not_found'}), 401
        
    g = Group.query.filter_by(group_uuid=u.group_uuid).first()
    members = User.query.filter_by(group_uuid=u.group_uuid).all()
    
    leaderboard = []
    for m in members:
        recs = SavingRecord.query.filter_by(user_id=m.id).all()
        cur = sum(r.amount for r in recs)
        target = 66795 * m.multiplier
        leaderboard.append({
            'name': m.username, 
            'pct': round((cur/target*100),1) if target > 0 else 0, 
            'is_me': m.id == u.id,
            'multiplier': m.multiplier,
            'target': target
        })
    leaderboard.sort(key=lambda x: x['pct'], reverse=True)

    records = SavingRecord.query.filter_by(user_id=u.id).all()
    my_recs = {}
    for r in records:
        # 這裡格式化為 YYYY/MM/DD 供前端顯示
        date_str = r.saved_date.strftime('%Y/%m/%d') if r.saved_date else ""
        my_recs[r.day_number] = {'note': r.note, 'date': date_str}

    grid = []
    for d in range(1, 366):
        rec_data = my_recs.get(d, None)
        grid.append({
            'd': d, 
            'a': d * u.multiplier, 
            's': 1 if rec_data else 0, 
            'n': rec_data['note'] if rec_data else "",
            'dt': rec_data['date'] if rec_data else ""
        })

    return jsonify({
        'group_name': g.name if g else "我的計畫", 'group_uuid': u.group_uuid, 'user_name': u.username,
        'multiplier': u.multiplier, 'current': sum(r.amount for r in records),
        'target': 66795 * u.multiplier, 'leaderboard': leaderboard, 'grid': grid
    })

# --- 頁面路由 ---
@app.route('/')
def index():
    if 'user_id' not in session: return redirect(url_for('login'))
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        un = request.form.get('username')
        if User.query.filter_by(username=un).first():
            flash("帳號已存在，請換一個名字")
            return redirect(url_for('register'))
        
        guuid = request.form.get('join_uuid')
        if guuid:
            group = Group.query.filter_by(group_uuid=guuid).first()
            if not group:
                flash("邀請碼無效，請確認後再試")
                return redirect(url_for('register'))
        else:
            guuid = str(uuid.uuid4())[:8]
            g_name = request.form.get('group_name') or "新計畫"
            db.session.add(Group(group_uuid=guuid, name=g_name))
            
        m_val = request.form.get('multiplier')
        mult = int(request.form.get('custom_multiplier', 1)) if m_val == 'custom' else int(m_val)
        
        u = User(username=un, password=generate_password_hash(request.form.get('password'), method='pbkdf2:sha256'), group_uuid=guuid, multiplier=mult)
        db.session.add(u)
        db.session.commit()
        session['user_id'] = u.id
        return redirect(url_for('index'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form.get('username')).first()
        if user and check_password_hash(user.password, request.form.get('password')):
            session['user_id'] = user.id; return redirect(url_for('index'))
        flash("帳號或密碼錯誤")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear(); return redirect(url_for('login'))

# --- 功能操作路由 ---
@app.route('/save', methods=['POST'])
def save_money():
    if 'user_id' not in session: return redirect(url_for('login'))
    u = User.query.get(session['user_id'])
    
    day = int(request.form.get('day_number'))
    note = request.form.get('note')
    date_str = request.form.get('saved_date') # 取得前端選的日期 (YYYY-MM-DD)

    # 處理日期：如果有選則用選的，沒選則用當下
    if date_str:
        try:
            final_date = datetime.strptime(date_str, '%Y-%m-%d')
        except:
            final_date = datetime.now()
    else:
        final_date = datetime.now()

    rec = SavingRecord.query.filter_by(user_id=u.id, day_number=day).first()
    if rec:
        rec.note = note
        rec.saved_date = final_date # 更新日期
    else:
        amount = day * u.multiplier
        new_rec = SavingRecord(user_id=u.id, day_number=day, amount=amount, note=note, saved_date=final_date)
        db.session.add(new_rec)
    
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/delete_record', methods=['POST'])
def delete_record():
    if 'user_id' not in session: return redirect(url_for('login'))
    day = int(request.form.get('day_number'))
    SavingRecord.query.filter_by(user_id=session['user_id'], day_number=day).delete()
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/update_group_name', methods=['POST'])
def update_group_name():
    if 'user_id' not in session: return redirect(url_for('login'))
    u = User.query.get(session['user_id'])
    if u and u.group_uuid:
        g = Group.query.filter_by(group_uuid=u.group_uuid).first()
        if g:
            new_name = request.form.get('group_name')
            if new_name:
                g.name = new_name
                db.session.commit()
    return redirect(url_for('index'))

@app.route('/update_multiplier', methods=['POST'])
def update_multiplier():
    if 'user_id' not in session: return redirect(url_for('login'))
    u = User.query.get(session['user_id'])
    new_m = int(request.form.get('multiplier'))
    u.multiplier = new_m
    SavingRecord.query.filter_by(user_id=u.id).delete()
    db.session.commit()
    return redirect(url_for('index'))

@app.route('/change_password', methods=['POST'])
def change_password():
    if 'user_id' not in session: return redirect(url_for('login'))
    u = User.query.get(session['user_id'])
    old_p = request.form.get('old_p')
    new_p = request.form.get('new_p')
    
    if check_password_hash(u.password, old_p):
        u.password = generate_password_hash(new_p, method='pbkdf2:sha256')
        db.session.commit()
        session.clear()
        flash("密碼修改成功，請重新登入")
        return redirect(url_for('login'))
    else:
        return "<script>alert('舊密碼錯誤');window.location.href='/';</script>"

@app.route('/delete_account', methods=['POST'])
def delete_account():
    if 'user_id' not in session: return redirect(url_for('login'))
    uid = session['user_id']
    SavingRecord.query.filter_by(user_id=uid).delete()
    User.query.filter_by(id=uid).delete()
    db.session.commit()
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True, port=5001)