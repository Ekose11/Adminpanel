from flask import Flask, render_template, request, redirect, session, flash, jsonify, Response
from datetime import datetime, date
from urllib.parse import urlparse, unquote
from io import BytesIO
import os
import secrets
import pg8000

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "boztek-secret")
DATABASE_URL = os.environ.get("DATABASE_URL")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "saban")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "5109")
READY = False
ENTRY_LIMIT = "09:00:00"
EXIT_LIMIT = "18:00:00"

def parse_db_url():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL yok. Render > Environment içine Neon connection string ekle.")
    u = urlparse(DATABASE_URL)
    return {"user":unquote(u.username or ""),"password":unquote(u.password or ""),"host":u.hostname,"port":u.port or 5432,"database":(u.path or "/neondb").lstrip("/")}

def db():
    c = parse_db_url()
    return pg8000.connect(user=c["user"], password=c["password"], host=c["host"], port=c["port"], database=c["database"], ssl_context=True, timeout=20)

def rows_to_dicts(cur, rows):
    if not rows:
        return []
    cols = [c["name"] if isinstance(c, dict) else c[0] for c in cur.description]
    return [dict(zip(cols, r)) for r in rows]

def q(sql, params=None, fetch=False, one=False):
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute(sql, params or ())
        data = None
        if fetch:
            data = rows_to_dicts(cur, cur.fetchall())
            if one:
                data = data[0] if data else None
        conn.commit()
        cur.close()
        return data
    finally:
        conn.close()

def init_db():
    global READY
    q("""create table if not exists personnel(id serial primary key,full_name text not null,department text not null,annual_leave_total integer default 14,annual_leave_used integer default 0,annual_leave_remaining integer default 14,salary numeric default 0,active integer default 1,username text unique,password text,token text unique)""")
    q("""create table if not exists advances(id serial primary key,person_id integer references personnel(id) on delete cascade,amount numeric not null,note text,status text default 'Beklemede')""")
    q("""create table if not exists leaves(id serial primary key,person_id integer references personnel(id) on delete cascade,start_date text not null,end_date text not null,days_count integer default 0,status text default 'İzinli')""")
    q("""create table if not exists attendance_logs(id serial primary key,person_id integer references personnel(id) on delete cascade,event_type text not null,event_time text not null)""")
    q("""create table if not exists leave_requests(id serial primary key,person_id integer references personnel(id) on delete cascade,start_date text not null,end_date text not null,days_count integer default 0,note text,status text default 'Beklemede',created_at text not null)""")
    q("""create table if not exists notifications(id serial primary key,event_type text not null,message text not null,created_at text not null,is_read integer default 0)""")
    READY = True

@app.before_request
def before():
    global READY
    if not READY:
        init_db()

def admin(): return session.get("admin_ok") is True
def val(name, default=None): return request.form.get(name) or request.args.get(name) or default
def now_str(): return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def notify(event_type, message):
    q("insert into notifications(event_type,message,created_at,is_read) values(%s,%s,%s,0)", (event_type, message, now_str()))

def days_between(start, end):
    s = datetime.strptime(start, "%Y-%m-%d").date()
    e = datetime.strptime(end, "%Y-%m-%d").date()
    return max((e - s).days + 1, 1)

def time_part(ts):
    try:
        return ts.split(" ")[1]
    except Exception:
        return ""

def warning_for(event_type, event_time):
    t = time_part(event_time)
    if event_type == "entry" and t > ENTRY_LIMIT:
        return "Geç giriş"
    if event_type == "exit" and t < EXIT_LIMIT:
        return "Erken çıkış"
    return ""

def person_summary(pid):
    p = q("""select p.*, coalesce(sum(a.amount),0) total_advance from personnel p left join advances a on a.person_id=p.id where p.id=%s group by p.id""", (pid,), fetch=True, one=True)
    if not p: return None
    salary = float(p["salary"] or 0)
    advance = float(p["total_advance"] or 0)
    return {"id":p["id"],"full_name":p["full_name"],"department":p["department"],"salary":salary,"total_advance":advance,"remaining_salary":salary-advance,"annual_leave_total":p["annual_leave_total"],"annual_leave_used":p["annual_leave_used"],"annual_leave_remaining":p["annual_leave_remaining"]}

