from flask import Flask, render_template, request, redirect, session, flash, jsonify, Response
from datetime import datetime, date
from zoneinfo import ZoneInfo
from urllib.parse import urlparse, unquote
from io import BytesIO
import os, secrets, pg8000
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "premium-personel-secret")
TR_TZ = ZoneInfo("Europe/Istanbul")
DATABASE_URL = os.environ.get("DATABASE_URL")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "eren")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "1234")
READY = False
ENTRY_LIMIT = "09:00:00"
EXIT_LIMIT = "18:00:00"

def parse_db_url():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL yok")
    u=urlparse(DATABASE_URL)
    return {"user":unquote(u.username or ""),"password":unquote(u.password or ""),"host":u.hostname,"port":u.port or 5432,"database":(u.path or "/neondb").lstrip("/")}

def db():
    c=parse_db_url()
    return pg8000.connect(user=c["user"],password=c["password"],host=c["host"],port=c["port"],database=c["database"],ssl_context=True,timeout=20)

def rows_to_dicts(cur, rows):
    if not rows: return []
    cols=[c["name"] if isinstance(c,dict) else c[0] for c in cur.description]
    return [dict(zip(cols,r)) for r in rows]

def q(sql, params=None, fetch=False, one=False):
    conn=db()
    try:
        cur=conn.cursor(); cur.execute(sql, params or ())
        data=None
        if fetch:
            data=rows_to_dicts(cur,cur.fetchall())
            if one: data=data[0] if data else None
        conn.commit(); cur.close(); return data
    finally:
        conn.close()

def init_db():
    global READY
    q("create table if not exists personnel(id serial primary key,full_name text not null,department text not null,annual_leave_total integer default 14,annual_leave_used integer default 0,annual_leave_remaining integer default 14,salary numeric default 0,active integer default 1,username text unique,password text,token text unique,phone text,address text,photo_data text)")
    q("create table if not exists advances(id serial primary key,person_id integer references personnel(id) on delete cascade,amount numeric not null,note text,status text default 'Beklemede')")
    q("create table if not exists leaves(id serial primary key,person_id integer references personnel(id) on delete cascade,start_date text not null,end_date text not null,days_count integer default 0,status text default 'İzinli')")
    q("create table if not exists attendance_logs(id serial primary key,person_id integer references personnel(id) on delete cascade,event_type text not null,event_time text not null)")
    q("create table if not exists leave_requests(id serial primary key,person_id integer references personnel(id) on delete cascade,start_date text not null,end_date text not null,days_count integer default 0,note text,status text default 'Beklemede',created_at text not null)")
    q("create table if not exists notifications(id serial primary key,person_id integer references personnel(id) on delete cascade,event_type text not null,message text not null,created_at text not null,is_read integer default 0)")
    q("create table if not exists payroll_events(id serial primary key,person_id integer references personnel(id) on delete cascade,amount numeric default 0,message text,created_at text not null)")
    for col,typ in [("phone","text"),("address","text"),("photo_data","text")]:
        try: q(f"alter table personnel add column {col} {typ}")
        except Exception: pass
    try: q("alter table advances add column note text")
    except Exception: pass
    try: q("alter table notifications add column person_id integer references personnel(id) on delete cascade")
    except Exception: pass
    READY=True

@app.before_request
def before():
    global READY
    if not READY: init_db()

def admin(): return session.get("admin_ok") is True
def val(n,d=None): return request.form.get(n) or request.args.get(n) or d
def now_str(): return datetime.now(TR_TZ).strftime("%Y-%m-%d %H:%M:%S")
def today_iso(): return datetime.now(TR_TZ).date().isoformat()
def month_key(): return datetime.now(TR_TZ).strftime("%Y-%m")
def notify(event_type, message, person_id=None): q("insert into notifications(person_id,event_type,message,created_at,is_read) values(%s,%s,%s,%s,0)", (person_id,event_type,message,now_str()))
def days_between(a,b):
    s=datetime.strptime(a,"%Y-%m-%d").date(); e=datetime.strptime(b,"%Y-%m-%d").date()
    return max((e-s).days+1,1)
def time_part(ts):
    try: return ts.split(" ")[1]
    except Exception: return ""
def warning_for(event_type,event_time):
    t=time_part(event_time)
    if event_type=="entry" and t>ENTRY_LIMIT: return "Geç giriş"
    if event_type=="exit" and t<EXIT_LIMIT: return "Erken çıkış"
    return ""

