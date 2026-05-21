from flask import Flask, render_template, request, redirect, session, flash, jsonify, Response, send_file
from datetime import datetime, date, timedelta
from urllib.parse import urlparse, unquote
from io import BytesIO, StringIO
import os, secrets, csv
import pg8000

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.units import mm

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "personel-premium-secret")
DATABASE_URL = os.environ.get("DATABASE_URL")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "eren")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "1234")
READY = False
ENTRY_LIMIT = "09:00:00"
EXIT_LIMIT = "18:00:00"
DOUBLE_SCAN_SECONDS = 10
TERMINAL_QR_TOKEN = os.environ.get("TERMINAL_QR_TOKEN", "PERSONEL-TEK-QR-GIRIS-CIKIS")

FONT_NAME = "Helvetica"
try:
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    if os.path.exists(font_path):
        pdfmetrics.registerFont(TTFont("DejaVu", font_path))
        FONT_NAME = "DejaVu"
except Exception:
    FONT_NAME = "Helvetica"

# ---------------- DATABASE ----------------
def parse_db_url():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL bulunamadı. Render Environment içine DATABASE_URL eklenmeli.")
    u = urlparse(DATABASE_URL)
    return {
        "user": unquote(u.username or ""),
        "password": unquote(u.password or ""),
        "host": u.hostname,
        "port": u.port or 5432,
        "database": (u.path or "/neondb").lstrip("/"),
    }

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

def safe_alter(sql):
    try:
        q(sql)
    except Exception:
        pass

def init_db():
    global READY
    q("""create table if not exists personnel(
        id serial primary key,
        full_name text not null,
        department text not null,
        annual_leave_total integer default 14,
        annual_leave_used integer default 0,
        annual_leave_remaining integer default 14,
        salary numeric default 0,
        active integer default 1,
        username text unique,
        password text,
        token text unique
    )""")
    for col, typ in [
        ("shift_name", "text default 'Sabah'"),
        ("shift_start", "text default '09:00'"),
        ("shift_end", "text default '18:00'"),
        ("phone", "text default ''"),
        ("address", "text default ''"),
        ("photo_url", "text default ''"),
    ]:
        safe_alter(f"alter table personnel add column {col} {typ}")

    q("create table if not exists advances(id serial primary key, person_id integer references personnel(id) on delete cascade, amount numeric not null, note text default '', status text default 'Beklemede')")
    q("create table if not exists leaves(id serial primary key, person_id integer references personnel(id) on delete cascade, start_date text not null, end_date text not null, days_count integer default 0, status text default 'İzinli')")
    q("create table if not exists attendance_logs(id serial primary key, person_id integer references personnel(id) on delete cascade, event_type text not null, event_time text not null)")
    q("create table if not exists leave_requests(id serial primary key, person_id integer references personnel(id) on delete cascade, start_date text not null, end_date text not null, days_count integer default 0, note text default '', status text default 'Beklemede', created_at text not null)")
    q("create table if not exists notifications(id serial primary key, person_id integer references personnel(id) on delete cascade, event_type text not null, message text not null, created_at text not null, is_read integer default 0)")
    q("create table if not exists monthly_shifts(id serial primary key, person_id integer references personnel(id) on delete cascade, month text not null, day text not null, shift_name text not null, shift_start text not null, shift_end text not null, is_work_day integer default 1)")
    q("create table if not exists salary_payments(id serial primary key, person_id integer references personnel(id) on delete cascade, amount numeric not null, month text not null, note text default '', created_at text not null)")
    READY = True

@app.before_request
def before_request():
    global READY
    if not READY:
        init_db()

# ---------------- HELPERS ----------------
def admin_ok():
    return session.get("admin_ok") is True

def admin_required():
    if not admin_ok():
        return redirect("/admin/login")
    return None

def val(name, default=None):
    return request.form.get(name) or request.args.get(name) or default

def now_dt():
    # Render UTC olabilir; Türkiye için +3 saat kullanıyoruz.
    return datetime.utcnow() + timedelta(hours=3)

def now_str():
    return now_dt().strftime("%Y-%m-%d %H:%M:%S")

def today_str():
    return now_dt().date().isoformat()

def notify(event_type, message, person_id=None):
    q("insert into notifications(person_id,event_type,message,created_at,is_read) values(%s,%s,%s,%s,0)", (person_id, event_type, message, now_str()))

def days_between(start, end):
    s = datetime.strptime(start, "%Y-%m-%d").date()
    e = datetime.strptime(end, "%Y-%m-%d").date()
    return max((e - s).days + 1, 1)

def month_bounds(month=None):
    if not month:
        month = now_dt().strftime("%Y-%m")
    y, m = map(int, month.split("-"))
    start = date(y, m, 1)
    end = (date(y + 1, 1, 1) - timedelta(days=1)) if m == 12 else (date(y, m + 1, 1) - timedelta(days=1))
    return month, start, end

def workdays_in_month(month=None):
    month, start, end = month_bounds(month)
    days = []
    d = start
    while d <= end:
        if d.weekday() != 6:  # Pazar hariç
            days.append(d.isoformat())
        d += timedelta(days=1)
    return days