def today_status_rows():
    today = date.today().isoformat()
    people = q("select * from personnel where active=1 order by full_name", fetch=True)
    logs = q("""select distinct on (person_id) person_id,event_type,event_time from attendance_logs where substring(event_time,1,10)=%s order by person_id,id desc""", (today,), fetch=True)
    log_map = {r["person_id"]: r for r in logs}
    out = []
    for p in people:
        log = log_map.get(p["id"])
        if not log:
            out.append({"id":p["id"],"full_name":p["full_name"],"department":p["department"],"status":"none","last_time":"","event_type":"","warning":""})
        else:
            st = "inside" if log["event_type"] == "entry" else "out"
            out.append({"id":p["id"],"full_name":p["full_name"],"department":p["department"],"status":st,"last_time":log["event_time"],"event_type":log["event_type"],"warning":warning_for(log["event_type"], log["event_time"])})
    return out

def report_rows():
    month = datetime.now().strftime("%Y-%m")
    return q("""select p.id,p.full_name,p.department,p.annual_leave_used,p.annual_leave_remaining,p.salary,coalesce(sum(a.amount),0) total_advance,(select count(distinct substring(event_time,1,10)) from attendance_logs al where al.person_id=p.id and al.event_type='entry' and substring(al.event_time,1,7)=%s) monthly_days,(select count(*) from attendance_logs al where al.person_id=p.id and al.event_type='entry' and substring(al.event_time,1,7)=%s and substring(al.event_time,12,8)>%s) late_entries,(select count(*) from attendance_logs al where al.person_id=p.id and al.event_type='exit' and substring(al.event_time,1,7)=%s and substring(al.event_time,12,8)<%s) early_exits from personnel p left join advances a on a.person_id=p.id group by p.id order by p.full_name""", (month, month, ENTRY_LIMIT, month, EXIT_LIMIT), fetch=True)

@app.route("/")
def home(): return redirect("/admin/dashboard") if admin() else redirect("/admin/login")

