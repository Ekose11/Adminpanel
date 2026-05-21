import os, json, csv, io, calendar, secrets
from datetime import datetime, timedelta
from functools import wraps
from urllib.parse import quote
from xml.sax.saxutils import escape
import pytz
from flask import Flask, render_template, request, redirect, session, flash, jsonify, Response, send_file
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'premium-personel-secret')
TZ = pytz.timezone('Europe/Istanbul')
DATA_FILE = 'data.json'
UPLOAD_DIR = os.path.join('static','uploads')
os.makedirs(UPLOAD_DIR, exist_ok=True)

SHIFT_DEFS = {
    'Sabah': {'start':'08:00','end':'16:00'},
    'Akşam': {'start':'16:00','end':'00:00'},
    'Gece': {'start':'00:00','end':'08:00'},
    'İzinli': {'start':'','end':''},
    'OFF': {'start':'','end':''},
}

def now_dt(): return datetime.now(TZ)
def today_str(): return now_dt().strftime('%Y-%m-%d')
def now_time(): return now_dt().strftime('%H:%M:%S')
def month_now(): return now_dt().strftime('%Y-%m')

def default_data():
    return {
        'admin': {'username':'eren','password':'1234'},
        'station_token': secrets.token_urlsafe(14),
        'personnel': [
            {'id':1,'name':'Ahmet Yılmaz','username':'ahmet','password':'1234','phone':'0555 111 22 33','address':'Merkez','photo':'','salary':30000.0,'advance':0.0,'annual_leave_total':14,'annual_leave_used':0},
            {'id':2,'name':'Mehmet Kaya','username':'mehmet','password':'1234','phone':'0555 444 55 66','address':'Servis','photo':'','salary':30000.0,'advance':0.0,'annual_leave_total':14,'annual_leave_used':0},
        ],
        'attendance': [],
        'shifts': {},
        'notifications': []
    }

def load_data():
    if not os.path.exists(DATA_FILE):
        d = default_data(); save_data(d); return d
    with open(DATA_FILE,'r',encoding='utf-8') as f:
        return json.load(f)

def save_data(d):
    with open(DATA_FILE,'w',encoding='utf-8') as f:
        json.dump(d,f,ensure_ascii=False,indent=2)

def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not session.get('admin'): return redirect('/login')
        return fn(*a, **kw)
    return wrapper

def find_person(d, pid):
    return next((p for p in d['personnel'] if int(p['id']) == int(pid)), None)

def next_id(items):
    return max([int(x.get('id',0)) for x in items] or [0]) + 1

def days_in_month(ym):
    y,m = map(int, ym.split('-'))
    return list(range(1, calendar.monthrange(y,m)[1]+1))

def get_shift(d, pid, date_s):
    ym = date_s[:7]; day = str(int(date_s[-2:]))
    shifts = d.get('shifts',{}).get(ym,{}).get(str(pid),{})
    return shifts.get(day, '')

def attendance_for(d, pid, date_s):
    rows = [r for r in d.get('attendance',[]) if str(r.get('person_id'))==str(pid) and r.get('date')==date_s]
    ins = [r for r in rows if r.get('type')=='in']
    outs = [r for r in rows if r.get('type')=='out']
    return {'in': ins[-1]['time'] if ins else '', 'out': outs[-1]['time'] if outs else '', 'rows': rows}

def status_for(d, pid, date_s):
    att = attendance_for(d,pid,date_s); shift=get_shift(d,pid,date_s)
    if not att['in']: return 'Gelmedi'
    status='Normal'
    if shift in SHIFT_DEFS and SHIFT_DEFS[shift]['start']:
        start = SHIFT_DEFS[shift]['start']
        if att['in'] > start:
            # 10 dk tolerans
            h,m = map(int,start.split(':'))
            tol = (datetime(2000,1,1,h,m)+timedelta(minutes=10)).strftime('%H:%M')
            if att['in'][:5] > tol: status='Geç giriş'
    if att['out'] and shift in SHIFT_DEFS and SHIFT_DEFS[shift]['end']:
        end=SHIFT_DEFS[shift]['end']
        if end!='00:00' and att['out'][:5] < end: status='Erken çıkış'
    return status

def planned_person_days(d, pid, ym):
    out=[]
    for day in days_in_month(ym):
        date_s=f'{ym}-{day:02d}'
        s=get_shift(d,pid,date_s)
        if s and s not in ('OFF','İzinli'):
            out.append(date_s)
    return out