def time_part(ts):
    try:
        return ts.split(" ")[1]
    except Exception:
        return ""

def person_shift_for_day(person, day):
    ms = q("select * from monthly_shifts where person_id=%s and day=%s", (person["id"], day), fetch=True, one=True)
    if ms:
        return ms
    return {
        "shift_name": person.get("shift_name") or "Sabah",
        "shift_start": person.get("shift_start") or "09:00",
        "shift_end": person.get("shift_end") or "18:00",
        "is_work_day": 1,
    }

def warning_for_person(person_id, event_type, event_time):
    p = q("select * from personnel where id=%s", (person_id,), fetch=True, one=True)
    if not p:
        return ""
    day = event_time[:10]
    shift = person_shift_for_day(p, day)
    start = (shift.get("shift_start") or "09:00") + ":00"
    end = (shift.get("shift_end") or "18:00") + ":00"
    t = time_part(event_time)
    if event_type == "entry" and t > start:
        return "Geç giriş"
    if event_type == "exit" and t < end:
        return "Erken çıkış"
    return ""

def warning_for(event_type, event_time):
    t = time_part(event_time)
    if event_type == "entry" and t > ENTRY_LIMIT:
        return "Geç giriş"
    if event_type == "exit" and t < EXIT_LIMIT:
        return "Erken çıkış"
    return ""

def person_summary(pid):
    p = q("select p.*, coalesce(sum(a.amount),0) total_advance from personnel p left join advances a on a.person_id=p.id where p.id=%s group by p.id", (pid,), fetch=True, one=True)
    if not p:
        return None
    salary = float(p.get("salary") or 0)
    advance = float(p.get("total_advance") or 0)
    return {
        "id": p["id"], "full_name": p["full_name"], "department": p["department"],
        "salary": salary, "total_advance": advance, "remaining_salary": salary - advance,
        "annual_leave_total": p.get("annual_leave_total") or 0,
        "annual_leave_used": p.get("annual_leave_used") or 0,
        "annual_leave_remaining": p.get("annual_leave_remaining") or 0,
        "phone": p.get("phone") or "", "address": p.get("address") or "", "photo_url": p.get("photo_url") or "",
        "shift_name": p.get("shift_name") or "Sabah", "shift_start": p.get("shift_start") or "09:00", "shift_end": p.get("shift_end") or "18:00",
    }

def today_status_rows():
    today = today_str()
    people = q("select * from personnel where active=1 order by full_name", fetch=True)
    logs = q("select distinct on (person_id) person_id,event_type,event_time from attendance_logs where substring(event_time,1,10)=%s order by person_id,id desc", (today,), fetch=True)
    log_map = {r["person_id"]: r for r in logs}
    out = []
    for p in people:
        log = log_map.get(p["id"])
        if not log:
            out.append({"id": p["id"], "full_name": p["full_name"], "department": p["department"], "status": "Bekleniyor", "last_time": "", "warning": "", "shift": f"{p.get('shift_name') or 'Sabah'} {p.get('shift_start') or '09:00'}-{p.get('shift_end') or '18:00'}"})
        else:
            st = "İşte" if log["event_type"] == "entry" else "Çıkış yaptı"
            out.append({"id": p["id"], "full_name": p["full_name"], "department": p["department"], "status": st, "last_time": log["event_time"], "warning": warning_for_person(p["id"], log["event_type"], log["event_time"]), "shift": f"{p.get('shift_name') or 'Sabah'} {p.get('shift_start') or '09:00'}-{p.get('shift_end') or '18:00'}"})
    return out

def monthly_puantaj_rows(month=None):
    month, start, end = month_bounds(month)
    workdays = workdays_in_month(month)
    people = q("select * from personnel where active=1 order by full_name", fetch=True)
    rows = []
    for p in people:
        # Aylık vardiyada izinli/gün dışı işaretlenenleri çıkart
        custom = q("select day,is_work_day from monthly_shifts where person_id=%s and month=%s", (p["id"], month), fetch=True)
        custom_map = {c["day"]: int(c.get("is_work_day") or 0) for c in custom}
        person_workdays = [d for d in workdays if custom_map.get(d, 1) == 1]
        entries = q("select distinct substring(event_time,1,10) d from attendance_logs where person_id=%s and event_type='entry' and substring(event_time,1,7)=%s", (p["id"], month), fetch=True)
        came = set(r["d"] for r in entries)
        leaves = q("select start_date,end_date from leaves where person_id=%s and status='İzinli'", (p["id"],), fetch=True)
        leave_days = set()
        for lv in leaves:
            try:
                ds = datetime.strptime(lv["start_date"], "%Y-%m-%d").date()
                de = datetime.strptime(lv["end_date"], "%Y-%m-%d").date()
                d = ds
                while d <= de:
                    if d.strftime("%Y-%m") == month and d.isoformat() in person_workdays:
                        leave_days.add(d.isoformat())
                    d += timedelta(days=1)
            except Exception:
                pass
        absent = [d for d in person_workdays if d not in came and d not in leave_days]
        salary = float(p.get("salary") or 0)
        daily = salary / len(person_workdays) if person_workdays else 0
        deduction = daily * len(absent)
        rows.append({
            "id": p["id"], "full_name": p["full_name"], "department": p["department"],
            "shift_name": p.get("shift_name") or "Sabah", "shift_start": p.get("shift_start") or "09:00", "shift_end": p.get("shift_end") or "18:00",
            "workdays": len(person_workdays), "came_days": len(came), "leave_days": len(leave_days), "absent_days": len(absent),
            "absent_list": ", ".join(absent) if absent else "-", "salary": salary, "daily": daily,
            "deduction": deduction, "net_salary": salary - deduction,
        })
    return rows