@app.route("/admin/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        if request.form.get("username") == ADMIN_USERNAME and request.form.get("password") == ADMIN_PASSWORD:
            session["admin_ok"] = True
            return redirect("/admin/dashboard")
        flash("Hatalı kullanıcı adı veya şifre")
    return render_template("login.html")

@app.route("/admin/logout")
def logout():
    session.clear()
    return redirect("/admin/login")

@app.route("/admin")
@app.route("/admin/dashboard")
def dashboard():
    if not admin(): return redirect("/admin/login")
    today_status = today_status_rows()
    inside = sum(1 for r in today_status if r["status"] == "inside")
    late = sum(1 for r in today_status if r["warning"] == "Geç giriş")
    early = sum(1 for r in today_status if r["warning"] == "Erken çıkış")
    stats = q("select (select count(*) from personnel) personel,(select count(*) from advances) avans,(select count(*) from leaves) izin", fetch=True, one=True)
    stats["inside"] = inside
    stats["late"] = late
    stats["early"] = early
    notifications = q("select * from notifications order by id desc limit 8", fetch=True)
    return render_template("dashboard.html", title="Dashboard", stats=stats, today_status=today_status, notifications=notifications)

@app.route("/admin/personnel", methods=["GET","POST"])
def personnel():
    if not admin(): return redirect("/admin/login")
    if request.method == "POST":
        total = int(request.form.get("annual_leave_total", 14))
        salary = float(request.form.get("salary", 0))
        try:
            q("insert into personnel(full_name,department,annual_leave_total,annual_leave_used,annual_leave_remaining,salary,active,username,password,token) values(%s,%s,%s,0,%s,%s,1,%s,%s,%s)", (request.form["full_name"], request.form["department"], total, total, salary, request.form.get("username") or None, request.form.get("password") or None, secrets.token_hex(24)))
            flash("Personel kalıcı olarak eklendi.")
        except Exception:
            flash("Personel eklenemedi. Kullanıcı adı aynı olabilir.")
    rows = q("select * from personnel order by id desc", fetch=True)
    return render_template("personnel.html", title="Personel", rows=rows)

@app.route("/admin/personnel/<int:pid>/edit", methods=["GET","POST"])
def edit_person(pid):
    if not admin(): return redirect("/admin/login")
    p = q("select * from personnel where id=%s", (pid,), fetch=True, one=True)
    if not p: return redirect("/admin/personnel")
    if request.method == "POST":
        total = int(request.form.get("annual_leave_total", 0))
        used = int(request.form.get("annual_leave_used", 0))
        remaining = max(total - used, 0)
        token = p.get("token") or secrets.token_hex(24)
        q("update personnel set full_name=%s,department=%s,username=%s,password=%s,annual_leave_total=%s,annual_leave_used=%s,annual_leave_remaining=%s,salary=%s,active=%s,token=%s where id=%s", (request.form["full_name"], request.form["department"], request.form.get("username") or None, request.form.get("password") or None, total, used, remaining, float(request.form.get("salary",0)), int(request.form.get("active",1)), token, pid))
        flash("Personel güncellendi.")
        return redirect("/admin/personnel")
    return render_template("edit.html", title="Düzenle", p=p)

@app.route("/admin/personnel/<int:pid>/delete", methods=["POST"])
def delete_person(pid):
    if not admin(): return redirect("/admin/login")
    q("delete from personnel where id=%s", (pid,))
    flash("Personel silindi.")
    return redirect("/admin/personnel")

@app.route("/admin/advances", methods=["GET","POST"])
def advances():
    if not admin(): return redirect("/admin/login")
    if request.method == "POST":
        pid = request.form["person_id"]
        amount = float(request.form["amount"])
        q("insert into advances(person_id,amount,note,status) values(%s,%s,'','Beklemede')", (pid, amount))
        p = q("select full_name from personnel where id=%s", (pid,), fetch=True, one=True)
        notify("Yeni avans", f"{p['full_name']} için {amount:.2f} TL avans girildi.")
        flash("Avans kaydedildi.")
    people = q("select * from personnel order by full_name", fetch=True)
    rows = q("select a.*,p.full_name from advances a join personnel p on p.id=a.person_id order by a.id desc limit 300", fetch=True)
    opts = "".join([f"<option value='{p['id']}'>{p['full_name']}</option>" for p in people])
    trs = "".join([f"<tr><td>{r['full_name']}</td><td>{float(r['amount']):.2f} TL</td><td><span class='badge orange'>{r['status']}</span></td></tr>" for r in rows])
    body = f"<div class='card'><h2>Yeni Avans</h2><form method='post' class='form-grid'><div class='field'><label>Personel</label><select name='person_id'>{opts}</select></div><div class='field'><label>Avans Tutarı</label><input name='amount' type='number' step='0.01' required></div><div><button class='btn btn-orange'>Avans Ekle</button></div></form></div><div class='card'><div class='table-wrap'><table class='table'><tr><th>Personel</th><th>Tutar</th><th>Durum</th></tr>{trs}</table></div></div>"
    return render_template("table.html", title="Avanslar", subtitle="Avans kaydedildiğinde kalan maaş otomatik hesaplanır.", body=body)

@app.route("/admin/leaves", methods=["GET","POST"])
def leaves():
    if not admin(): return redirect("/admin/login")
    if request.method == "POST":
        pid = request.form["person_id"]
        start = request.form["start_date"]
        end = request.form["end_date"]
        count = days_between(start, end)
        p = q("select * from personnel where id=%s", (pid,), fetch=True, one=True)
        if p and p["annual_leave_remaining"] >= count:
            q("insert into leaves(person_id,start_date,end_date,days_count,status) values(%s,%s,%s,%s,'İzinli')", (pid,start,end,count))
            q("update personnel set annual_leave_used=annual_leave_used+%s, annual_leave_remaining=annual_leave_remaining-%s where id=%s", (count,count,pid))
            notify("İzin onaylandı", f"{p['full_name']} için {count} günlük izin işlendi.")
            flash("İzin kaydedildi.")
        else:
            flash("Yetersiz izin hakkı.")
    people = q("select * from personnel order by full_name", fetch=True)
    rows = q("select l.*,p.full_name from leaves l join personnel p on p.id=l.person_id order by l.id desc limit 300", fetch=True)
    opts = "".join([f"<option value='{p['id']}'>{p['full_name']} - Kalan {p['annual_leave_remaining']} gün</option>" for p in people])
    trs = "".join([f"<tr><td>{r['full_name']}</td><td>{r['start_date']} - {r['end_date']}</td><td>{r['days_count']} gün</td><td><span class='badge green'>{r['status']}</span></td></tr>" for r in rows])
    body = f"<div class='card'><h2>Yeni İzin</h2><form method='post' class='form-grid'><div class='field'><label>Personel</label><select name='person_id'>{opts}</select></div><div class='field'><label>Başlangıç</label><input name='start_date' type='date' required></div><div class='field'><label>Bitiş</label><input name='end_date' type='date' required></div><div><button class='btn btn-green'>İzin Ekle</button></div></form></div><div class='card'><div class='table-wrap'><table class='table'><tr><th>Personel</th><th>Tarih</th><th>Gün</th><th>Durum</th></tr>{trs}</table></div></div>"
    return render_template("table.html", title="İzinler", subtitle="İzin girildiğinde yıllık izin hakkından otomatik düşer.", body=body)

@app.route("/admin/leave-requests")
def leave_requests_page():
    if not admin(): return redirect("/admin/login")
    rows = q("select lr.*,p.full_name from leave_requests lr join personnel p on p.id=lr.person_id order by lr.id desc limit 300", fetch=True)
    trs = "".join([f"<tr><td>{r['full_name']}</td><td>{r['start_date']} - {r['end_date']}</td><td>{r['days_count']} gün</td><td>{r['note'] or '-'}</td><td><span class='badge orange'>{r['status']}</span></td><td><a class='btn btn-green' href='/admin/leave-requests/{r['id']}/approve'>Onayla</a></td></tr>" for r in rows])
    body = f"<div class='card'><div class='table-wrap'><table class='table'><tr><th>Personel</th><th>Tarih</th><th>Gün</th><th>Not</th><th>Durum</th><th>İşlem</th></tr>{trs}</table></div></div>"
    return render_template("table.html", title="İzin Talepleri", subtitle="Personel uygulamasından gelen izin talepleri.", body=body)

@app.route("/admin/leave-requests/<int:rid>/approve")
def approve_leave_request(rid):
    if not admin(): return redirect("/admin/login")
    req = q("select lr.*,p.full_name,p.annual_leave_remaining from leave_requests lr join personnel p on p.id=lr.person_id where lr.id=%s", (rid,), fetch=True, one=True)
    if not req:
        flash("Talep bulunamadı.")
        return redirect("/admin/leave-requests")
    if req["status"] == "Onaylandı":
        flash("Bu talep zaten onaylı.")
        return redirect("/admin/leave-requests")
    if req["annual_leave_remaining"] < req["days_count"]:
        flash("Yetersiz izin hakkı.")
        return redirect("/admin/leave-requests")
    q("insert into leaves(person_id,start_date,end_date,days_count,status) values(%s,%s,%s,%s,'İzinli')", (req["person_id"], req["start_date"], req["end_date"], req["days_count"]))
    q("update personnel set annual_leave_used=annual_leave_used+%s, annual_leave_remaining=annual_leave_remaining-%s where id=%s", (req["days_count"], req["days_count"], req["person_id"]))
    q("update leave_requests set status='Onaylandı' where id=%s", (rid,))
    notify("İzin onaylandı", f"{req['full_name']} izin talebi onaylandı.")
    flash("İzin talebi onaylandı.")
    return redirect("/admin/leave-requests")

@app.route("/admin/salary")
def salary():
    if not admin(): return redirect("/admin/login")
    rows = q("select p.*,coalesce(sum(a.amount),0) total_advance from personnel p left join advances a on a.person_id=p.id group by p.id order by full_name", fetch=True)
    trs = ""
    for r in rows:
        s = float(r["salary"] or 0); a = float(r["total_advance"] or 0)
        trs += f"<tr><td><b>{r['full_name']}</b></td><td>{r['department']}</td><td>{s:.2f} TL</td><td>{a:.2f} TL</td><td><b>{s-a:.2f} TL</b></td></tr>"
    body = f"<div class='card'><div class='table-wrap'><table class='table'><tr><th>Personel</th><th>Bölüm</th><th>Maaş</th><th>Toplam Avans</th><th>Kalan Maaş</th></tr>{trs}</table></div></div>"
    return render_template("table.html", title="Maaşlar", subtitle="Avanslar maaştan anlık düşer.", body=body)

@app.route("/admin/attendance")
def attendance():
    if not admin(): return redirect("/admin/login")
    rows = q("select a.*,p.full_name from attendance_logs a join personnel p on p.id=a.person_id order by a.id desc limit 300", fetch=True)
    trs = ""
    for r in rows:
        warning = warning_for(r["event_type"], r["event_time"])
        badge = f"<span class='badge orange'>{warning}</span>" if warning else "-"
        trs += f"<tr><td>{r['full_name']}</td><td>{'Giriş' if r['event_type']=='entry' else 'Çıkış'}</td><td>{r['event_time']}</td><td>{badge}</td></tr>"
    body = f"<div class='card'><div class='table-wrap'><table class='table'><tr><th>Personel</th><th>Tip</th><th>Zaman</th><th>Uyarı</th></tr>{trs}</table></div></div>"
    return render_template("table.html", title="Giriş / Çıkış", subtitle="Geç giriş ve erken çıkış uyarıları aktiftir.", body=body)

@app.route("/admin/annual-leave")
def annual_leave():
    if not admin(): return redirect("/admin/login")
    rows = q("select * from personnel order by full_name", fetch=True)
    trs = "".join([f"<tr><td>{r['full_name']}</td><td>{r['department']}</td><td>{r['annual_leave_total']}</td><td>{r['annual_leave_used']}</td><td><b>{r['annual_leave_remaining']}</b></td></tr>" for r in rows])
    body = f"<div class='card'><div class='table-wrap'><table class='table'><tr><th>Personel</th><th>Bölüm</th><th>Toplam</th><th>Kullanılan</th><th>Kalan</th></tr>{trs}</table></div></div>"
    return render_template("table.html", title="Yıllık İzin", subtitle="Personel yıllık izin hakları.", body=body)

@app.route("/admin/notifications")
def notifications_page():
    if not admin(): return redirect("/admin/login")
    rows = q("select * from notifications order by id desc limit 300", fetch=True)
    trs = "".join([f"<tr><td>{r['created_at']}</td><td><span class='badge blue'>{r['event_type']}</span></td><td>{r['message']}</td></tr>" for r in rows])
    body = f"<div class='card'><div class='table-wrap'><table class='table'><tr><th>Zaman</th><th>Tip</th><th>Mesaj</th></tr>{trs}</table></div></div>"
    return render_template("table.html", title="Bildirimler", subtitle="Yeni avans, izin onayı ve maaş bildirim kayıtları.", body=body)

@app.route("/admin/notify-salary")
def notify_salary():
    if not admin(): return redirect("/admin/login")
    notify("Maaş yattı", "Maaş bildirim kaydı oluşturuldu.")
    flash("Maaş yattı bildirimi oluşturuldu.")
    return redirect("/admin/notifications")

@app.route("/admin/reports")
def reports():
    if not admin(): return redirect("/admin/login")
    rows = report_rows()
    trs = ""
    for r in rows:
        s = float(r["salary"] or 0); a = float(r["total_advance"] or 0)
        trs += f"<tr><td>{r['full_name']}</td><td>{r['department']}</td><td>{r['monthly_days']}</td><td>{r['late_entries']}</td><td>{r['early_exits']}</td><td>{r['annual_leave_used']}</td><td>{r['annual_leave_remaining']}</td><td>{a:.2f} TL</td><td>{s-a:.2f} TL</td></tr>"
    body = f"<div class='card'><a class='btn btn-green' href='/admin/reports/pdf'>Aylık Raporu PDF İndir</a> <a class='btn btn-orange' href='/admin/notify-salary'>Maaş Yattı Bildirimi Oluştur</a></div><div class='card'><div class='table-wrap'><table class='table'><tr><th>Personel</th><th>Bölüm</th><th>Çalışma Günü</th><th>Geç</th><th>Erken</th><th>Kullanılan İzin</th><th>Kalan İzin</th><th>Avans</th><th>Kalan Maaş</th></tr>{trs}</table></div></div>"
    return render_template("table.html", title="Aylık Rapor", subtitle="Çalışma günü, geç giriş, erken çıkış, maaş ve avans özeti.", body=body)

@app.route("/admin/reports/pdf")
def reports_pdf():
    if not admin(): return redirect("/admin/login")
    rows = report_rows()
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(A4), rightMargin=24, leftMargin=24, topMargin=24, bottomMargin=24)
    styles = getSampleStyleSheet()
    story = []
    story.append(Paragraph("BOZTEK", styles["Title"]))
    story.append(Paragraph("Aylik Personel Raporu", styles["Heading2"]))
    story.append(Paragraph(datetime.now().strftime("Tarih/Saat: %Y-%m-%d %H:%M"), styles["Normal"]))
    story.append(Spacer(1, 12))
    total_days = sum(int(r["monthly_days"] or 0) for r in rows)
    total_late = sum(int(r["late_entries"] or 0) for r in rows)
    total_early = sum(int(r["early_exits"] or 0) for r in rows)
    total_adv = sum(float(r["total_advance"] or 0) for r in rows)
    total_remaining = sum(float(r["salary"] or 0) - float(r["total_advance"] or 0) for r in rows)
    story.append(Paragraph(f"Toplam Calisma Gunu: {total_days} | Gec Giris: {total_late} | Erken Cikis: {total_early} | Toplam Avans: {total_adv:.2f} TL | Kalan Maas Toplami: {total_remaining:.2f} TL", styles["Normal"]))
    story.append(Spacer(1, 12))
    data = [["Personel","Bolum","Calisma","Gec","Erken","Kull. Izin","Kalan Izin","Avans TL","Kalan Maas TL"]]
    for r in rows:
        s = float(r["salary"] or 0); a = float(r["total_advance"] or 0)
        data.append([str(r["full_name"]),str(r["department"]),str(r["monthly_days"]),str(r["late_entries"]),str(r["early_exits"]),str(r["annual_leave_used"]),str(r["annual_leave_remaining"]),f"{a:.2f}",f"{s-a:.2f}"])
    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([("BACKGROUND",(0,0),(-1,0),colors.HexColor("#1e293b")),("TEXTCOLOR",(0,0),(-1,0),colors.white),("GRID",(0,0),(-1,-1),0.5,colors.grey),("FONTNAME",(0,0),(-1,0),"Helvetica-Bold"),("ALIGN",(2,1),(-1,-1),"CENTER"),("ROWBACKGROUNDS",(0,1),(-1,-1),[colors.white,colors.HexColor("#eef2f7")])]))
    story.append(table)
    doc.build(story)
    pdf = buffer.getvalue()
    buffer.close()
    return Response(pdf, mimetype="application/pdf", headers={"Content-Disposition":"attachment; filename=boztek_profesyonel_aylik_rapor.pdf"})