def person_summary(pid):
    p=q("select p.*,coalesce(sum(a.amount),0) total_advance from personnel p left join advances a on a.person_id=p.id where p.id=%s group by p.id",(pid,),fetch=True,one=True)
    if not p: return None
    s=float(p["salary"] or 0); a=float(p["total_advance"] or 0)
    return {"id":p["id"],"full_name":p["full_name"],"department":p["department"],"salary":s,"total_advance":a,"remaining_salary":s-a,"annual_leave_total":p["annual_leave_total"],"annual_leave_used":p["annual_leave_used"],"annual_leave_remaining":p["annual_leave_remaining"],"phone":p.get("phone") or "","address":p.get("address") or "","photo_data":p.get("photo_data") or ""}

def today_status_rows():
    today=today_iso()
    people=q("select * from personnel where active=1 order by full_name",fetch=True)
    logs=q("select distinct on (person_id) person_id,event_type,event_time from attendance_logs where substring(event_time,1,10)=%s order by person_id,id desc",(today,),fetch=True)
    log_map={r["person_id"]:r for r in logs}; out=[]
    for p in people:
        log=log_map.get(p["id"])
        if not log: out.append({"id":p["id"],"full_name":p["full_name"],"department":p["department"],"status":"bekleniyor","last_time":"","warning":""})
        else:
            st="işte" if log["event_type"]=="entry" else "çıkış yaptı"
            out.append({"id":p["id"],"full_name":p["full_name"],"department":p["department"],"status":st,"last_time":log["event_time"],"warning":warning_for(log["event_type"],log["event_time"])})
    return out

def report_rows():
    m=month_key()
    return q("select p.id,p.full_name,p.department,p.annual_leave_used,p.annual_leave_remaining,p.salary,coalesce(sum(a.amount),0) total_advance,(select count(distinct substring(event_time,1,10)) from attendance_logs al where al.person_id=p.id and al.event_type='entry' and substring(al.event_time,1,7)=%s) monthly_days,(select count(*) from attendance_logs al where al.person_id=p.id and al.event_type='entry' and substring(al.event_time,1,7)=%s and substring(al.event_time,12,8)>%s) late_entries,(select count(*) from attendance_logs al where al.person_id=p.id and al.event_type='exit' and substring(al.event_time,1,7)=%s and substring(al.event_time,12,8)<%s) early_exits from personnel p left join advances a on a.person_id=p.id group by p.id order by p.full_name",(m,m,ENTRY_LIMIT,m,EXIT_LIMIT),fetch=True)

@app.route("/")
def home(): return redirect("/admin/dashboard") if admin() else redirect("/admin/login")
@app.route("/admin/login",methods=["GET","POST"])
def login():
    if request.method=="POST":
        if request.form.get("username")==ADMIN_USERNAME and request.form.get("password")==ADMIN_PASSWORD:
            session["admin_ok"]=True; return redirect("/admin/dashboard")
        flash("Hatalı kullanıcı adı veya şifre")
    return render_template("login.html")
@app.route("/admin/logout")
def logout(): session.clear(); return redirect("/admin/login")
@app.route("/admin/dashboard")
@app.route("/admin")
def dashboard():
    if not admin(): return redirect("/admin/login")
    ts=today_status_rows()
    stats=q("select (select count(*) from personnel) personel,(select count(*) from advances) avans,(select count(*) from leaves) izin",fetch=True,one=True)
    stats["inside"]=sum(1 for r in ts if r["status"]=="işte"); stats["late"]=sum(1 for r in ts if r["warning"]=="Geç giriş"); stats["early"]=sum(1 for r in ts if r["warning"]=="Erken çıkış")
    return render_template("dashboard.html",title="Dashboard",stats=stats,today_status=ts)

@app.route("/admin/qr-cards")
def qr_cards():
    if not admin(): return redirect("/admin/login")
    rows=q("select * from personnel where active=1 order by full_name",fetch=True)
    return render_template("qr_cards.html", title="QR Kartları", rows=rows)

