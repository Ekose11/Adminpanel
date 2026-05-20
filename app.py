from flask import Flask, request, jsonify, redirect, url_for, render_template_string, session
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, date
import sqlite3, secrets, os, io, base64, segno

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'premium-personel-secret-key')
DB = os.environ.get('DATABASE_PATH', 'personel.db')
ADMIN_USER = os.environ.get('ADMIN_USER', 'eren')
ADMIN_PASS = os.environ.get('ADMIN_PASS', '1234')

def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = db(); c = con.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS staff(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        salary REAL DEFAULT 0,
        advance REAL DEFAULT 0,
        annual_leave INTEGER DEFAULT 14,
        active INTEGER DEFAULT 1,
        qr_token TEXT UNIQUE NOT NULL
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS attendance(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        staff_id INTEGER NOT NULL,
        type TEXT NOT NULL,
        created_at TEXT NOT NULL,
        note TEXT DEFAULT '',
        FOREIGN KEY(staff_id) REFERENCES staff(id)
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS leave_requests(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        staff_id INTEGER NOT NULL,
        start_date TEXT,
        end_date TEXT,
        days INTEGER DEFAULT 1,
        status TEXT DEFAULT 'Beklemede',
        created_at TEXT NOT NULL,
        FOREIGN KEY(staff_id) REFERENCES staff(id)
    )''')
    existing = c.execute('SELECT id FROM staff WHERE username=?', ('eren',)).fetchone()
    if not existing:
        c.execute('INSERT INTO staff(name, username, password_hash, salary, advance, annual_leave, qr_token) VALUES(?,?,?,?,?,?,?)',
                  ('Eren', 'eren', generate_password_hash('1234'), 0, 0, 14, secrets.token_urlsafe(32)))
    con.commit(); con.close()

init_db()

def staff_to_dict(r):
    return dict(id=r['id'], name=r['name'], username=r['username'], salary=r['salary'], advance=r['advance'], remaining_salary=r['salary']-r['advance'], annual_leave=r['annual_leave'], active=bool(r['active']))

def make_qr_data(staff_id, token):
    return f'PERSONELQR:{staff_id}:{token}'

def qr_svg_base64(data):
    qr = segno.make(data, error='m')
    buf = io.BytesIO()
    qr.save(buf, kind='svg', scale=8, xmldecl=False)
    return base64.b64encode(buf.getvalue()).decode('utf-8')

LOGIN_HTML = '''<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Personel Sistemi</title><style>
*{box-sizing:border-box}body{margin:0;min-height:100vh;font-family:Inter,Arial,sans-serif;background:radial-gradient(circle at top,#113b67,#050b14 65%);color:#fff;display:grid;place-items:center}.card{width:min(430px,92vw);padding:34px;border:1px solid rgba(255,255,255,.16);border-radius:28px;background:linear-gradient(145deg,rgba(255,255,255,.18),rgba(255,255,255,.06));box-shadow:0 30px 80px rgba(0,0,0,.55);backdrop-filter:blur(18px)}.logo{width:74px;height:74px;border-radius:24px;margin:auto;background:linear-gradient(135deg,#64b5ff,#0b4f92);display:grid;place-items:center;box-shadow:0 14px 40px rgba(0,138,255,.45)}.logo:before{content:'👥';font-size:36px}.title{text-align:center;margin:18px 0 6px;font-size:26px;font-weight:900}.sub{text-align:center;color:#b8cee8;margin-bottom:24px}input{width:100%;padding:16px;margin:9px 0;border-radius:16px;border:1px solid rgba(255,255,255,.18);background:rgba(3,14,28,.7);color:#fff;font-size:16px}button{width:100%;padding:16px;margin-top:14px;border:0;border-radius:16px;background:linear-gradient(135deg,#23a7ff,#0557bc);color:white;font-weight:900;font-size:16px;box-shadow:0 12px 30px rgba(0,114,255,.35)}.err{color:#ffb3b3;text-align:center}</style></head><body><form class="card" method="post"><div class="logo"></div><div class="title">Personel Sistemi</div><div class="sub">Premium yönetim paneli</div>{err}<input name="username" placeholder="Kullanıcı adı" required><input name="password" placeholder="Şifre" type="password" required><button>Giriş Yap</button></form></body></html>'''

DASH_HTML = '''<!doctype html><html lang="tr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Personel Sistemi</title><style>
*{box-sizing:border-box}body{margin:0;font-family:Inter,Arial,sans-serif;background:#07111f;color:#eaf4ff}.top{position:sticky;top:0;padding:18px 26px;background:rgba(5,18,35,.86);backdrop-filter:blur(18px);border-bottom:1px solid rgba(255,255,255,.1);display:flex;justify-content:space-between;align-items:center}.brand{display:flex;gap:12px;align-items:center;font-weight:900;font-size:20px}.logo{width:42px;height:42px;border-radius:14px;background:linear-gradient(135deg,#63c7ff,#084a95);display:grid;place-items:center}.logo:before{content:'👥'}.wrap{padding:26px;max-width:1200px;margin:auto}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:16px}.card{border:1px solid rgba(255,255,255,.11);border-radius:24px;padding:20px;background:linear-gradient(145deg,rgba(255,255,255,.1),rgba(255,255,255,.035));box-shadow:0 18px 50px rgba(0,0,0,.28)}.num{font-size:34px;font-weight:900;margin-top:8px}.muted{color:#97b4d4}.panel{margin-top:22px}.staff{display:grid;grid-template-columns:1fr auto auto;gap:12px;align-items:center;margin:12px 0;padding:16px;border-radius:18px;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.09)}a,button{background:linear-gradient(135deg,#20a4ff,#0756bd);color:white;text-decoration:none;border:0;border-radius:12px;padding:11px 14px;font-weight:800}.danger{background:linear-gradient(135deg,#ff4b5f,#9d1224)}.qr{max-width:220px;border-radius:20px;background:white;padding:10px}.form{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px}.form input{padding:13px;border-radius:12px;border:1px solid rgba(255,255,255,.12);background:#0c1b2f;color:white}</style></head><body><div class="top"><div class="brand"><div class="logo"></div>Personel Sistemi</div><a class="danger" href="/logout">Çıkış</a></div><div class="wrap"><div class="grid"><div class="card"><div class="muted">Toplam Personel</div><div class="num">{{total}}</div></div><div class="card"><div class="muted">Bugün Giriş</div><div class="num">{{entries}}</div></div><div class="card"><div class="muted">Bugün Çıkış</div><div class="num">{{exits}}</div></div><div class="card"><div class="muted">Aktif Sistem</div><div class="num">QR</div></div></div><div class="card panel"><h2>Personel Ekle</h2><form class="form" method="post" action="/admin/staff/add"><input name="name" placeholder="Ad Soyad"><input name="username" placeholder="Kullanıcı adı"><input name="password" placeholder="Şifre"><input name="salary" placeholder="Maaş"><button>Ekle</button></form></div><div class="card panel"><h2>Personel Listesi</h2>{% for s in staff %}<div class="staff"><div><b>{{s.name}}</b><div class="muted">@{{s.username}} · Maaş: {{s.salary}} · Avans: {{s.advance}} · İzin: {{s.annual_leave}}</div></div><a href="/admin/qr/{{s.id}}">QR Aç</a><a class="danger" href="/admin/staff/delete/{{s.id}}">Sil</a></div>{% endfor %}</div><div class="card panel"><h2>Son Hareketler</h2>{% for l in logs %}<div class="staff"><div><b>{{l.name}}</b><div class="muted">{{l.type}} · {{l.created_at}}</div></div></div>{% endfor %}</div></div></body></html>'''

@app.route('/', methods=['GET','POST'])
@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        if request.form.get('username') == ADMIN_USER and request.form.get('password') == ADMIN_PASS:
            session['admin'] = True; return redirect('/dashboard')
        return render_template_string(LOGIN_HTML, err='<div class="err">Kullanıcı adı veya şifre hatalı</div>')
    return render_template_string(LOGIN_HTML, err='')

@app.route('/logout')
def logout():
    session.clear(); return redirect('/')

def need_admin():
    return session.get('admin') is True

@app.route('/dashboard')
@app.route('/admin')
@app.route('/adminpanel')
@app.route('/web')
def dashboard():
    if not need_admin(): return redirect('/')
    con = db()
    staff = con.execute('SELECT * FROM staff ORDER BY id DESC').fetchall()
    today = date.today().isoformat()
    entries = con.execute("SELECT COUNT(*) c FROM attendance WHERE type='entry' AND created_at LIKE ?", (today+'%',)).fetchone()['c']
    exits = con.execute("SELECT COUNT(*) c FROM attendance WHERE type='exit' AND created_at LIKE ?", (today+'%',)).fetchone()['c']
    logs = con.execute('SELECT staff.name, attendance.type, attendance.created_at FROM attendance JOIN staff ON staff.id=attendance.staff_id ORDER BY attendance.id DESC LIMIT 20').fetchall()
    con.close()
    return render_template_string(DASH_HTML, staff=staff, total=len(staff), entries=entries, exits=exits, logs=logs)

@app.route('/admin/staff/add', methods=['POST'])
def add_staff():
    if not need_admin(): return redirect('/')
    name = request.form.get('name','').strip(); username=request.form.get('username','').strip(); password=request.form.get('password','1234')
    salary = float(request.form.get('salary') or 0)
    if name and username:
        con=db(); con.execute('INSERT OR IGNORE INTO staff(name,username,password_hash,salary,qr_token) VALUES(?,?,?,?,?)', (name,username,generate_password_hash(password),salary,secrets.token_urlsafe(32))); con.commit(); con.close()
    return redirect('/dashboard')

@app.route('/admin/staff/delete/<int:sid>')
def del_staff(sid):
    if not need_admin(): return redirect('/')
    con=db(); con.execute('DELETE FROM staff WHERE id=?',(sid,)); con.commit(); con.close(); return redirect('/dashboard')

@app.route('/admin/qr/<int:sid>')
def admin_qr(sid):
    if not need_admin(): return redirect('/')
    con=db(); s=con.execute('SELECT * FROM staff WHERE id=?',(sid,)).fetchone(); con.close()
    if not s: return 'Personel yok',404
    data = make_qr_data(s['id'], s['qr_token']); img=qr_svg_base64(data)
    return f'''<body style="margin:0;background:#07111f;color:white;font-family:Arial;display:grid;place-items:center;min-height:100vh"><div style="padding:30px;border-radius:26px;background:rgba(255,255,255,.08);text-align:center"><h1>{s['name']}</h1><p>Kişiye özel güvenli barkod</p><img style="background:white;padding:14px;border-radius:20px;width:280px" src="data:image/svg+xml;base64,{img}"><br><br><a style="color:white" href="/dashboard">Panele dön</a></div></body>'''

@app.route('/api/login', methods=['POST'])
def api_login():
    data=request.get_json(force=True,silent=True) or request.form
    username=data.get('username'); password=data.get('password')
    con=db(); s=con.execute('SELECT * FROM staff WHERE username=? AND active=1',(username,)).fetchone(); con.close()
    if s and check_password_hash(s['password_hash'], password):
        return jsonify(ok=True, staff=staff_to_dict(s), token=s['qr_token'])
    return jsonify(ok=False, error='Kullanıcı adı veya şifre hatalı'),401

@app.route('/api/staff')
def api_staff():
    con=db(); rows=con.execute('SELECT * FROM staff WHERE active=1 ORDER BY name').fetchall(); con.close()
    return jsonify(ok=True, staff=[staff_to_dict(r) for r in rows])

@app.route('/api/my-qr')
def api_my_qr():
    staff_id=request.args.get('staff_id'); token=request.args.get('token')
    con=db(); s=con.execute('SELECT * FROM staff WHERE id=? AND qr_token=?',(staff_id,token)).fetchone(); con.close()
    if not s: return jsonify(ok=False,error='QR yetkisi reddedildi'),403
    data=make_qr_data(s['id'],s['qr_token'])
    return jsonify(ok=True, qr_data=data, qr_image='data:image/svg+xml;base64,'+qr_svg_base64(data))

@app.route('/api/qr/verify', methods=['POST'])
def api_qr_verify():
    data=request.get_json(force=True,silent=True) or request.form
    qr_data=data.get('qr_data',''); logged_id=str(data.get('staff_id',''))
    action=data.get('action','entry')
    try:
        prefix, sid, token = qr_data.split(':',2)
    except ValueError:
        return jsonify(ok=False,error='Geçersiz QR'),400
    if prefix!='PERSONELQR' or sid != logged_id:
        return jsonify(ok=False,error='Bu barkod bu kullanıcıya ait değil'),403
    con=db(); s=con.execute('SELECT * FROM staff WHERE id=? AND qr_token=? AND active=1',(sid,token)).fetchone()
    if not s:
        con.close(); return jsonify(ok=False,error='QR doğrulanamadı'),403
    typ='exit' if action=='exit' else 'entry'
    now=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    con.execute('INSERT INTO attendance(staff_id,type,created_at) VALUES(?,?,?)',(sid,typ,now)); con.commit(); con.close()
    return jsonify(ok=True,message='İşlem kaydedildi',type=typ,time=now,staff=staff_to_dict(s))

@app.route('/api/entry', methods=['POST'])
def api_entry():
    data=request.get_json(force=True,silent=True) or request.form; sid=data.get('staff_id') or data.get('id')
    con=db(); s=con.execute('SELECT * FROM staff WHERE id=? AND active=1',(sid,)).fetchone()
    if not s: con.close(); return jsonify(ok=False,error='Personel bulunamadı'),404
    now=datetime.now().strftime('%Y-%m-%d %H:%M:%S'); con.execute('INSERT INTO attendance(staff_id,type,created_at) VALUES(?,?,?)',(sid,'entry',now)); con.commit(); con.close()
    return jsonify(ok=True,message='Giriş yapıldı',time=now)

@app.route('/api/exit', methods=['POST'])
def api_exit():
    data=request.get_json(force=True,silent=True) or request.form; sid=data.get('staff_id') or data.get('id')
    con=db(); s=con.execute('SELECT * FROM staff WHERE id=? AND active=1',(sid,)).fetchone()
    if not s: con.close(); return jsonify(ok=False,error='Personel bulunamadı'),404
    now=datetime.now().strftime('%Y-%m-%d %H:%M:%S'); con.execute('INSERT INTO attendance(staff_id,type,created_at) VALUES(?,?,?)',(sid,'exit',now)); con.commit(); con.close()
    return jsonify(ok=True,message='Çıkış yapıldı',time=now)

@app.route('/api/leaves', methods=['GET','POST'])
def api_leaves():
    con=db()
    if request.method=='POST':
        data=request.get_json(force=True,silent=True) or request.form; sid=data.get('staff_id'); days=int(data.get('days') or 1)
        con.execute('INSERT INTO leave_requests(staff_id,start_date,end_date,days,created_at) VALUES(?,?,?,?,?)',(sid,data.get('start_date'),data.get('end_date'),days,datetime.now().strftime('%Y-%m-%d %H:%M:%S'))); con.commit(); con.close()
        return jsonify(ok=True,message='İzin talebi alındı')
    rows=con.execute('SELECT leave_requests.*, staff.name FROM leave_requests JOIN staff ON staff.id=leave_requests.staff_id ORDER BY id DESC').fetchall(); con.close()
    return jsonify(ok=True, leaves=[dict(r) for r in rows])

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT',5000)))