@app.route("/api/health")
def health():
    q("select 1", fetch=True, one=True)
    return jsonify({"status":"ok","database":"connected","driver":"pg8000","mode":"full-upgrade"})

@app.route("/api/personnel")
def api_personnel():
    month = datetime.now().strftime("%Y-%m")
    rows = q("""select p.id,p.full_name,p.department,p.annual_leave_remaining,p.salary,coalesce(sum(a.amount),0) total_advance,(select count(distinct substring(event_time,1,10)) from attendance_logs al where al.person_id=p.id and al.event_type='entry' and substring(al.event_time,1,7)=%s) monthly_days from personnel p left join advances a on a.person_id=p.id where p.active=1 group by p.id order by p.full_name""", (month,), fetch=True)
    return jsonify([{"id":r["id"],"full_name":r["full_name"],"department":r["department"],"monthly_days":r["monthly_days"],"annual_leave_remaining":r["annual_leave_remaining"],"salary":float(r["salary"] or 0),"total_advance":float(r["total_advance"] or 0)} for r in rows])

@app.route("/api/today-status")
def api_today_status():
    return jsonify(today_status_rows())

@app.route("/api/entry", methods=["GET","POST"])
def api_entry():
    pid = val("person_id")
    if not pid: return jsonify({"status":"error","message":"person_id eksik"}), 400
    t = now_str()
    q("insert into attendance_logs(person_id,event_type,event_time) values(%s,'entry',%s)", (pid,t))
    return jsonify({"status":"ok","event_type":"entry","person_id":int(pid),"event_time":t,"warning":warning_for("entry", t)})