def report_rows():
    month = now_dt().strftime("%Y-%m")
    return q("""select p.id,p.full_name,p.department,p.annual_leave_used,p.annual_leave_remaining,p.salary,
        coalesce(sum(a.amount),0) total_advance,
        (select count(distinct substring(event_time,1,10)) from attendance_logs al where al.person_id=p.id and al.event_type='entry' and substring(al.event_time,1,7)=%s) monthly_days,
        (select count(*) from attendance_logs al where al.person_id=p.id and al.event_type='entry' and substring(al.event_time,1,7)=%s and substring(al.event_time,12,8)>%s) late_entries,
        (select count(*) from attendance_logs al where al.person_id=p.id and al.event_type='exit' and substring(al.event_time,1,7)=%s and substring(al.event_time,12,8)<%s) early_exits
        from personnel p left join advances a on a.person_id=p.id group by p.id order by p.full_name""", (month, month, ENTRY_LIMIT, month, EXIT_LIMIT), fetch=True)

def make_pdf_response(filename, title, subtitle, headers, rows):
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), rightMargin=12*mm, leftMargin=12*mm, topMargin=10*mm, bottomMargin=10*mm)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="TRTitle", parent=styles["Title"], fontName=FONT_NAME, fontSize=18, leading=22))
    styles.add(ParagraphStyle(name="TRNormal", parent=styles["Normal"], fontName=FONT_NAME, fontSize=9, leading=12))
    story = [Paragraph(title, styles["TRTitle"]), Paragraph(subtitle, styles["TRNormal"]), Spacer(1, 8)]
    data = [headers] + rows
    table = Table(data, repeatRows=1)
    table.setStyle(TableStyle([
        ("FONTNAME", (0,0), (-1,-1), FONT_NAME),
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#0f2a4a")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.white),
        ("GRID", (0,0), (-1,-1), 0.35, colors.HexColor("#cbd5e1")),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#f1f5f9")]),
        ("FONTSIZE", (0,0), (-1,-1), 8),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
    ]))
    story.append(table)
    doc.build(story)
    pdf = buf.getvalue(); buf.close()
    return Response(pdf, mimetype="application/pdf", headers={"Content-Disposition": f"attachment; filename={filename}"})

# ---------------- ADMIN ROUTES ----------------
@app.route("/")
def home():
    return redirect("/admin/dashboard") if admin_ok() else redirect("/admin/login")