@app.route("/admin/personnel",methods=["GET","POST"])
def personnel():
    if not admin(): return redirect("/admin/login")
    if request.method=="POST":
        total=int(request.form.get("annual_leave_total",14)); salary=float(request.form.get("salary",0))
        try:
            q("insert into personnel(full_name,department,annual_leave_total,annual_leave_used,annual_leave_remaining,salary,active,username,password,token) values(%s,%s,%s,0,%s,%s,1,%s,%s,%s)",(request.form["full_name"],request.form["department"],total,total,salary,request.form.get("username") or None,request.form.get("password") or None,secrets.token_hex(24)))
            flash("Personel eklendi.")
        except Exception: flash("Personel eklenemedi. Kullanıcı adı aynı olabilir.")
    return render_template("personnel.html",title="Personel",rows=q("select * from personnel order by id desc",fetch=True))
@app.route("/admin/personnel/<int:pid>/edit",methods=["GET","POST"])
def edit_person(pid):
    if not admin(): return redirect("/admin/login")
    p=q("select * from personnel where id=%s",(pid,),fetch=True,one=True)
    if not p: return redirect("/admin/personnel")
    if request.method=="POST":
        total=int(request.form.get("annual_leave_total",0)); used=int(request.form.get("annual_leave_used",0)); rem=max(total-used,0); token=p.get("token") or secrets.token_hex(24)
        q("update personnel set full_name=%s,department=%s,username=%s,password=%s,annual_leave_total=%s,annual_leave_used=%s,annual_leave_remaining=%s,salary=%s,active=%s,token=%s where id=%s",(request.form["full_name"],request.form["department"],request.form.get("username") or None,request.form.get("password") or None,total,used,rem,float(request.form.get("salary",0)),int(request.form.get("active",1)),token,pid))
        flash("Personel güncellendi."); return redirect("/admin/personnel")
    return render_template("edit.html",title="Düzenle",p=p)
@app.route("/admin/personnel/<int:pid>/delete",methods=["POST"])
def delete_person(pid):
    if not admin(): return redirect("/admin/login")
    q("delete from personnel where id=%s",(pid,)); flash("Personel silindi."); return redirect("/admin/personnel")

@app.route("/admin/advances",methods=["GET","POST"])
def advances():
    if not admin(): return redirect("/admin/login")
    if request.method=="POST":
        pid=int(request.form["person_id"]); amount=float(request.form["amount"]); q("insert into advances(person_id,amount,note,status) values(%s,%s,'','Beklemede')",(pid,amount))
        p=q("select full_name from personnel where id=%s",(pid,),fetch=True,one=True); notify("Yeni avans",f"{p['full_name']} için {amount:.2f} TL avans girildi.",pid); flash("Avans kaydedildi.")
    people=q("select * from personnel order by full_name",fetch=True); rows=q("select a.*,p.full_name from advances a join personnel p on p.id=a.person_id order by a.id desc limit 300",fetch=True)
    opts="".join([f"<option value='{p['id']}'>{p['full_name']}</option>" for p in people]); trs="".join([f"<tr><td>{r['full_name']}</td><td>{float(r['amount']):.2f} TL</td><td>{r['status']}</td></tr>" for r in rows])
    return render_template("table.html",title="Avanslar",subtitle="Avans bildirimi sadece ilgili personelde görünür.",body=f"<div class='card'><form method='post' class='form-grid'><div class='field'><label>Personel</label><select name='person_id'>{opts}</select></div><div class='field'><label>Tutar</label><input name='amount' type='number' step='0.01' required></div><button class='btn btn-orange'>Avans Ekle</button></form></div><div class='card'><table class='table'><tr><th>Personel</th><th>Tutar</th><th>Durum</th></tr>{trs}</table></div>")