@app.route("/api/exit", methods=["GET","POST"])
def api_exit():
    pid = val("person_id")
    if not pid: return jsonify({"status":"error","message":"person_id eksik"}), 400
    t = now_str()
    q("insert into attendance_logs(person_id,event_type,event_time) values(%s,'exit',%s)", (pid,t))
    return jsonify({"status":"ok","event_type":"exit","person_id":int(pid),"event_time":t,"warning":warning_for("exit", t)})

@app.route("/api/attendance")
def api_attendance():
    rows = q("select a.id,a.person_id,p.full_name,a.event_type,a.event_time from attendance_logs a join personnel p on p.id=a.person_id order by a.id desc limit 100", fetch=True)
    for r in rows:
        r["warning"] = warning_for(r["event_type"], r["event_time"])
    return jsonify(rows)

@app.route("/api/leaves", methods=["GET"])
def api_leaves():
    return jsonify(q("select l.id,l.person_id,p.full_name,l.start_date,l.end_date,l.days_count,l.status from leaves l join personnel p on p.id=l.person_id order by l.id desc limit 100", fetch=True))

@app.route("/api/leaves", methods=["POST"])
@app.route("/api/leave-add", methods=["GET","POST"])
def api_leave_add():
    pid = val("person_id"); start = val("start_date"); end = val("end_date")
    if not pid or not start or not end: return jsonify({"status":"error","message":"eksik alan"}), 400
    count = days_between(start,end)
    p = q("select * from personnel where id=%s", (pid,), fetch=True, one=True)
    if not p: return jsonify({"status":"error","message":"personel yok"}), 404
    if p["annual_leave_remaining"] < count: return jsonify({"status":"error","message":"yetersiz izin"}), 400
    q("insert into leaves(person_id,start_date,end_date,days_count,status) values(%s,%s,%s,%s,'İzinli')", (pid,start,end,count))
    q("update personnel set annual_leave_used=annual_leave_used+%s, annual_leave_remaining=annual_leave_remaining-%s where id=%s", (count,count,pid))
    notify("İzin onaylandı", f"{p['full_name']} için {count} günlük izin işlendi.")
    return jsonify({"status":"ok","person_id":int(pid),"days_count":count})