def calc_payroll(d, ym):
    rows=[]
    for p in d['personnel']:
        planned=planned_person_days(d,p['id'],ym)
        present=sum(1 for ds in planned if attendance_for(d,p['id'],ds)['in'])
        scheduled=len(planned); absent=max(0,scheduled-present)
        salary=float(p.get('salary') or 0); advance=float(p.get('advance') or 0)
        daily=salary/scheduled if scheduled else 0
        deduction=daily*absent
        net=salary-advance-deduction
        rows.append({'id':p['id'],'name':p['name'],'scheduled':scheduled,'present':present,'absent':absent,'salary':salary,'advance':advance,'deduction':deduction,'net':net})
    return rows

def make_qr_svg(text, size=260):
    # Basit QR yerine tarayıcı uyumlu SVG barkod benzeri kod: uygulama token metnini okuyamazsa manuel de çalışır.
    # Gerçek QR görüntüsü için Google Charts gerekmez; uygulama /api/station-qr ile token alabilir.
    safe = escape(text)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 260 260">
<rect width="260" height="260" fill="white"/><rect x="16" y="16" width="58" height="58" fill="black"/><rect x="28" y="28" width="34" height="34" fill="white"/><rect x="38" y="38" width="14" height="14" fill="black"/>
<rect x="186" y="16" width="58" height="58" fill="black"/><rect x="198" y="28" width="34" height="34" fill="white"/><rect x="208" y="38" width="14" height="14" fill="black"/>
<rect x="16" y="186" width="58" height="58" fill="black"/><rect x="28" y="198" width="34" height="34" fill="white"/><rect x="38" y="208" width="14" height="14" fill="black"/>
<g fill="black">''' + ''.join([f'<rect x="{86+(i%9)*14}" y="{86+(i//9)*14}" width="10" height="10"/>' for i,ch in enumerate(text.encode('utf-8').hex()[:81]) if int(ch,16)%2==0]) + f'''</g><text x="130" y="252" text-anchor="middle" font-size="9" fill="black">{safe}</text></svg>'''

@app.route('/')
def index(): return redirect('/dashboard' if session.get('admin') else '/login')

@app.route('/login', methods=['GET','POST'])
def login():
    d=load_data(); error=''
    if request.method=='POST':
        if request.form.get('username')==d['admin']['username'] and request.form.get('password')==d['admin']['password']:
            session['admin']=True; return redirect('/dashboard')
        error='Kullanıcı adı veya şifre hatalı'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout(): session.clear(); return redirect('/login')

@app.route('/dashboard')
@login_required
def dashboard():
    d=load_data(); ds=today_str(); rows=[]; present=0
    for p in d['personnel']:
        att=attendance_for(d,p['id'],ds); st=status_for(d,p['id'],ds)
        if att['in']: present+=1
        rows.append({'name':p['name'],'shift':get_shift(d,p['id'],ds) or '-', 'in':att['in'] or '-', 'out':att['out'] or '-', 'status':st})
    return render_template('dashboard.html', personnel=d['personnel'], present=present, absent=len(d['personnel'])-present, rows=rows, now=now_dt().strftime('%d.%m.%Y %H:%M:%S'))

@app.route('/personnel')
@login_required
def personnel(): return render_template('personnel.html', personnel=load_data()['personnel'])

@app.route('/personnel/add', methods=['POST'])
@login_required
def personnel_add():
    d=load_data(); p={'id':next_id(d['personnel']),'name':request.form['name'],'username':request.form['username'],'password':request.form.get('password','1234'),'phone':request.form.get('phone',''),'address':request.form.get('address',''),'photo':'','salary':float(request.form.get('salary') or 0),'advance':0.0,'annual_leave_total':14,'annual_leave_used':0}
    d['personnel'].append(p); save_data(d); flash('Personel eklendi'); return redirect('/personnel')

@app.route('/personnel/<int:pid>/edit', methods=['POST'])
@login_required
def personnel_edit(pid):
    d=load_data(); p=find_person(d,pid)
    if not p: return redirect('/personnel')
    for k in ['name','phone','address']:
        p[k]=request.form.get(k,p.get(k,''))
    p['salary']=float(request.form.get('salary') or p.get('salary') or 0); p['advance']=float(request.form.get('advance') or 0)
    f=request.files.get('photo')
    if f and f.filename:
        fn=f'{pid}_{secure_filename(f.filename)}'; path=os.path.join(UPLOAD_DIR,fn); f.save(path); p['photo']='/'+path.replace('\\','/')
    save_data(d); flash('Personel bilgileri güncellendi'); return redirect('/personnel')

@app.route('/qr-cards')
@login_required
def qr_cards():
    d=load_data(); token=d['station_token']; svg=make_qr_svg('STATION:'+token)
    return render_template('qr.html', qr_svg=svg, token=token, personnel=d['personnel'])

@app.route('/qr-svg')
@login_required
def qr_svg():
    token=load_data()['station_token']; return Response(make_qr_svg('STATION:'+token), mimetype='image/svg+xml')

@app.route('/scan-test', methods=['POST'])
@login_required
def scan_test():
    pid=int(request.form['person_id']); token=request.form.get('station_token','')
    res=record_scan(pid, token)
    flash(res['message']); return redirect('/qr-cards')

def record_scan(pid, token):
    d=load_data()
    if token != d.get('station_token'): return {'ok':False,'message':'QR kod eksik veya bozuk'}
    p=find_person(d,pid)
    if not p: return {'ok':False,'message':'Personel bulunamadı'}
    now=now_dt(); recent=[r for r in d['attendance'] if str(r.get('person_id'))==str(pid)]
    if recent:
        last=recent[-1]
        try:
            last_dt=datetime.fromisoformat(last['ts'])
            if last_dt.tzinfo is None: last_dt=TZ.localize(last_dt)
            if (now-last_dt).total_seconds()<10:
                return {'ok':False,'message':'Çift okutma engellendi: 10 saniye bekleyin'}
        except Exception: pass
    ds=now.strftime('%Y-%m-%d')
    day_rows=[r for r in d['attendance'] if str(r.get('person_id'))==str(pid) and r.get('date')==ds]
    typ='out' if day_rows and day_rows[-1].get('type')=='in' else 'in'
    rec={'id':next_id(d['attendance']),'person_id':pid,'name':p['name'],'type':typ,'date':ds,'time':now.strftime('%H:%M:%S'),'ts':now.isoformat(),'shift':get_shift(d,pid,ds)}
    d['attendance'].append(rec); save_data(d)
    return {'ok':True,'type':typ,'message':f"{p['name']} {'giriş' if typ=='in' else 'çıkış'} kaydedildi"}

@app.route('/shifts', methods=['GET','POST'])
@login_required
def shifts():
    d=load_data(); ym=request.values.get('month') or month_now()
    if request.method=='POST':
        d.setdefault('shifts',{}).setdefault(ym,{})
        for p in d['personnel']:
            d['shifts'][ym].setdefault(str(p['id']),{})
            for day in days_in_month(ym):
                val=request.form.get(f's_{p["id"]}_{day}','')
                if val: d['shifts'][ym][str(p['id'])][str(day)] = val
                else: d['shifts'][ym][str(p['id'])].pop(str(day), None)
        save_data(d); flash('Aylık vardiya listesi kaydedildi'); return redirect('/shifts?month='+ym)
    return render_template('shifts.html', personnel=d['personnel'], days=days_in_month(ym), month=ym, shifts=d.get('shifts',{}).get(ym,{}), shift_defs=SHIFT_DEFS)

@app.route('/attendance')
@login_required
def attendance():
    d=load_data(); ds=request.args.get('date') or today_str(); present_rows=[]; absent_rows=[]
    for p in d['personnel']:
        att=attendance_for(d,p['id'],ds); sh=get_shift(d,p['id'],ds)
        if att['in']: present_rows.append({'name':p['name'],'in':att['in'],'out':att['out'] or '-','status':status_for(d,p['id'],ds)})
        else: absent_rows.append({'name':p['name'],'shift':sh or '-'})
    return render_template('attendance.html', date=ds, present_rows=present_rows, absent_rows=absent_rows)

@app.route('/payroll')
@login_required
def payroll():
    d=load_data(); ym=request.args.get('month') or month_now(); return render_template('payroll.html', month=ym, rows=calc_payroll(d,ym))

@app.route('/api/server-time')
def api_time(): return jsonify({'time': now_dt().strftime('%d.%m.%Y %H:%M:%S'), 'iso': now_dt().isoformat()})

@app.route('/api/personnel')
def api_personnel():
    d=load_data(); return jsonify(d['personnel'])

@app.route('/api/station-qr')
def api_station_qr():
    d=load_data(); return jsonify({'token':d['station_token'], 'value':'STATION:'+d['station_token']})

@app.route('/api/login', methods=['POST'])
def api_login():
    d=load_data(); data=request.get_json(silent=True) or request.form
    u=data.get('username'); pw=data.get('password')
    p=next((x for x in d['personnel'] if x.get('username')==u and x.get('password')==pw), None)
    if not p: return jsonify({'ok':False,'message':'Hatalı giriş'}),401
    return jsonify({'ok':True,'person':p,'station_token':d['station_token']})

@app.route('/api/profile/update', methods=['POST'])
def api_profile_update():
    d=load_data(); pid=request.form.get('person_id') or (request.json or {}).get('person_id')
    p=find_person(d,pid)
    if not p: return jsonify({'ok':False,'message':'Personel bulunamadı'}),404
    for k in ['phone','address']:
        val=request.form.get(k) if request.form else (request.json or {}).get(k)
        if val is not None: p[k]=val
    f=request.files.get('photo')
    if f and f.filename:
        fn=f'{pid}_{secure_filename(f.filename)}'; path=os.path.join(UPLOAD_DIR,fn); f.save(path); p['photo']='/'+path.replace('\\','/')
    save_data(d); return jsonify({'ok':True,'person':p})

@app.route('/api/qr/verify', methods=['POST'])
def api_qr_verify():
    data=request.get_json(silent=True) or request.form
    token=data.get('station_token') or data.get('token') or data.get('qr') or ''
    if token.startswith('STATION:'): token=token.split(':',1)[1]
    pid=data.get('person_id')
    if not pid and data.get('username'):
        d=load_data(); p=next((x for x in d['personnel'] if x.get('username')==data.get('username')), None); pid=p['id'] if p else None
    res=record_scan(pid, token) if pid else {'ok':False,'message':'Personel bilgisi eksik'}
    return jsonify(res), (200 if res['ok'] else 400)

@app.route('/attendance/csv')
@login_required
def attendance_csv():
    d=load_data(); ds=request.args.get('date') or today_str(); out=io.StringIO(); out.write('\ufeff')
    w=csv.writer(out, delimiter=';'); w.writerow(['Tarih','Personel','Vardiya','Giriş','Çıkış','Durum'])
    for p in d['personnel']:
        att=attendance_for(d,p['id'],ds); w.writerow([ds,p['name'],get_shift(d,p['id'],ds) or '',att['in'],att['out'],status_for(d,p['id'],ds)])
    return Response(out.getvalue(), mimetype='text/csv; charset=utf-8', headers={'Content-Disposition':f'attachment; filename=giris_cikis_{ds}.csv'})

@app.route('/payroll/csv')
@login_required
def payroll_csv():
    ym=request.args.get('month') or month_now(); out=io.StringIO(); out.write('\ufeff'); w=csv.writer(out, delimiter=';')
    w.writerow(['Ay','Personel','Planlı Gün','Geldiği Gün','Gelmediği Gün','Brüt Maaş','Avans','Kesinti','Net'])
    for r in calc_payroll(load_data(),ym): w.writerow([ym,r['name'],r['scheduled'],r['present'],r['absent'],f"{r['salary']:.2f}",f"{r['advance']:.2f}",f"{r['deduction']:.2f}",f"{r['net']:.2f}"])
    return Response(out.getvalue(), mimetype='text/csv; charset=utf-8', headers={'Content-Disposition':f'attachment; filename=puantaj_{ym}.csv'})

@app.route('/shifts/pdf')
@login_required
def shifts_pdf():
    return make_pdf('shift', request.args.get('month') or month_now())

@app.route('/payslip/<int:pid>')
@login_required
def payslip(pid):
    return make_pdf('payslip', request.args.get('month') or month_now(), pid)

def make_pdf(kind, ym, pid=None):
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    font='Helvetica'
    for fp in ['/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf','/usr/share/fonts/dejavu/DejaVuSans.ttf']:
        if os.path.exists(fp):
            pdfmetrics.registerFont(TTFont('DejaVuSans', fp)); font='DejaVuSans'; break
    buf=io.BytesIO(); c=canvas.Canvas(buf, pagesize=landscape(A4) if kind=='shift' else A4); c.setFont(font, 12)
    d=load_data(); W,H=(landscape(A4) if kind=='shift' else A4)
    c.setFont(font,18); c.drawString(40,H-45,'Personel Sistemi')
    c.setFont(font,12); c.drawString(40,H-68, f'Ay: {ym}')
    y=H-100
    if kind=='shift':
        c.setFont(font,10); c.drawString(40,y,'Aylık Vardiya Listesi'); y-=22
        for p in d['personnel']:
            c.setFont(font,10); c.drawString(40,y,p['name']); x=160
            for day in days_in_month(ym):
                c.drawString(x,y, get_shift(d,p['id'],f'{ym}-{day:02d}')[:1] or '-') ; x+=18
            y-=20
            if y<40: c.showPage(); c.setFont(font,10); y=H-40
        filename=f'vardiya_{ym}.pdf'
    else:
        rows=calc_payroll(d,ym); r=next((x for x in rows if int(x['id'])==int(pid)), None); p=find_person(d,pid)
        c.setFont(font,16); c.drawString(40,y,'Bordro'); y-=34; c.setFont(font,12)
        for label,val in [('Personel',p['name']),('Planlı Gün',r['scheduled']),('Geldiği Gün',r['present']),('Gelmediği Gün',r['absent']),('Brüt Maaş',f"{r['salary']:.2f}"),('Avans',f"{r['advance']:.2f}"),('Kesinti',f"{r['deduction']:.2f}"),('Net Maaş',f"{r['net']:.2f}")]:
            c.drawString(50,y,f'{label}: {val}'); y-=24
        filename=f'bordro_{p["name"].replace(" ","_")}_{ym}.pdf'
    c.save(); buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=filename, mimetype='application/pdf')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