@app.route("/admin/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        u = request.form.get("username")
        pw = request.form.get("password")
        # Eski giriş de çalışsın, yeni giriş de çalışsın.
        if (u == ADMIN_USERNAME and pw == ADMIN_PASSWORD) or (u == "saban" and pw == "5109") or (u == "eren" and pw == "1234"):
            session["admin_ok"] = True
            return redirect("/admin/dashboard")
        flash("Hatalı kullanıcı adı veya şifre")
    return render_template("login.html", title="Giriş")

@app.route("/admin/logout")
def logout():
    session.clear()
    return redirect("/admin/login")

@app.route("/admin/dashboard")
@app.route("/admin")
def dashboard():
    guard = admin_required()
    if guard: return guard
    ts = today_status_rows()
    stats = q("select (select count(*) from personnel) personel,(select count(*) from advances) avans,(select count(*) from leaves) izin", fetch=True, one=True)
    stats["inside"] = sum(1 for r in ts if r["status"] == "İşte")
    stats["late"] = sum(1 for r in ts if r["warning"] == "Geç giriş")
    stats["early"] = sum(1 for r in ts if r["warning"] == "Erken çıkış")
    stats["clock"] = now_dt().strftime("%d.%m.%Y %H:%M:%S")
    return render_template("dashboard.html", title="Dashboard", stats=stats, today_status=ts)

@app.route("/admin/personnel", methods=["GET", "POST"])
def personnel():
    guard = admin_required()
    if guard: return guard
    if request.method == "POST":
        total = int(request.form.get("annual_leave_total") or 14)
        salary = float(request.form.get("salary") or 0)
        try:
            q("""insert into personnel(full_name,department,annual_leave_total,annual_leave_used,annual_leave_remaining,salary,active,username,password,token,phone,address,photo_url)
                 values(%s,%s,%s,0,%s,%s,1,%s,%s,%s,%s,%s,%s)""",
              (request.form["full_name"], request.form["department"], total, total, salary, request.form.get("username") or None, request.form.get("password") or None, secrets.token_hex(24), request.form.get("phone") or "", request.form.get("address") or "", request.form.get("photo_url") or ""))
            flash("Personel eklendi.")
        except Exception as e:
            flash("Personel eklenemedi. Kullanıcı adı aynı olabilir.")
    rows = q("select * from personnel order by id desc", fetch=True)
    return render_template("personnel.html", title="Personel", rows=rows)

@app.route("/admin/personnel/<int:pid>/edit", methods=["GET", "POST"])
def edit_person(pid):
    guard = admin_required()
    if guard: return guard
    p = q("select * from personnel where id=%s", (pid,), fetch=True, one=True)
    if not p:
        return redirect("/admin/personnel")
    if request.method == "POST":
        total = int(request.form.get("annual_leave_total") or 0)
        used = int(request.form.get("annual_leave_used") or 0)
        rem = max(total - used, 0)
        token = p.get("token") or secrets.token_hex(24)
        q("""update personnel set full_name=%s,department=%s,username=%s,password=%s,annual_leave_total=%s,annual_leave_used=%s,annual_leave_remaining=%s,salary=%s,active=%s,token=%s,phone=%s,address=%s,photo_url=%s,shift_name=%s,shift_start=%s,shift_end=%s where id=%s""",
          (request.form["full_name"], request.form["department"], request.form.get("username") or None, request.form.get("password") or None, total, used, rem, float(request.form.get("salary") or 0), int(request.form.get("active") or 1), token, request.form.get("phone") or "", request.form.get("address") or "", request.form.get("photo_url") or "", request.form.get("shift_name") or "Sabah", request.form.get("shift_start") or "09:00", request.form.get("shift_end") or "18:00", pid))
        flash("Personel güncellendi.")
        return redirect("/admin/personnel")
    return render_template("edit.html", title="Düzenle", p=p)

@app.route("/admin/personnel/<int:pid>/delete", methods=["POST"])
def delete_person(pid):
    guard = admin_required()
    if guard: return guard
    q("delete from personnel where id=%s", (pid,))
    flash("Personel silindi.")
    return redirect("/admin/personnel")

@app.route("/admin/personnel-cards")
def personnel_cards():
    guard = admin_required()
    if guard: return guard
    rows = q("select * from personnel where active=1 order by full_name", fetch=True)
    return render_template("personnel_cards.html", title="Kartvizitler", rows=rows)

@app.route("/admin/qr-cards")
def qr_cards():
    guard = admin_required()
    if guard: return guard
    return render_template("qr_cards.html", title="Tek QR", token=TERMINAL_QR_TOKEN)

@app.route("/admin/advances", methods=["GET", "POST"])
def advances():
    guard = admin_required()
    if guard: return guard
    if request.method == "POST":
        pid = int(request.form["person_id"]); amount = float(request.form["amount"] or 0); note = request.form.get("note") or ""
        q("insert into advances(person_id,amount,note,status) values(%s,%s,%s,'Beklemede')", (pid, amount, note))
        p = q("select full_name from personnel where id=%s", (pid,), fetch=True, one=True)
        notify("Yeni avans", f"{p['full_name']} için {amount:.2f} TL avans girildi.", pid)
        flash("Avans kaydedildi.")
    people = q("select * from personnel order by full_name", fetch=True)
    rows = q("select a.*,p.full_name from advances a join personnel p on p.id=a.person_id order by a.id desc limit 300", fetch=True)
    return render_template("advances.html", title="Avanslar", people=people, rows=rows)

@app.route("/admin/leaves", methods=["GET", "POST"])
def leaves():
    guard = admin_required()
    if guard: return guard
    if request.method == "POST":
        pid = int(request.form["person_id"]); start = request.form["start_date"]; end = request.form["end_date"]; count = days_between(start, end)
        p = q("select * from personnel where id=%s", (pid,), fetch=True, one=True)
        if p and int(p.get("annual_leave_remaining") or 0) >= count:
            q("insert into leaves(person_id,start_date,end_date,days_count,status) values(%s,%s,%s,%s,'İzinli')", (pid, start, end, count))
            q("update personnel set annual_leave_used=annual_leave_used+%s, annual_leave_remaining=annual_leave_remaining-%s where id=%s", (count, count, pid))
            notify("İzin onaylandı", f"{count} günlük iznin işlendi.", pid)
            flash("İzin kaydedildi.")
        else:
            flash("Yetersiz izin.")
    people = q("select * from personnel order by full_name", fetch=True)
    rows = q("select l.*,p.full_name from leaves l join personnel p on p.id=l.person_id order by l.id desc limit 300", fetch=True)
    return render_template("leaves.html", title="İzinler", people=people, rows=rows)

@app.route("/admin/leave-requests")
def leave_requests_page():
    guard = admin_required()
    if guard: return guard
    rows = q("select lr.*,p.full_name from leave_requests lr join personnel p on p.id=lr.person_id order by lr.id desc limit 300", fetch=True)
    return render_template("leave_requests.html", title="İzin Talepleri", rows=rows)

@app.route("/admin/leave-requests/<int:rid>/approve")
def approve_leave_request(rid):
    guard = admin_required()
    if guard: return guard
    req = q("select lr.*,p.full_name,p.annual_leave_remaining from leave_requests lr join personnel p on p.id=lr.person_id where lr.id=%s", (rid,), fetch=True, one=True)
    if not req:
        flash("Talep yok."); return redirect("/admin/leave-requests")
    if req["status"] == "Onaylandı":
        flash("Zaten onaylandı."); return redirect("/admin/leave-requests")
    if int(req["annual_leave_remaining"] or 0) < int(req["days_count"] or 0):
        flash("Yetersiz izin."); return redirect("/admin/leave-requests")
    q("insert into leaves(person_id,start_date,end_date,days_count,status) values(%s,%s,%s,%s,'İzinli')", (req["person_id"], req["start_date"], req["end_date"], req["days_count"]))
    q("update personnel set annual_leave_used=annual_leave_used+%s, annual_leave_remaining=annual_leave_remaining-%s where id=%s", (req["days_count"], req["days_count"], req["person_id"]))
    q("update leave_requests set status='Onaylandı' where id=%s", (rid,))
    notify("İzin onaylandı", f"{req['days_count']} günlük izin talebin onaylandı.", req["person_id"])
    flash("İzin onaylandı.")
    return redirect("/admin/leave-requests")

@app.route("/admin/salary")
def salary():
    guard = admin_required()
    if guard: return guard
    rows = q("select p.*,coalesce(sum(a.amount),0) total_advance from personnel p left join advances a on a.person_id=p.id group by p.id order by full_name", fetch=True)
    return render_template("salary.html", title="Maaşlar", rows=rows)

@app.route("/admin/salary-paid", methods=["POST"])
def salary_paid():
    guard = admin_required()
    if guard: return guard
    pid = int(request.form["person_id"]); amount = float(request.form.get("amount") or 0); month = request.form.get("month") or now_dt().strftime("%Y-%m")
    q("insert into salary_payments(person_id,amount,month,note,created_at) values(%s,%s,%s,%s,%s)", (pid, amount, month, request.form.get("note") or "Maaş yatırıldı", now_str()))
    notify("Maaş yatırıldı", f"{month} maaş ödemeniz yatırıldı. Tutar: {amount:.2f} TL", pid)
    flash("Maaş yatırıldı bildirimi gönderildi.")
    return redirect("/admin/salary")

@app.route("/admin/attendance")
def attendance():
    guard = admin_required()
    if guard: return guard
    selected = request.args.get("date") or today_str()
    rows = q("select a.*,p.full_name,p.department from attendance_logs a join personnel p on p.id=a.person_id where substring(a.event_time,1,10)=%s order by p.full_name,a.id desc", (selected,), fetch=True)
    people = q("select * from personnel where active=1 order by full_name", fetch=True)
    came_ids = set([r["person_id"] for r in rows if r["event_type"] == "entry"])
    missing = [p for p in people if p["id"] not in came_ids]
    return render_template("attendance.html", title="Giriş Çıkış", selected=selected, rows=rows, missing=missing)

@app.route("/admin/attendance/csv")
def attendance_csv():
    guard = admin_required()
    if guard: return guard
    selected = request.args.get("date") or today_str()
    rows = q("select a.*,p.full_name,p.department from attendance_logs a join personnel p on p.id=a.person_id where substring(a.event_time,1,10)=%s order by p.full_name,a.id", (selected,), fetch=True)
    out = StringIO()
    out.write("\ufeff")
    writer = csv.writer(out)
    writer.writerow(["Tarih", "Personel", "Bölüm", "Tip", "Saat", "Uyarı"])
    for r in rows:
        writer.writerow([selected, r["full_name"], r["department"], "Giriş" if r["event_type"] == "entry" else "Çıkış", r["event_time"], warning_for_person(r["person_id"], r["event_type"], r["event_time"])])
    return Response(out.getvalue(), mimetype="text/csv; charset=utf-8", headers={"Content-Disposition": f"attachment; filename=giris_cikis_{selected}.csv"})

@app.route("/admin/shifts", methods=["GET", "POST"])
def shifts():
    guard = admin_required()
    if guard: return guard
    month = request.args.get("month") or request.form.get("month") or now_dt().strftime("%Y-%m")
    if request.method == "POST":
        pid = int(request.form["person_id"])
        name = request.form.get("shift_name") or "Özel"
        st = request.form.get("shift_start") or "09:00"
        en = request.form.get("shift_end") or "18:00"
        days = request.form.getlist("days")
        if request.form.get("apply_default") == "1":
            q("update personnel set shift_name=%s,shift_start=%s,shift_end=%s where id=%s", (name, st, en, pid))
        if days:
            for day in days:
                q("delete from monthly_shifts where person_id=%s and day=%s", (pid, day))
                q("insert into monthly_shifts(person_id,month,day,shift_name,shift_start,shift_end,is_work_day) values(%s,%s,%s,%s,%s,%s,1)", (pid, month, day, name, st, en))
        flash("Vardiya kaydedildi.")
    _, start, end = month_bounds(month)
    days = []
    d = start
    while d <= end:
        days.append(d.isoformat())
        d += timedelta(days=1)
    people = q("select * from personnel where active=1 order by full_name", fetch=True)
    custom_rows = q("select ms.*,p.full_name,p.department from monthly_shifts ms join personnel p on p.id=ms.person_id where ms.month=%s order by ms.day,p.full_name", (month,), fetch=True)
    return render_template("shifts.html", title="Vardiyalar", month=month, people=people, days=days, custom_rows=custom_rows)

@app.route("/admin/shifts/pdf")
def shifts_pdf():
    guard = admin_required()
    if guard: return guard
    month = request.args.get("month") or now_dt().strftime("%Y-%m")
    rows = q("select p.full_name,p.department,coalesce(ms.day,'Genel') day,coalesce(ms.shift_name,p.shift_name) shift_name,coalesce(ms.shift_start,p.shift_start) shift_start,coalesce(ms.shift_end,p.shift_end) shift_end from personnel p left join monthly_shifts ms on ms.person_id=p.id and ms.month=%s where p.active=1 order by p.full_name,ms.day", (month,), fetch=True)
    data = [[r["full_name"], r["department"], r["day"] or "Genel", r["shift_name"] or "Sabah", f"{r['shift_start'] or '09:00'} - {r['shift_end'] or '18:00'}"] for r in rows]
    return make_pdf_response(f"vardiya_listesi_{month}.pdf", "Aylık Vardiya Listesi", f"Ay: {month} · Oluşturma: {now_str()}", ["Personel", "Bölüm", "Tarih", "Vardiya", "Saat"], data)

@app.route("/admin/monthly-puantaj")
def monthly_puantaj():
    guard = admin_required()
    if guard: return guard
    month = request.args.get("month") or now_dt().strftime("%Y-%m")
    rows = monthly_puantaj_rows(month)
    return render_template("monthly_puantaj.html", title="Ay Sonu Puantaj", month=month, rows=rows)

@app.route("/admin/monthly-puantaj/pdf")
def monthly_puantaj_pdf():
    guard = admin_required()
    if guard: return guard
    month = request.args.get("month") or now_dt().strftime("%Y-%m")
    rows = monthly_puantaj_rows(month)
    data = [[r["full_name"], r["department"], r["shift_name"], str(r["workdays"]), str(r["came_days"]), str(r["leave_days"]), str(r["absent_days"]), r["absent_list"], f"{r['deduction']:.2f} TL", f"{r['net_salary']:.2f} TL"] for r in rows]
    return make_pdf_response(f"ay_sonu_puantaj_{month}.pdf", "Ay Sonu Puantaj", f"Ay: {month} · Türkçe karakter uyumlu PDF", ["Personel", "Bölüm", "Vardiya", "İş Günü", "Geldi", "İzin", "Gelmedi", "Gelmeyen Tarihler", "Kesinti", "Net Maaş"], data)

@app.route("/admin/payroll/<int:pid>")
def payroll(pid):
    guard = admin_required()
    if guard: return guard
    month = request.args.get("month") or now_dt().strftime("%Y-%m")
    rows = monthly_puantaj_rows(month)
    r = next((x for x in rows if x["id"] == pid), None)
    if not r:
        flash("Personel bulunamadı."); return redirect("/admin/monthly-puantaj")
    data = [
        ["Personel", r["full_name"]], ["Bölüm", r["department"]], ["Ay", month], ["Vardiya", f"{r['shift_name']} {r['shift_start']}-{r['shift_end']}"],
        ["İş Günü", str(r["workdays"])], ["Geldiği Gün", str(r["came_days"])], ["İzinli Gün", str(r["leave_days"])],
        ["Gelmediği Gün", str(r["absent_days"])], ["Gelmeyen Tarihler", r["absent_list"]], ["Aylık Maaş", f"{r['salary']:.2f} TL"],
        ["Günlük Kesinti", f"{r['daily']:.2f} TL"], ["Toplam Kesinti", f"{r['deduction']:.2f} TL"], ["Net Maaş", f"{r['net_salary']:.2f} TL"],
    ]
    return make_pdf_response(f"bordro_{r['full_name'].replace(' ','_')}_{month}.pdf", "Personel Bordro", f"Oluşturma: {now_str()}", ["Alan", "Bilgi"], data)

@app.route("/admin/notifications")
def notifications_page():
    guard = admin_required()
    if guard: return guard
    rows = q("select n.*,p.full_name from notifications n left join personnel p on p.id=n.person_id order by n.id desc limit 300", fetch=True)
    return render_template("notifications.html", title="Bildirimler", rows=rows)

@app.route("/admin/reports")
def reports():
    guard = admin_required()
    if guard: return guard
    rows = report_rows()
    return render_template("reports.html", title="Aylık Rapor", rows=rows)

@app.route("/admin/reports/pdf")
def reports_pdf():
    guard = admin_required()
    if guard: return guard
    rows = report_rows()
    data = []
    for r in rows:
        salary = float(r.get("salary") or 0); advance = float(r.get("total_advance") or 0)
        data.append([r["full_name"], r["department"], str(r["monthly_days"]), str(r["late_entries"]), str(r["early_exits"]), f"{advance:.2f} TL", f"{salary-advance:.2f} TL"])
    return make_pdf_response("aylik_personel_raporu.pdf", "Aylık Personel Raporu", f"Tarih/Saat: {now_str()}", ["Personel", "Bölüm", "Gün", "Geç", "Erken", "Avans", "Kalan Maaş"], data)

# ---------------- API ----------------
@app.route("/api/health")
def health():
    q("select 1", fetch=True, one=True)
    return jsonify({"status": "ok", "database": "connected", "time": now_str()})

@app.route("/api/server-time")
def server_time():
    return jsonify({"status": "ok", "time": now_str(), "timezone": "Türkiye UTC+3"})

@app.route("/api/personnel")
def api_personnel():
    month = now_dt().strftime("%Y-%m")
    rows = q("""select p.id,p.full_name,p.department,p.annual_leave_remaining,p.salary,p.phone,p.address,p.photo_url,p.shift_name,p.shift_start,p.shift_end,
              coalesce(sum(a.amount),0) total_advance,
              (select count(distinct substring(event_time,1,10)) from attendance_logs al where al.person_id=p.id and al.event_type='entry' and substring(al.event_time,1,7)=%s) monthly_days
              from personnel p left join advances a on a.person_id=p.id where p.active=1 group by p.id order by p.full_name""", (month,), fetch=True)
    return jsonify([{**r, "salary": float(r.get("salary") or 0), "total_advance": float(r.get("total_advance") or 0)} for r in rows])

def record_attendance(pid):
    person = q("select * from personnel where id=%s and active=1", (pid,), fetch=True, one=True)
    if not person:
        return {"status": "error", "message": "Personel bulunamadı"}, 404
    last = q("select * from attendance_logs where person_id=%s order by id desc limit 1", (pid,), fetch=True, one=True)
    t = now_str()
    if last:
        try:
            last_dt = datetime.strptime(last["event_time"], "%Y-%m-%d %H:%M:%S")
            if (datetime.strptime(t, "%Y-%m-%d %H:%M:%S") - last_dt).total_seconds() < DOUBLE_SCAN_SECONDS:
                return {"status": "blocked", "message": "Çift okutma engellendi", "person_id": pid, "full_name": person["full_name"]}, 429
        except Exception:
            pass
    event_type = "entry"
    if last and last["event_type"] == "entry" and last["event_time"][:10] == t[:10]:
        event_type = "exit"
    q("insert into attendance_logs(person_id,event_type,event_time) values(%s,%s,%s)", (pid, event_type, t))
    warn = warning_for_person(pid, event_type, t)
    return {"status": "ok", "message": "Giriş kaydedildi" if event_type == "entry" else "Çıkış kaydedildi", "person_id": pid, "full_name": person["full_name"], "event_type": event_type, "event_time": t, "warning": warn}, 200

@app.route("/api/entry", methods=["GET", "POST"])
def api_entry():
    pid = val("person_id")
    if not pid:
        return jsonify({"status": "error", "message": "person_id eksik"}), 400
    t = now_str()
    q("insert into attendance_logs(person_id,event_type,event_time) values(%s,'entry',%s)", (pid, t))
    p = q("select full_name from personnel where id=%s", (pid,), fetch=True, one=True)
    return jsonify({"status": "ok", "full_name": p["full_name"] if p else "Personel", "event_type": "entry", "person_id": int(pid), "event_time": t, "warning": warning_for_person(int(pid), "entry", t)})

@app.route("/api/exit", methods=["GET", "POST"])
def api_exit():
    pid = val("person_id")
    if not pid:
        return jsonify({"status": "error", "message": "person_id eksik"}), 400
    t = now_str()
    q("insert into attendance_logs(person_id,event_type,event_time) values(%s,'exit',%s)", (pid, t))
    p = q("select full_name from personnel where id=%s", (pid,), fetch=True, one=True)
    return jsonify({"status": "ok", "full_name": p["full_name"] if p else "Personel", "event_type": "exit", "person_id": int(pid), "event_time": t, "warning": warning_for_person(int(pid), "exit", t)})

@app.route("/api/qr/verify", methods=["GET", "POST"])
def api_qr_verify():
    token = val("token") or val("qr") or val("data")
    person_token = val("person_token") or val("employee_token")
    person_id = val("person_id")
    # Tek QR modu: QR token sabit; personel uygulaması kendi tokenını veya person_id'sini gönderir.
    if token and token != TERMINAL_QR_TOKEN and not str(token).startswith("PERSONEL:"):
        return jsonify({"status": "error", "message": "QR kod eksik veya bozuk"}), 400
    if person_token:
        p = q("select id from personnel where token=%s and active=1", (person_token,), fetch=True, one=True)
        if not p:
            return jsonify({"status": "error", "message": "Personel girişi geçersiz"}), 401
        person_id = p["id"]
    elif token and str(token).startswith("PERSONEL:"):
        parts = str(token).split(":")
        if len(parts) >= 2:
            person_id = parts[1]
    if not person_id:
        return jsonify({"status": "error", "message": "Personel bilgisi eksik"}), 400
    data, code = record_attendance(int(person_id))
    return jsonify(data), code

@app.route("/api/my-qr")
def api_my_qr():
    return jsonify({"status": "ok", "qr_token": TERMINAL_QR_TOKEN, "mode": "single_terminal_qr"})

@app.route("/api/today-status")
def api_today_status():
    return jsonify(today_status_rows())

@app.route("/api/attendance")
def api_attendance():
    return jsonify(q("select a.id,a.person_id,p.full_name,a.event_type,a.event_time from attendance_logs a join personnel p on p.id=a.person_id order by a.id desc limit 100", fetch=True))

@app.route("/api/leaves", methods=["GET"])
def api_leaves():
    return jsonify(q("select l.id,l.person_id,p.full_name,l.start_date,l.end_date,l.days_count,l.status from leaves l join personnel p on p.id=l.person_id order by l.id desc limit 100", fetch=True))

@app.route("/api/leaves", methods=["POST"])
@app.route("/api/leave-add", methods=["GET", "POST"])
def api_leave_add():
    pid = int(val("person_id") or 0); start = val("start_date"); end = val("end_date")
    if not pid or not start or not end:
        return jsonify({"status": "error", "message": "eksik alan"}), 400
    count = days_between(start, end)
    p = q("select * from personnel where id=%s", (pid,), fetch=True, one=True)
    if not p:
        return jsonify({"status": "error", "message": "personel yok"}), 404
    if int(p.get("annual_leave_remaining") or 0) < count:
        return jsonify({"status": "error", "message": "yetersiz izin"}), 400
    q("insert into leaves(person_id,start_date,end_date,days_count,status) values(%s,%s,%s,%s,'İzinli')", (pid, start, end, count))
    q("update personnel set annual_leave_used=annual_leave_used+%s, annual_leave_remaining=annual_leave_remaining-%s where id=%s", (count, count, pid))
    notify("İzin onaylandı", f"{count} günlük iznin işlendi.", pid)
    return jsonify({"status": "ok", "person_id": pid, "days_count": count})

@app.route("/api/employee-login", methods=["GET", "POST"])
def employee_login():
    u = val("username"); pw = val("password")
    p = q("select * from personnel where username=%s and password=%s and active=1", (u, pw), fetch=True, one=True)
    if not p:
        return jsonify({"status": "error", "message": "Kullanıcı adı veya şifre hatalı"}), 401
    token = p.get("token") or secrets.token_hex(24)
    q("update personnel set token=%s where id=%s", (token, p["id"]))
    return jsonify({"status": "ok", "token": token, "person": person_summary(p["id"]), "terminal_qr": TERMINAL_QR_TOKEN})

@app.route("/api/employee-me", methods=["GET", "POST"])
def employee_me():
    token = val("token")
    p = q("select id from personnel where token=%s and active=1", (token,), fetch=True, one=True)
    if not p:
        return jsonify({"status": "error", "message": "geçersiz giriş"}), 401
    return jsonify({"status": "ok", "person": person_summary(p["id"])})

@app.route("/api/employee-profile-update", methods=["POST"])
def employee_profile_update():
    token = val("token")
    p = q("select id from personnel where token=%s and active=1", (token,), fetch=True, one=True)
    if not p:
        return jsonify({"status": "error", "message": "geçersiz giriş"}), 401
    q("update personnel set phone=%s,address=%s,photo_url=%s where id=%s", (val("phone", ""), val("address", ""), val("photo_url", ""), p["id"]))
    return jsonify({"status": "ok", "message": "Profil güncellendi", "person": person_summary(p["id"])})

@app.route("/api/employee-advances", methods=["GET", "POST"])
def employee_advances():
    token = val("token")
    p = q("select id from personnel where token=%s and active=1", (token,), fetch=True, one=True)
    if not p:
        return jsonify({"status": "error", "message": "geçersiz giriş"}), 401
    rows = q("select id,amount,note,status from advances where person_id=%s order by id desc limit 50", (p["id"],), fetch=True)
    return jsonify({"status": "ok", "advances": [{"id": r["id"], "amount": float(r["amount"] or 0), "note": r.get("note") or "", "status": r["status"]} for r in rows]})

@app.route("/api/employee-leave-request", methods=["GET", "POST"])
def employee_leave_request():
    token = val("token"); start = val("start_date"); end = val("end_date"); note = val("note", "")
    p = q("select id,full_name from personnel where token=%s and active=1", (token,), fetch=True, one=True)
    if not p:
        return jsonify({"status": "error", "message": "geçersiz giriş"}), 401
    if not start or not end:
        return jsonify({"status": "error", "message": "tarih eksik"}), 400
    count = days_between(start, end)
    q("insert into leave_requests(person_id,start_date,end_date,days_count,note,status,created_at) values(%s,%s,%s,%s,%s,'Beklemede',%s)", (p["id"], start, end, count, note, now_str()))
    notify("Yeni izin talebi", f"{p['full_name']} {count} günlük izin talebi gönderdi.", p["id"])
    return jsonify({"status": "ok", "message": "İzin talebi gönderildi", "days_count": count})

@app.route("/api/employee-notifications", methods=["GET", "POST"])
def employee_notifications():
    token = val("token")
    p = q("select id from personnel where token=%s and active=1", (token,), fetch=True, one=True)
    if not p:
        return jsonify({"status": "error", "message": "geçersiz giriş"}), 401
    rows = q("select id,event_type,message,created_at,is_read from notifications where person_id=%s order by id desc limit 50", (p["id"],), fetch=True)
    return jsonify({"status": "ok", "notifications": rows})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