@app.route("/api/employee-login", methods=["GET","POST"])
def employee_login():
    username = val("username"); password = val("password")
    p = q("select * from personnel where username=%s and password=%s and active=1", (username,password), fetch=True, one=True)
    if not p: return jsonify({"status":"error","message":"Kullanıcı adı veya şifre hatalı"}), 401
    token = p.get("token") or secrets.token_hex(24)
    q("update personnel set token=%s where id=%s", (token,p["id"]))
    return jsonify({"status":"ok","token":token,"person":person_summary(p["id"])})

@app.route("/api/employee-me", methods=["GET","POST"])
def employee_me():
    token = val("token")
    p = q("select id from personnel where token=%s and active=1", (token,), fetch=True, one=True)
    if not p: return jsonify({"status":"error","message":"geçersiz giriş"}), 401
    return jsonify({"status":"ok","person":person_summary(p["id"])})

@app.route("/api/employee-advances", methods=["GET","POST"])
def employee_advances():
    token = val("token")
    p = q("select id from personnel where token=%s and active=1", (token,), fetch=True, one=True)
    if not p: return jsonify({"status":"error","message":"geçersiz giriş"}), 401
    rows = q("select id,amount,note,status from advances where person_id=%s order by id desc limit 50", (p["id"],), fetch=True)
    return jsonify({"status":"ok","advances":[{"id":r["id"],"amount":float(r["amount"] or 0),"note":r["note"] or "","status":r["status"]} for r in rows]})