@app.route("/admin/leaves",methods=["GET","POST"])
def leaves():
    if not admin(): return redirect("/admin/login")
    if request.method=="POST":
        pid=int(request.form["person_id"]); start=request.form["start_date"]; end=request.form["end_date"]; count=days_between(start,end)
        p=q("select * from personnel where id=%s",(pid,),fetch=True,one=True)
        if p and p["annual_leave_remaining"]>=count:
            q("insert into leaves(person_id,start_date,end_date,days_count,status) values(%s,%s,%s,%s,'İzinli')",(pid,start,end,count)); q("update personnel set annual_leave_used=annual_leave_used+%s,annual_leave_remaining=annual_leave_remaining-%s where id=%s",(count,count,pid)); notify("İzin onaylandı",f"{count} günlük iznin işlendi.",pid); flash("İzin kaydedildi.")
        else: flash("Yetersiz izin.")
    people=q("select * from personnel order by full_name",fetch=True); rows=q("select l.*,p.full_name from leaves l join personnel p on p.id=l.person_id order by l.id desc limit 300",fetch=True)
    opts="".join([f"<option value='{p['id']}'>{p['full_name']} - Kalan {p['annual_leave_remaining']} gün</option>" for p in people]); trs="".join([f"<tr><td>{r['full_name']}</td><td>{r['start_date']} - {r['end_date']}</td><td>{r['days_count']}</td><td>{r['status']}</td></tr>" for r in rows])
    return render_template("table.html",title="İzinler",subtitle="İzin onayı sadece ilgili personele bildirim gönderir.",body=f"<div class='card'><form method='post' class='form-grid'><div class='field'><label>Personel</label><select name='person_id'>{opts}</select></div><div class='field'><label>Başlangıç</label><input name='start_date' type='date' required></div><div class='field'><label>Bitiş</label><input name='end_date' type='date' required></div><button class='btn btn-green'>İzin Ekle</button></form></div><div class='card'><table class='table'><tr><th>Personel</th><th>Tarih</th><th>Gün</th><th>Durum</th></tr>{trs}</table></div>")

@app.route("/admin/leave-requests")
def leave_requests_page():
    if not admin(): return redirect("/admin/login")
    rows=q("select lr.*,p.full_name from leave_requests lr join personnel p on p.id=lr.person_id order by lr.id desc limit 300",fetch=True)
    trs="".join([f"<tr><td>{r['full_name']}</td><td>{r['start_date']} - {r['end_date']}</td><td>{r['days_count']}</td><td>{r['note'] or '-'}</td><td>{r['status']}</td><td><a class='btn btn-green' href='/admin/leave-requests/{r['id']}/approve'>Onayla</a></td></tr>" for r in rows])
    return render_template("table.html",title="İzin Talepleri",subtitle="Personel uygulamasından gelen talepler.",body=f"<div class='card'><table class='table'><tr><th>Personel</th><th>Tarih</th><th>Gün</th><th>Not</th><th>Durum</th><th>İşlem</th></tr>{trs}</table></div>")
@app.route("/admin/leave-requests/<int:rid>/approve")
def approve_leave_request(rid):
    if not admin(): return redirect("/admin/login")
    req=q("select lr.*,p.full_name,p.annual_leave_remaining from leave_requests lr join personnel p on p.id=lr.person_id where lr.id=%s",(rid,),fetch=True,one=True)
    if not req: flash("Talep yok."); return redirect("/admin/leave-requests")
    if req["status"]=="Onaylandı": flash("Zaten onaylandı."); return redirect("/admin/leave-requests")
    if req["annual_leave_remaining"]<req["days_count"]: flash("Yetersiz izin."); return redirect("/admin/leave-requests")
    q("insert into leaves(person_id,start_date,end_date,days_count,status) values(%s,%s,%s,%s,'İzinli')",(req["person_id"],req["start_date"],req["end_date"],req["days_count"]))
    q("update personnel set annual_leave_used=annual_leave_used+%s,annual_leave_remaining=annual_leave_remaining-%s where id=%s",(req["days_count"],req["days_count"],req["person_id"]))
    q("update leave_requests set status='Onaylandı' where id=%s",(rid,)); notify("İzin onaylandı",f"{req['days_count']} günlük izin talebin onaylandı.",req["person_id"]); flash("İzin onaylandı."); return redirect("/admin/leave-requests")

@app.route("/admin/salary")
def salary():
    if not admin(): return redirect("/admin/login")
    rows=q("select p.*,coalesce(sum(a.amount),0) total_advance from personnel p left join advances a on a.person_id=p.id group by p.id order by full_name",fetch=True); trs=""
    for r in rows:
        s=float(r["salary"] or 0); a=float(r["total_advance"] or 0); trs+=f"<tr><td>{r['full_name']}</td><td>{r['department']}</td><td>{s:.2f} TL</td><td>{a:.2f} TL</td><td>{s-a:.2f} TL</td><td><form method='post' action='/admin/payroll-paid/{r['id']}'><button class='btn btn-green'>Maaş Yatırıldı Bildirimi</button></form></td></tr>"
    return render_template("table.html",title="Maaşlar",subtitle="Maaş özeti.",body=f"<div class='card'><table class='table'><tr><th>Personel</th><th>Bölüm</th><th>Maaş</th><th>Avans</th><th>Kalan</th><th>Bildirim</th></tr>{trs}</table></div>")
