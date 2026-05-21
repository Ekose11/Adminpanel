from flask import Flask, render_template, request, redirect, session, jsonify, Response, send_file, url_for
from datetime import datetime, date, timedelta
import os, json, io, csv, calendar
import pytz
import qrcode
import qrcode.image.svg
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'premium-personel-secret')
TZ = pytz.timezone('Europe/Istanbul')
DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
DB_PATH = os.path.join(DATA_DIR, 'db.json')
MASTER_QR_CODE = 'PERSONEL-SISTEMI-TEK-QR-2026'
ADMIN_USER = 'eren'
ADMIN_PASS = '1234'

os.makedirs(DATA_DIR, exist_ok=True)

def now_tr():
    return datetime.now(TZ)

def today_str():
    return now_tr().strftime('%Y-%m-%d')

def month_str():
    return now_tr().strftime('%Y-%m')

def default_db():
    return {
        'personnel': [
            {'id':'1','name':'Ahmet Yılmaz','username':'ahmet','password':'1234','phone':'0555 111 22 33','address':'Merkez','salary':30000,'active':True,'photo':''},
            {'id':'2','name':'Mehmet Çelik','username':'mehmet','password':'1234','phone':'0555 444 55 66','address':'Servis','salary':30000,'active':True,'photo':''},
            {'id':'3','name':'Ayşe Şahin','username':'ayse','password':'1234','phone':'0555 777 88 99','address':'Atölye','salary':30000,'active':True,'photo':''},
        ],
        'attendance': [],
        'shifts': {},
        'notifications': []
    }