@app.route("/api/employee-leave-request", methods=["GET","POST"])
def employee_leave_request():
    token = val("token"); start = val("start_date"); end = val("end_date"); note = val("note","")
    p = q("select id,full_name from personnel where token=%s and active=1", (token,), fetch=True, one=True)
    if not p: return jsonify({"status":"error","message":"geçersiz giriş"}), 401
    if not start or not end: return jsonify({"status":"error","message":"tarih eksik"}), 400
    count = days_between(start,end)
    q("insert into leave_requests(person_id,start_date,end_date,days_count,note,status,created_at) values(%s,%s,%s,%s,%s,'Beklemede',%s)", (p["id"],start,end,count,note,now_str()))
    notify("Yeni izin talebi", f"{p['full_name']} {count} günlük izin talebi gönderdi.")
    return jsonify({"status":"ok","message":"İzin talebi gönderildi","days_count":count})

@app.route("/api/employee-notifications", methods=["GET","POST"])
def employee_notifications():
    token = val("token")
    p = q("select id from personnel where token=%s and active=1", (token,), fetch=True, one=True)
    if not p: return jsonify({"status":"error","message":"geçersiz giriş"}), 401
    rows = q("select * from notifications order by id desc limit 30", fetch=True)
    return jsonify({"status":"ok","notifications":rows})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",10000)))