@app.route("/admin/attendance")
def attendance():
    if not admin(): return redirect("/admin/login")
    rows=q("select a.*,p.full_name from attendance_logs a join personnel p on p.id=a.person_id order by a.id desc limit 300",fetch=True)
    trs="".join([f"<tr><td>{r['full_name']}</td><td>{'Giriş' if r['event_type']=='entry' else 'Çıkış'}</td><td>{r['event_time']}</td><td>{warning_for(r['event_type'],r['event_time']) or '-'}</td></tr>" for r in rows])
    return render_template("table.html",title="Giriş Çıkış",subtitle="Giriş/çıkış kayıtları.",body=f"<div class='card'><table class='table'><tr><th>Personel</th><th>Tip</th><th>Zaman</th><th>Uyarı</th></tr>{trs}</table></div>")
@app.route("/admin/notifications")
def notifications_page():
    if not admin(): return redirect("/admin/login")
    rows=q("select n.*,p.full_name from notifications n left join personnel p on p.id=n.person_id order by n.id desc limit 300",fetch=True)
    trs="".join([f"<tr><td>{r['created_at']}</td><td>{r['full_name'] or 'Genel'}</td><td>{r['event_type']}</td><td>{r['message']}</td></tr>" for r in rows])
    return render_template("table.html",title="Bildirimler",subtitle="Panelde tüm bildirimler görünür; personelde sadece kendi bildirimi görünür.",body=f"<div class='card'><table class='table'><tr><th>Zaman</th><th>Personel</th><th>Tip</th><th>Mesaj</th></tr>{trs}</table></div>")
@app.route("/admin/reports")
def reports():
    if not admin(): return redirect("/admin/login")
    rows=report_rows(); trs=""
    for r in rows:
        s=float(r["salary"] or 0); a=float(r["total_advance"] or 0); trs+=f"<tr><td>{r['full_name']}</td><td>{r['department']}</td><td>{r['monthly_days']}</td><td>{r['late_entries']}</td><td>{r['early_exits']}</td><td>{a:.2f} TL</td><td>{s-a:.2f} TL</td></tr>"
    return render_template("table.html",title="Aylık Rapor",subtitle="PDF rapor.",body=f"<div class='card'><a class='btn btn-green' href='/admin/reports/pdf'>PDF İndir</a></div><div class='card'><table class='table'><tr><th>Personel</th><th>Bölüm</th><th>Gün</th><th>Geç</th><th>Erken</th><th>Avans</th><th>Kalan Maaş</th></tr>{trs}</table></div>")
@app.route("/admin/reports/pdf")
def reports_pdf():
    if not admin(): return redirect("/admin/login")
    rows=report_rows(); buf=BytesIO(); doc=SimpleDocTemplate(buf,pagesize=landscape(A4),rightMargin=24,leftMargin=24,topMargin=24,bottomMargin=24)
    styles=getSampleStyleSheet(); story=[Paragraph("Personel Sistemi",styles["Title"]),Paragraph("Aylik Personel Raporu",styles["Heading2"]),Paragraph(datetime.now(TR_TZ).strftime("Tarih/Saat: %Y-%m-%d %H:%M"),styles["Normal"]),Spacer(1,12)]
    data=[["Personel","Bolum","Calisma","Gec","Erken","Avans TL","Kalan Maas TL"]]
    for r in rows:
        s=float(r["salary"] or 0); a=float(r["total_advance"] or 0); data.append([str(r["full_name"]),str(r["department"]),str(r["monthly_days"]),str(r["late_entries"]),str(r["early_exits"]),f"{a:.2f}",f"{s-a:.2f}"])
    table=Table(data,repeatRows=1); table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#1e293b")),("TEXTCOLOR",(0,0),(-1,0),colors.white),("GRID",(0,0),(-1,-1),0.5,colors.grey),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#eef2f7")])]))
    story.append(table); doc.build(story); pdf=buf.getvalue(); buf.close()
    return Response(pdf,mimetype="application/pdf",headers={"Content-Disposition":"attachment; filename=personel_aylik_rapor.pdf"})