def load_db():
    if not os.path.exists(DB_PATH):
        save_db(default_db())
    try:
        with open(DB_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        db = default_db(); save_db(db); return db

def save_db(db):
    with open(DB_PATH, 'w', encoding='utf-8') as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

def require_login():
    return session.get('admin') == True

def person_by_id(db, pid):
    return next((p for p in db['personnel'] if str(p['id']) == str(pid)), None)

def month_days(ym):
    y, m = map(int, ym.split('-'))
    return [date(y, m, d).strftime('%Y-%m-%d') for d in range(1, calendar.monthrange(y,m)[1]+1)]

def get_shift(db, pid, day):
    return db.get('shifts', {}).get(day, {}).get(str(pid), 'Sabah')

def shift_hours(name):
    return {'Sabah':('08:00','16:00'), 'Akşam':('16:00','00:00'), 'Gece':('00:00','08:00'), 'İzin':('',''), 'Kapalı':('','')}.get(name, ('08:00','16:00'))

def status_for_record(rec, shift_name):
    if rec.get('type') == 'in':
        start, _ = shift_hours(shift_name)
        if start and rec.get('time','') > start:
            return 'Geç giriş'
        return 'Normal giriş'
    if rec.get('type') == 'out':
        _, end = shift_hours(shift_name)
        if end and end != '00:00' and rec.get('time','') < end:
            return 'Erken çıkış'
        return 'Normal çıkış'
    return '-'

def register_pdf_font():
    for p in ['/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf','/usr/share/fonts/dejavu/DejaVuSans.ttf']:
        if os.path.exists(p):
            try:
                pdfmetrics.registerFont(TTFont('TRFont', p)); return 'TRFont'
            except Exception:
                pass
    return 'Helvetica'

@app.route('/')
def root():
    return redirect('/dashboard' if require_login() else '/login')

@app.route('/login', methods=['GET','POST'])
def login():
    error=''
    if request.method == 'POST':
        if request.form.get('username') == ADMIN_USER and request.form.get('password') == ADMIN_PASS:
            session['admin'] = True
            return redirect('/dashboard')
        error='Kullanıcı adı veya şifre hatalı'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    session.clear(); return redirect('/login')

@app.route('/dashboard')
def dashboard():
    if not require_login(): return redirect('/login')
    db=load_db(); today=today_str()
    ins={r['person_id'] for r in db['attendance'] if r['date']==today and r['type']=='in'}
    outs={r['person_id'] for r in db['attendance'] if r['date']==today and r['type']=='out'}
    active_count=len(ins-outs)
    return render_template('dashboard.html', db=db, active_count=active_count, today=today, now=now_tr().strftime('%d.%m.%Y %H:%M:%S'))

@app.route('/admin/qr')
def admin_qr():
    if not require_login(): return redirect('/login')
    img = qrcode.make(MASTER_QR_CODE, image_factory=qrcode.image.svg.SvgPathImage)
    buf=io.BytesIO(); img.save(buf); svg=buf.getvalue().decode('utf-8')
    return render_template('qr.html', qr_svg=svg, code=MASTER_QR_CODE)

@app.route('/admin/shifts', methods=['GET','POST'])
def shifts():
    if not require_login(): return redirect('/login')
    db=load_db(); ym=request.values.get('month', month_str())
    days=month_days(ym)
    if request.method=='POST':
        for day in days:
            db.setdefault('shifts', {}).setdefault(day, {})
            for p in db['personnel']:
                db['shifts'][day][str(p['id'])] = request.form.get(f'shift_{day}_{p["id"]}', 'Sabah')
        save_db(db); return redirect('/admin/shifts?month='+ym)
    return render_template('shifts.html', db=db, ym=ym, days=days, get_shift=get_shift)

@app.route('/admin/attendance')
def attendance():
    if not require_login(): return redirect('/login')
    db=load_db(); day=request.args.get('date', today_str())
    records=[r for r in db['attendance'] if r['date']==day]
    present={r['person_id'] for r in records if r['type']=='in'}
    absent=[p for p in db['personnel'] if str(p['id']) not in present and p.get('active', True)]
    return render_template('attendance.html', db=db, day=day, records=records, absent=absent, person_by_id=person_by_id, get_shift=get_shift, status_for_record=status_for_record)

@app.route('/admin/attendance.csv')
def attendance_csv():
    if not require_login(): return redirect('/login')
    db=load_db(); day=request.args.get('date', today_str())
    out=io.StringIO(); out.write('\ufeff')
    w=csv.writer(out, delimiter=';')
    w.writerow(['Tarih','Personel','İşlem','Saat','Vardiya','Durum'])
    for r in db['attendance']:
        if r['date']==day:
            p=person_by_id(db,r['person_id']); sh=get_shift(db,r['person_id'],day)
            w.writerow([day, p['name'] if p else r['person_id'], 'Giriş' if r['type']=='in' else 'Çıkış', r['time'], sh, status_for_record(r, sh)])
    return Response(out.getvalue(), mimetype='text/csv; charset=utf-8-sig', headers={'Content-Disposition':f'attachment; filename=puantaj_{day}.csv'})

@app.route('/admin/puantaj')
def puantaj():
    if not require_login(): return redirect('/login')
    db=load_db(); ym=request.args.get('month', month_str()); days=month_days(ym)
    rows=[]
    for p in db['personnel']:
        work_days=[d for d in days if get_shift(db,p['id'],d) not in ['İzin','Kapalı']]
        present_days={r['date'] for r in db['attendance'] if r['person_id']==str(p['id']) and r['type']=='in' and r['date'].startswith(ym)}
        absent=[d for d in work_days if d not in present_days]
        late=0; early=0
        for r in db['attendance']:
            if r['person_id']==str(p['id']) and r['date'].startswith(ym):
                st=status_for_record(r, get_shift(db,p['id'],r['date']))
                if st=='Geç giriş': late+=1
                if st=='Erken çıkış': early+=1
        salary=float(p.get('salary',0)); daily=salary/max(len(work_days),1); cut=round(daily*len(absent),2)
        rows.append({'p':p,'work':len(work_days),'present':len(present_days),'absent':len(absent),'late':late,'early':early,'cut':cut,'net':round(salary-cut,2)})
    return render_template('puantaj.html', rows=rows, ym=ym)

@app.route('/admin/payroll/<pid>')
def payroll(pid):
    if not require_login(): return redirect('/login')
    db=load_db(); ym=request.args.get('month', month_str()); p=person_by_id(db,pid)
    if not p: return 'Personel bulunamadı',404
    days=month_days(ym); work_days=[d for d in days if get_shift(db,pid,d) not in ['İzin','Kapalı']]
    present={r['date'] for r in db['attendance'] if r['person_id']==str(pid) and r['type']=='in' and r['date'].startswith(ym)}
    absent=[d for d in work_days if d not in present]
    salary=float(p.get('salary',0)); cut=round((salary/max(len(work_days),1))*len(absent),2); net=round(salary-cut,2)
    font=register_pdf_font(); buf=io.BytesIO(); doc=SimpleDocTemplate(buf, pagesize=A4)
    styles=getSampleStyleSheet(); styles['Normal'].fontName=font; styles['Title'].fontName=font
    story=[Paragraph('Personel Bordro', styles['Title']), Spacer(1,12), Paragraph(f"Personel: {p['name']}", styles['Normal']), Paragraph(f"Ay: {ym}", styles['Normal']), Spacer(1,12)]
    data=[['Brüt Maaş','Çalışma Günü','Geldiği Gün','Gelmediği Gün','Kesinti','Net Maaş'],[f'{salary:.2f} TL',len(work_days),len(present),len(absent),f'{cut:.2f} TL',f'{net:.2f} TL']]
    t=Table(data); t.setStyle(TableStyle([('FONTNAME',(0,0),(-1,-1),font),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#0f2747')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('GRID',(0,0),(-1,-1),0.4,colors.grey),('PADDING',(0,0),(-1,-1),8)])); story.append(t)
    if absent:
        story += [Spacer(1,12), Paragraph('Gelmediği Günler: '+', '.join(absent), styles['Normal'])]
    doc.build(story); buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=f"bordro_{p['name'].replace(' ','_')}_{ym}.pdf", mimetype='application/pdf')

@app.route('/admin/shifts.pdf')
def shifts_pdf():
    if not require_login(): return redirect('/login')
    db=load_db(); ym=request.args.get('month', month_str()); days=month_days(ym); font=register_pdf_font()
    buf=io.BytesIO(); doc=SimpleDocTemplate(buf, pagesize=A4, leftMargin=18, rightMargin=18)
    styles=getSampleStyleSheet(); styles['Title'].fontName=font
    story=[Paragraph(f'Aylık Vardiya Listesi - {ym}', styles['Title']), Spacer(1,10)]
    data=[['Tarih']+[p['name'] for p in db['personnel']]]
    for d in days: data.append([d]+[get_shift(db,p['id'],d) for p in db['personnel']])
    t=Table(data, repeatRows=1); t.setStyle(TableStyle([('FONTNAME',(0,0),(-1,-1),font),('FONTSIZE',(0,0),(-1,-1),7),('BACKGROUND',(0,0),(-1,0),colors.HexColor('#0f2747')),('TEXTCOLOR',(0,0),(-1,0),colors.white),('GRID',(0,0),(-1,-1),0.25,colors.grey)])); story.append(t)
    doc.build(story); buf.seek(0)
    return send_file(buf, as_attachment=True, download_name=f'vardiya_listesi_{ym}.pdf', mimetype='application/pdf')

@app.route('/api/server-time')
def api_time(): return jsonify({'time': now_tr().strftime('%d.%m.%Y %H:%M:%S')})

@app.route('/api/personnel')
def api_personnel():
    db=load_db(); return jsonify(db['personnel'])

@app.route('/api/qr/verify', methods=['POST'])
def api_qr_verify():
    db=load_db(); data=request.get_json(silent=True) or request.form
    code=data.get('code') or data.get('qr') or data.get('qr_code')
    pid=str(data.get('person_id') or data.get('user_id') or '')
    username=data.get('username') or ''
    if code != MASTER_QR_CODE:
        return jsonify({'ok':False,'message':'QR kod eksik veya bozuk'}),400
    if not pid and username:
        p=next((x for x in db['personnel'] if x.get('username')==username), None); pid=str(p['id']) if p else ''
    p=person_by_id(db,pid)
    if not p: return jsonify({'ok':False,'message':'Personel bulunamadı'}),404
    n=now_tr(); day=n.strftime('%Y-%m-%d'); tm=n.strftime('%H:%M:%S')
    last=[r for r in db['attendance'] if r['person_id']==pid]
    if last:
        lr=last[-1]
        try:
            last_dt=TZ.localize(datetime.strptime(lr['date']+' '+lr['time'], '%Y-%m-%d %H:%M:%S'))
            if (n-last_dt).total_seconds()<10:
                return jsonify({'ok':False,'message':'Çift okutma engellendi'}),429
        except Exception: pass
    today_recs=[r for r in db['attendance'] if r['person_id']==pid and r['date']==day]
    typ='out' if today_recs and today_recs[-1]['type']=='in' else 'in'
    rec={'person_id':pid,'date':day,'time':tm,'type':typ,'shift':get_shift(db,pid,day)}
    rec['status']=status_for_record(rec, rec['shift'])
    db['attendance'].append(rec); save_db(db)
    return jsonify({'ok':True,'message':f"{p['name']} {'giriş' if typ=='in' else 'çıkış'} kaydı alındı", 'record':rec})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
