from flask import Flask, render_template, request, redirect, url_for, session, jsonify, send_file
from datetime import datetime, date
import sqlite3, os, calendar
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer

app = Flask(__name__)
app.secret_key = "boztek-secret-key"
DB = "boztek.db"
WORK_START = "09:00"
WORK_END = "18:00"

def db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db(); c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS personnel (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        salary REAL DEFAULT 0,
        annual_leave_total INTEGER DEFAULT 14,
        active INTEGER DEFAULT 1
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        person_id INTEGER,
        action TEXT,
        ts TEXT,
        day TEXT,
        month TEXT,
        FOREIGN KEY(person_id) REFERENCES personnel(id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS leaves (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        person_id INTEGER,
        start_day TEXT,
        end_day TEXT,
        note TEXT,
        created_at TEXT,
        FOREIGN KEY(person_id) REFERENCES personnel(id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS advances (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        person_id INTEGER,
        amount REAL,
        note TEXT,
        created_at TEXT,
        month TEXT,
        FOREIGN KEY(person_id) REFERENCES personnel(id)
    )""")
    if c.execute("SELECT COUNT(*) FROM personnel").fetchone()[0] == 0:
        c.executemany("INSERT INTO personnel(name,salary) VALUES (?,?)", [("Ahmet Yılmaz",25000),("Mehmet Kaya",25000),("Ayşe Demir",25000)])
    conn.commit(); conn.close()

def login_required(fn):
    def wrapper(*a, **kw):
        if not session.get('login'):
            return redirect(url_for('login'))
        return fn(*a, **kw)
    wrapper.__name__ = fn.__name__
    return wrapper

def current_month(): return datetime.now().strftime('%Y-%m')
def now_str(): return datetime.now().strftime('%Y-%m-%d %H:%M:%S')
def today_str(): return date.today().isoformat()

def get_summary(month=None):
    month = month or current_month()
    conn = db()
    people = conn.execute("SELECT * FROM personnel WHERE active=1 ORDER BY name").fetchall()
    result=[]
    for p in people:
        days = conn.execute("SELECT COUNT(DISTINCT day) c FROM attendance WHERE person_id=? AND action='giris' AND month=?", (p['id'],month)).fetchone()['c']
        late = conn.execute("SELECT COUNT(*) c FROM attendance WHERE person_id=? AND action='giris' AND month=? AND substr(ts,12,5)>?", (p['id'],month,WORK_START)).fetchone()['c']
        early = conn.execute("SELECT COUNT(*) c FROM attendance WHERE person_id=? AND action='cikis' AND month=? AND substr(ts,12,5)<?", (p['id'],month,WORK_END)).fetchone()['c']
        adv = conn.execute("SELECT COALESCE(SUM(amount),0) s FROM advances WHERE person_id=? AND month=?", (p['id'],month)).fetchone()['s']
        last = conn.execute("SELECT action,ts FROM attendance WHERE person_id=? ORDER BY ts DESC LIMIT 1", (p['id'],)).fetchone()
        result.append(dict(p, came_days=days, late=late, early=early, advance_total=adv, net_salary=(p['salary'] or 0)-adv, last_action=last['action'] if last else '-', last_ts=last['ts'] if last else '-'))
    conn.close(); return result

@app.route('/login', methods=['GET','POST'])
def login():
    if request.method=='POST':
        if request.form.get('username')=='admin' and request.form.get('password')=='1234':
            session['login']=True; return redirect(url_for('dashboard'))
        return render_template('login.html', error='Hatalı kullanıcı adı veya şifre')
    return render_template('login.html')

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))

@app.route('/')
@login_required
def dashboard():
    month=request.args.get('month', current_month())
    return render_template('dashboard.html', people=get_summary(month), month=month)

@app.route('/personnel', methods=['GET','POST'])
@login_required
def personnel():
    conn=db()
    if request.method=='POST':
        conn.execute("INSERT INTO personnel(name,salary,annual_leave_total) VALUES (?,?,?)", (request.form['name'], request.form.get('salary',0), request.form.get('leave',14)))
        conn.commit(); conn.close(); return redirect(url_for('personnel'))
    people=conn.execute("SELECT * FROM personnel WHERE active=1 ORDER BY name").fetchall(); conn.close()
    return render_template('personnel.html', people=people)

@app.route('/personnel/delete/<int:id>')
@login_required
def delete_person(id):
    conn=db(); conn.execute("UPDATE personnel SET active=0 WHERE id=?", (id,)); conn.commit(); conn.close(); return redirect(url_for('personnel'))

@app.route('/leaves', methods=['GET','POST'])
@login_required
def leaves():
    conn=db()
    if request.method=='POST':
        conn.execute("INSERT INTO leaves(person_id,start_day,end_day,note,created_at) VALUES (?,?,?,?,?)", (request.form['person_id'], request.form['start_day'], request.form['end_day'], request.form.get('note',''), now_str()))
        conn.commit(); return redirect(url_for('leaves'))
    people=conn.execute("SELECT * FROM personnel WHERE active=1 ORDER BY name").fetchall()
    rows=conn.execute("SELECT l.*,p.name FROM leaves l JOIN personnel p ON p.id=l.person_id ORDER BY l.start_day DESC").fetchall(); conn.close()
    return render_template('leaves.html', people=people, rows=rows)

@app.route('/advances', methods=['GET','POST'])
@login_required
def advances():
    conn=db()
    if request.method=='POST':
        m=request.form.get('month') or current_month()
        conn.execute("INSERT INTO advances(person_id,amount,note,created_at,month) VALUES (?,?,?,?,?)", (request.form['person_id'], request.form['amount'], request.form.get('note',''), now_str(), m))
        conn.commit(); return redirect(url_for('advances'))
    people=conn.execute("SELECT * FROM personnel WHERE active=1 ORDER BY name").fetchall()
    rows=conn.execute("SELECT a.*,p.name FROM advances a JOIN personnel p ON p.id=a.person_id ORDER BY a.created_at DESC").fetchall(); conn.close()
    return render_template('advances.html', people=people, rows=rows, month=current_month())

@app.route('/reports')
@login_required
def reports():
    month=request.args.get('month', current_month())
    return render_template('reports.html', people=get_summary(month), month=month)

@app.route('/reports/pdf')
@login_required
def report_pdf():
    month=request.args.get('month', current_month())
    rows=get_summary(month)
    buf=BytesIO(); doc=SimpleDocTemplate(buf, pagesize=A4)
    styles=getSampleStyleSheet(); story=[]
    story.append(Paragraph('BOZTEK AYLIK PERSONEL RAPORU', styles['Title']))
    story.append(Paragraph(f'Ay: {month}', styles['Normal'])); story.append(Spacer(1,12))
    data=[['Personel','Geldiği Gün','Geç Giriş','Erken Çıkış','Avans','Net Maaş','Son Durum']]
    for r in rows:
        data.append([r['name'], str(r['came_days']), str(r['late']), str(r['early']), f"{r['advance_total']:.2f}", f"{r['net_salary']:.2f}", r['last_action']])
    table=Table(data, repeatRows=1)
    table.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#0f3b70')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('GRID',(0,0),(-1,-1),0.5,colors.grey),('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('ALIGN',(1,1),(-1,-1),'CENTER')]))
    story.append(table); doc.build(story); buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=f'Boztek_Aylik_Rapor_{month}.pdf', mimetype='application/pdf')

@app.route('/api/personnel')
def api_personnel(): return jsonify(get_summary(current_month()))

@app.route('/api/attendance', methods=['POST'])
def api_attendance():
    data=request.get_json(force=True); pid=data.get('person_id'); action=data.get('action')
    if action not in ['giris','cikis']: return jsonify({'ok':False,'error':'action giris veya cikis olmali'}),400
    conn=db(); ts=now_str(); conn.execute("INSERT INTO attendance(person_id,action,ts,day,month) VALUES (?,?,?,?,?)", (pid,action,ts,today_str(),current_month()))
    conn.commit(); conn.close(); return jsonify({'ok':True,'ts':ts})

if __name__=='__main__':
    init_db(); app.run(host='0.0.0.0', port=5000, debug=True)