@app.route("/api/server-time")
def api_server_time():
    return jsonify({"status":"ok","timezone":"Europe/Istanbul","datetime":now_str(),"date":today_iso(),"time":datetime.now(TR_TZ).strftime("%H:%M:%S")})

@app.route("/api/my-qr", methods=["GET","POST"])
def api_my_qr():
    token=val("token")
    p=q("select id,full_name,token from personnel where token=%s and active=1",(token,),fetch=True,one=True)
    if not p: return jsonify({"status":"error","message":"geçersiz giriş"}),401
    qr_payload=f"PERSONEL:{p['id']}:{p['token']}"
    return jsonify({"status":"ok","person_id":p["id"],"full_name":p["full_name"],"qr_payload":qr_payload,"token":p["token"]})

@app.route("/api/qr/verify", methods=["GET","POST"])
def api_qr_verify():
    qr_payload=val("qr_payload") or val("qr") or ""
    action=val("action","entry")
    try:
        _, pid, token = qr_payload.split(":",2)
        pid=int(pid)
    except Exception:
        return jsonify({"status":"error","message":"QR formatı geçersiz"}),400
    p=q("select id,full_name,token from personnel where id=%s and token=%s and active=1",(pid,token),fetch=True,one=True)
    if not p: return jsonify({"status":"error","message":"Bu QR bu personele ait değil veya geçersiz"}),403
    event_type="exit" if action=="exit" else "entry"
    t=now_str()
    q("insert into attendance_logs(person_id,event_type,event_time) values(%s,%s,%s)",(pid,event_type,t))
    return jsonify({"status":"ok","person_id":pid,"full_name":p["full_name"],"event_type":event_type,"event_time":t,"warning":warning_for(event_type,t)})

@app.route("/api/employee-profile", methods=["GET","POST"])
def api_employee_profile():
    token=val("token")
    p=q("select * from personnel where token=%s and active=1",(token,),fetch=True,one=True)
    if not p: return jsonify({"status":"error","message":"geçersiz giriş"}),401
    if request.method=="POST":
        phone=val("phone","")
        address=val("address","")
        photo_data=val("photo_data",p.get("photo_data") or "")
        q("update personnel set phone=%s,address=%s,photo_data=%s where id=%s",(phone,address,photo_data,p["id"]))
        notify("Profil güncellendi", "Personel profil bilgileri güncellendi.", p["id"])
        return jsonify({"status":"ok","message":"Profil kaydedildi","person":person_summary(p["id"])})
    return jsonify({"status":"ok","person":person_summary(p["id"])})

@app.route("/admin/payroll-paid/<int:pid>", methods=["POST","GET"])
def payroll_paid(pid):
    if not admin(): return redirect("/admin/login")
    p=person_summary(pid)
    if not p: flash("Personel bulunamadı."); return redirect("/admin/salary")
    amount=float(p["remaining_salary"] or 0)
    q("insert into payroll_events(person_id,amount,message,created_at) values(%s,%s,%s,%s)",(pid,amount,"Maaş yatırıldı bildirimi gönderildi",now_str()))
    notify("Maaş yatırıldı", f"{amount:.2f} TL maaş ödemen yatırıldı.", pid)
    flash("Maaş yatırıldı bildirimi gönderildi.")
    return redirect("/admin/salary")

@app.route("/admin/puantaj")
def puantaj():
    if not admin(): return redirect("/admin/login")
    rows=report_rows(); body=""; month=month_key()
    for r in rows:
        salary=float(r["salary"] or 0); day_price=salary/30 if salary else 0
        came=int(r["monthly_days"] or 0); absent=max(30-came,0); cut=absent*day_price
        net=max(salary-float(r["total_advance"] or 0)-cut,0)
        body+=f"<tr><td>{r['full_name']}</td><td>{r['department']}</td><td>{came}</td><td>{absent}</td><td>{cut:.2f} TL</td><td>{net:.2f} TL</td></tr>"
    return render_template("table.html",title="Puantaj Sistemi",subtitle=f"{month} ayı - gelmediği gün otomatik maaş kesintisi hesaplanır.",body=f"<div class='card'><table class='table'><tr><th>Personel</th><th>Bölüm</th><th>Geldiği Gün</th><th>Gelmediği Gün</th><th>Kesinti</th><th>Net Maaş</th></tr>{body}</table></div>")

@app.route("/personel/login", methods=["GET","POST"])
def personel_login_page():
    if request.method=="POST":
        u=request.form.get("username"); pw=request.form.get("password")
        p=q("select * from personnel where username=%s and password=%s and active=1",(u,pw),fetch=True,one=True)
        if p:
            token=p.get("token") or secrets.token_hex(24); q("update personnel set token=%s where id=%s",(token,p["id"]))
            session["personel_token"]=token; return redirect("/personel/panel")
        flash("Hatalı kullanıcı adı veya şifre")
    return render_template("personel_login.html")

@app.route("/personel/logout")
def personel_logout():
    session.pop("personel_token",None); return redirect("/personel/login")

def current_personel():
    token=session.get("personel_token")
    if not token: return None
    return q("select * from personnel where token=%s and active=1",(token,),fetch=True,one=True)

@app.route("/personel/panel")
def personel_panel():
    p=current_personel()
    if not p: return redirect("/personel/login")
    summary=person_summary(p["id"])
    notes=q("select * from notifications where person_id=%s order by id desc limit 8",(p["id"],),fetch=True)
    qr_payload=f"PERSONEL:{p['id']}:{p['token']}"
    return render_template("personel_panel.html",p=summary,notes=notes,qr_payload=qr_payload)

@app.route("/personel/profile", methods=["GET","POST"])
def personel_profile():
    p=current_personel()
    if not p: return redirect("/personel/login")
    if request.method=="POST":
        phone=request.form.get("phone","")
        address=request.form.get("address","")
        photo_data=request.form.get("photo_data",p.get("photo_data") or "")
        q("update personnel set phone=%s,address=%s,photo_data=%s where id=%s",(phone,address,photo_data,p["id"]))
        notify("Profil güncellendi","Profil bilgilerin kaydedildi.",p["id"])
        flash("Profil kaydedildi."); return redirect("/personel/profile")
    return render_template("personel_profile.html",p=person_summary(p["id"]))

@app.route("/api/health")
def health(): q("select 1",fetch=True,one=True); return jsonify({"status":"ok","database":"connected","mode":"qr-entry"})
@app.route("/api/personnel")
def api_personnel():
    m=month_key()
    rows=q("select p.id,p.full_name,p.department,p.annual_leave_remaining,p.salary,coalesce(sum(a.amount),0) total_advance,(select count(distinct substring(event_time,1,10)) from attendance_logs al where al.person_id=p.id and al.event_type='entry' and substring(al.event_time,1,7)=%s) monthly_days from personnel p left join advances a on a.person_id=p.id where p.active=1 group by p.id order by p.full_name",(m,),fetch=True)
    return jsonify([{"id":r["id"],"full_name":r["full_name"],"department":r["department"],"monthly_days":r["monthly_days"],"annual_leave_remaining":r["annual_leave_remaining"],"salary":float(r["salary"] or 0),"total_advance":float(r["total_advance"] or 0)} for r in rows])
@app.route("/api/entry",methods=["GET","POST"])
def api_entry():
    pid=val("person_id"); t=now_str()
    if not pid: return jsonify({"status":"error","message":"person_id eksik"}),400
    q("insert into attendance_logs(person_id,event_type,event_time) values(%s,'entry',%s)",(pid,t))
    p=q("select full_name from personnel where id=%s",(pid,),fetch=True,one=True)
    return jsonify({"status":"ok","full_name":p["full_name"] if p else "Personel","event_type":"entry","person_id":int(pid),"event_time":t,"warning":warning_for("entry",t)})
@app.route("/api/exit",methods=["GET","POST"])
def api_exit():
    pid=val("person_id"); t=now_str()
    if not pid: return jsonify({"status":"error","message":"person_id eksik"}),400
    q("insert into attendance_logs(person_id,event_type,event_time) values(%s,'exit',%s)",(pid,t))
    p=q("select full_name from personnel where id=%s",(pid,),fetch=True,one=True)
    return jsonify({"status":"ok","full_name":p["full_name"] if p else "Personel","event_type":"exit","person_id":int(pid),"event_time":t,"warning":warning_for("exit",t)})
@app.route("/api/today-status")
def api_today_status(): return jsonify(today_status_rows())
@app.route("/api/attendance")
def api_attendance(): return jsonify(q("select a.id,a.person_id,p.full_name,a.event_type,a.event_time from attendance_logs a join personnel p on p.id=a.person_id order by a.id desc limit 100",fetch=True))
@app.route("/api/leaves",methods=["GET"])
def api_leaves(): return jsonify(q("select l.id,l.person_id,p.full_name,l.start_date,l.end_date,l.days_count,l.status from leaves l join personnel p on p.id=l.person_id order by l.id desc limit 100",fetch=True))
@app.route("/api/leaves",methods=["POST"])
@app.route("/api/leave-add",methods=["GET","POST"])
def api_leave_add():
    pid=int(val("person_id")); start=val("start_date"); end=val("end_date")
    if not pid or not start or not end: return jsonify({"status":"error","message":"eksik alan"}),400
    count=days_between(start,end); p=q("select * from personnel where id=%s",(pid,),fetch=True,one=True)
    if not p: return jsonify({"status":"error","message":"personel yok"}),404
    if p["annual_leave_remaining"]<count: return jsonify({"status":"error","message":"yetersiz izin"}),400
    q("insert into leaves(person_id,start_date,end_date,days_count,status) values(%s,%s,%s,%s,'İzinli')",(pid,start,end,count))
    q("update personnel set annual_leave_used=annual_leave_used+%s,annual_leave_remaining=annual_leave_remaining-%s where id=%s",(count,count,pid))
    notify("İzin onaylandı",f"{count} günlük iznin işlendi.",pid)
    return jsonify({"status":"ok","person_id":pid,"days_count":count})
@app.route("/api/employee-login",methods=["GET","POST"])
def employee_login():
    u=val("username"); pw=val("password")
    p=q("select * from personnel where username=%s and password=%s and active=1",(u,pw),fetch=True,one=True)
    if not p: return jsonify({"status":"error","message":"Kullanıcı adı veya şifre hatalı"}),401
    token=p.get("token") or secrets.token_hex(24); q("update personnel set token=%s where id=%s",(token,p["id"]))
    return jsonify({"status":"ok","token":token,"person":person_summary(p["id"])})
@app.route("/api/employee-me",methods=["GET","POST"])
def employee_me():
    token=val("token"); p=q("select id from personnel where token=%s and active=1",(token,),fetch=True,one=True)
    if not p: return jsonify({"status":"error","message":"geçersiz giriş"}),401
    return jsonify({"status":"ok","person":person_summary(p["id"])})
@app.route("/api/employee-advances",methods=["GET","POST"])
def employee_advances():
    token=val("token"); p=q("select id from personnel where token=%s and active=1",(token,),fetch=True,one=True)
    if not p: return jsonify({"status":"error","message":"geçersiz giriş"}),401
    rows=q("select id,amount,note,status from advances where person_id=%s order by id desc limit 50",(p["id"],),fetch=True)
    return jsonify({"status":"ok","advances":[{"id":r["id"],"amount":float(r["amount"] or 0),"note":r["note"] or "","status":r["status"]} for r in rows]})
@app.route("/api/employee-leave-request",methods=["GET","POST"])
def employee_leave_request():
    token=val("token"); start=val("start_date"); end=val("end_date"); note=val("note","")
    p=q("select id,full_name from personnel where token=%s and active=1",(token,),fetch=True,one=True)
    if not p: return jsonify({"status":"error","message":"geçersiz giriş"}),401
    if not start or not end: return jsonify({"status":"error","message":"tarih eksik"}),400
    count=days_between(start,end)
    q("insert into leave_requests(person_id,start_date,end_date,days_count,note,status,created_at) values(%s,%s,%s,%s,%s,'Beklemede',%s)",(p["id"],start,end,count,note,now_str()))
    notify("Yeni izin talebi",f"{p['full_name']} {count} günlük izin talebi gönderdi.",p["id"])
    return jsonify({"status":"ok","message":"İzin talebi gönderildi","days_count":count})
@app.route("/api/employee-notifications",methods=["GET","POST"])
def employee_notifications():
    token=val("token"); p=q("select id from personnel where token=%s and active=1",(token,),fetch=True,one=True)
    if not p: return jsonify({"status":"error","message":"geçersiz giriş"}),401
    rows=q("select id,event_type,message,created_at,is_read from notifications where person_id=%s order by id desc limit 50",(p["id"],),fetch=True)
    return jsonify({"status":"ok","notifications":rows})

if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.environ.get("PORT",10000)))
