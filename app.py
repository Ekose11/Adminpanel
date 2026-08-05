from flask import Flask, render_template, request, redirect, session, flash, jsonify, Response, send_file, g, has_request_context
from datetime import datetime, date, timedelta
from urllib.parse import urlparse, unquote
from io import BytesIO, StringIO
import os, secrets, csv, json
from concurrent.futures import ThreadPoolExecutor
import pg8000
try:
    from pywebpush import webpush, WebPushException
except Exception:
    webpush = None
    WebPushException = Exception

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
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "BOZTEK")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "5109")
READY = False
PUSH_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="push")
LAST_NOTIFICATION_CLEANUP_DATE = None
ENTRY_LIMIT = "09:00:00"
EXIT_LIMIT = "18:00:00"
DOUBLE_SCAN_SECONDS = 10
TERMINAL_QR_TOKEN = os.environ.get("TERMINAL_QR_TOKEN", "PERSONEL-TEK-QR-GIRIS-CIKIS")
VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", "BHXwlsT6E8iQBx018lo4nw-G9Lg2YcjAGWh7iZ3bvZfOvgabxUoCe_nKqwltezPzfd93eB01webaLLRZDQWKWSQ")
VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", os.path.join(os.path.dirname(__file__), "vapid_private.pem"))
VAPID_CLAIMS = {"sub": os.environ.get("VAPID_SUBJECT", "mailto:admin@example.com")}

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

def _request_db():
    """Aynı HTTP isteğindeki tüm sorgularda tek Neon bağlantısını kullanır."""
    conn = getattr(g, "_db_conn", None)
    if conn is None:
        conn = db()
        g._db_conn = conn
    return conn

def q(sql, params=None, fetch=False, one=False):
    in_request = has_request_context()
    conn = _request_db() if in_request else db()
    cur = None
    try:
        cur = conn.cursor()
        cur.execute(sql, params or ())
        data = None
        if fetch:
            data = rows_to_dicts(cur, cur.fetchall())
            if one:
                data = data[0] if data else None
        conn.commit()
        return data
    except Exception:
        try: conn.rollback()
        except Exception: pass
        raise
    finally:
        if cur is not None:
            try: cur.close()
            except Exception: pass
        if not in_request:
            try: conn.close()
            except Exception: pass

@app.teardown_appcontext
def close_request_db(_error=None):
    conn = g.pop("_db_conn", None)
    if conn is not None:
        try: conn.close()
        except Exception: pass

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
    safe_alter("alter table advances add column created_at text default ''")
    try:
        q("update advances set created_at=%s where created_at is null or created_at=''", (now_str(),))
        q("create index if not exists idx_advances_person_created on advances(person_id,created_at)")
    except Exception:
        pass
    q("create table if not exists leaves(id serial primary key, person_id integer references personnel(id) on delete cascade, start_date text not null, end_date text not null, days_count integer default 0, status text default 'İzinli')")
    q("create table if not exists attendance_logs(id serial primary key, person_id integer references personnel(id) on delete cascade, event_type text not null, event_time text not null)")
    q("create table if not exists leave_requests(id serial primary key, person_id integer references personnel(id) on delete cascade, start_date text not null, end_date text not null, days_count integer default 0, note text default '', status text default 'Beklemede', created_at text not null)")
    q("create table if not exists notifications(id serial primary key, person_id integer references personnel(id) on delete cascade, event_type text not null, message text not null, created_at text not null, is_read integer default 0, audience text default 'personel', archived integer default 0)")
    q("""create table if not exists push_subscriptions(
        id serial primary key,
        endpoint text unique not null,
        p256dh text not null,
        auth text not null,
        audience text not null default 'personel',
        person_id integer references personnel(id) on delete cascade,
        created_at text not null,
        last_seen text not null
    )""")
    safe_alter("alter table notifications add column audience text default 'personel'")
    safe_alter("alter table notifications add column archived integer default 0")
    safe_alter("alter table notifications add column delivered_at text default ''")
    safe_alter("alter table notifications add column delivery_count integer default 0")
    try:
        q("create index if not exists idx_notifications_person_pending on notifications(person_id,audience,archived,delivered_at,id)")
        q("create index if not exists idx_notifications_admin_unread on notifications(audience,archived,is_read,id)")
        q("create index if not exists idx_leave_requests_status on leave_requests(status)")
        q("create index if not exists idx_advance_requests_status on advance_requests(status)")
        q("create index if not exists idx_attendance_logs_id on attendance_logs(id desc)")
        q("create index if not exists idx_attendance_logs_person_id on attendance_logs(person_id,id desc)")
        q("create index if not exists idx_push_subscriptions_audience on push_subscriptions(audience,person_id)")
        q("create index if not exists idx_personnel_token_active on personnel(token,active)")
        q("create index if not exists idx_personnel_username_active on personnel(username,active)")
        q("create index if not exists idx_notifications_person_read on notifications(person_id,audience,archived,is_read,id desc)")
    except Exception:
        pass
    q("create table if not exists advance_requests(id serial primary key, person_id integer references personnel(id) on delete cascade, amount numeric not null, note text default '', status text default 'Beklemede', created_at text not null, decided_at text default '')")
    try:
        q("create index if not exists idx_advance_requests_status on advance_requests(status)")
        q("create index if not exists idx_attendance_logs_id on attendance_logs(id desc)")
        q("create index if not exists idx_attendance_logs_person_id on attendance_logs(person_id,id desc)")
        q("create index if not exists idx_push_subscriptions_audience on push_subscriptions(audience,person_id)")
        q("create index if not exists idx_personnel_token_active on personnel(token,active)")
        q("create index if not exists idx_personnel_username_active on personnel(username,active)")
        q("create index if not exists idx_notifications_person_read on notifications(person_id,audience,archived,is_read,id desc)")
    except Exception:
        pass
    q("create table if not exists monthly_shifts(id serial primary key, person_id integer references personnel(id) on delete cascade, month text not null, day text not null, shift_name text not null, shift_start text not null, shift_end text not null, is_work_day integer default 1)")
    q("create table if not exists salary_payments(id serial primary key, person_id integer references personnel(id) on delete cascade, amount numeric default 0, month text default '', note text default '', created_at text default '')")
    # Eski Neon kurulumlarında salary_payments tablosu farklı sütunlarla kalmış olabilir.
    # Eksik sütunları veriyi silmeden tamamla.
    for col, typ in [
        ("person_id", "integer"),
        ("amount", "numeric default 0"),
        ("month", "text default ''"),
        ("note", "text default ''"),
        ("created_at", "text default ''"),
    ]:
        safe_alter(f"alter table salary_payments add column {col} {typ}")
    try:
        q("create index if not exists idx_salary_payments_person_month on salary_payments(person_id,month,id desc)")
    except Exception:
        pass
    q("""create table if not exists daily_bonuses(
        id serial primary key,
        person_id integer references personnel(id) on delete cascade,
        bonus_date text not null,
        amount numeric not null,
        note text default '',
        created_at text not null,
        unique(person_id, bonus_date)
    )""")
    try:
        q("create index if not exists idx_daily_bonuses_person_date on daily_bonuses(person_id,bonus_date desc)")
        q("create index if not exists idx_attendance_logs_event_time on attendance_logs(event_time)")
    except Exception:
        pass
    q("""create table if not exists attendance_adjustments(
        id serial primary key,
        person_id integer references personnel(id) on delete cascade,
        work_date text not null,
        status text not null,
        note text default '',
        created_at text not null,
        unique(person_id, work_date)
    )""")
    try:
        q("create index if not exists idx_attendance_adjustments_person_date on attendance_adjustments(person_id,work_date)")
    except Exception:
        pass
    READY = True

@app.after_request
def add_cache_headers(response):
    if request.path.startswith("/static/"):
        response.headers["Cache-Control"]="public, max-age=86400"
    elif request.path.startswith("/api/"):
        response.headers["Cache-Control"]="no-store"
    return response

@app.before_request
def before_request():
    # Şema kurulumu artık ilk kullanıcı isteğinde yapılmaz; uygulama açılırken tamamlanır.
    clear_old_notifications()

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

def _send_push_worker(event_type, message, person_id, audience, url='/'):
    if not webpush:
        return
    try:
        if audience == 'admin':
            rows = q("select id,endpoint,p256dh,auth from push_subscriptions where audience='admin'", fetch=True)
        else:
            rows = q("select id,endpoint,p256dh,auth from push_subscriptions where audience='personel' and person_id=%s", (person_id,), fetch=True)
        payload = json.dumps({"title": event_type, "body": message, "url": url, "tag": f"{audience}-{event_type}-{person_id or 0}-{int(datetime.utcnow().timestamp())}"}, ensure_ascii=False)
        for row in rows or []:
            try:
                webpush(subscription_info={"endpoint":row["endpoint"],"keys":{"p256dh":row["p256dh"],"auth":row["auth"]}}, data=payload, vapid_private_key=VAPID_PRIVATE_KEY, vapid_claims=VAPID_CLAIMS, ttl=86400, headers={"Urgency":"high"})
            except Exception as exc:
                status = getattr(getattr(exc, 'response', None), 'status_code', None)
                if status in (404, 410):
                    try: q("delete from push_subscriptions where id=%s", (row['id'],))
                    except Exception: pass
    except Exception:
        pass

def send_push(event_type, message, person_id=None, audience='personel', url='/'):
    # Sınırsız thread üretmek yerine küçük bir kuyruk kullanılır.
    PUSH_EXECUTOR.submit(_send_push_worker, event_type, message, person_id, audience, url)

def notify(event_type, message, person_id=None, audience='personel', push_url=None):
    q("insert into notifications(person_id,event_type,message,created_at,is_read,audience,archived) values(%s,%s,%s,%s,0,%s,0)", (person_id, event_type, message, now_str(), audience))
    send_push(event_type, message, person_id, audience, push_url or ('/admin/dashboard' if audience == 'admin' else '/personel/'))

def clear_old_notifications():
    # 30 günden eski bildirimleri silmek yerine arşivler.
    global LAST_NOTIFICATION_CLEANUP_DATE
    today = today_str()
    if LAST_NOTIFICATION_CLEANUP_DATE == today:
        return
    try:
        cutoff = (now_dt() - timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        q("update notifications set archived=1 where created_at<%s", (cutoff,))
        LAST_NOTIFICATION_CLEANUP_DATE = today
    except Exception:
        pass

@app.context_processor
def inject_badges():
    if not admin_ok():
        return {}
    try:
        counts = q("""select
            (select count(*) from leave_requests where status='Beklemede') leave_badge,
            (select count(*) from advance_requests where status='Beklemede') advance_badge,
            (select count(*) from notifications where audience='admin' and is_read=0 and archived=0) notification_badge
        """, fetch=True, one=True)
        return counts or {'leave_badge': 0, 'advance_badge': 0, 'notification_badge': 0}
    except Exception:
        return {'leave_badge': 0, 'advance_badge': 0, 'notification_badge': 0}

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



def days_in_month(month=None):
    month, start, end = month_bounds(month)
    days = []
    d = start
    while d <= end:
        days.append(d.isoformat())
        d += timedelta(days=1)
    return days

def shift_code(name):
    n = (name or '').lower()
    if 'akşam' in n or 'aksam' in n or n == 'b':
        return 'B'
    if 'gece' in n or n == 'c':
        return 'C'
    if 'izin' in n or 'off' in n or n == 'x':
        return 'X'
    return 'A'

def build_shift_matrix(month=None):
    month, start, end = month_bounds(month)
    days = days_in_month(month)
    people = q('select * from personnel where active=1 order by full_name', fetch=True)
    out = []
    totals = {'A':[0]*len(days), 'B':[0]*len(days), 'C':[0]*len(days), 'X':[0]*len(days)}
    for p in people:
        custom = q('select day,shift_name,shift_start,shift_end,is_work_day from monthly_shifts where person_id=%s and month=%s', (p['id'], month), fetch=True)
        cmap = {r['day']: r for r in custom}
        cells = []
        for i, day in enumerate(days):
            r = cmap.get(day)
            if r:
                if int(r.get('is_work_day') or 0) == 0:
                    code = 'X'; label = 'İzin'; st = ''; en = ''
                else:
                    code = shift_code(r.get('shift_name')); label = r.get('shift_name') or code; st = r.get('shift_start') or ''; en = r.get('shift_end') or ''
            else:
                code = shift_code(p.get('shift_name')); label = p.get('shift_name') or 'Sabah'; st = p.get('shift_start') or '09:00'; en = p.get('shift_end') or '18:00'
            totals.setdefault(code, [0]*len(days))[i] += 1
            cells.append({'day': day, 'code': code, 'label': label, 'start': st, 'end': en})
        out.append({'person': p, 'cells': cells})
    return month, days, out, totals

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
    month=now_dt().strftime("%Y-%m")
    p = q("""select p.*,
        coalesce((select sum(a.amount) from advances a where a.person_id=p.id and substring(coalesce(a.created_at,''),1,7)=%s and a.status in ('Onaylandı','Beklemede')),0) total_advance,
        coalesce((select sum(b.amount) from daily_bonuses b where b.person_id=p.id and substring(b.bonus_date,1,7)=%s),0) monthly_bonus
        from personnel p where p.id=%s""", (month, month, pid), fetch=True, one=True)
    if not p: return None
    days=workdays_in_month(month); today=today_str(); days=[d for d in days if d<=today]
    custom=q("select day,is_work_day from monthly_shifts where person_id=%s and month=%s",(pid,month),fetch=True)
    cmap={r['day']:int(r.get('is_work_day') or 0) for r in custom}; days=[d for d in days if cmap.get(d,1)==1]
    entries=q("select distinct substring(cast(event_time as text),1,10) d from attendance_logs where person_id=%s and event_type='entry' and substring(cast(event_time as text),1,7)=%s",(pid,month),fetch=True)
    came={r['d'] for r in entries}
    leave_days=set(); leaves=q("select start_date,end_date from leaves where person_id=%s and status='İzinli'",(pid,),fetch=True)
    for lv in leaves:
        try:
            d=datetime.strptime(lv['start_date'],'%Y-%m-%d').date(); de=datetime.strptime(lv['end_date'],'%Y-%m-%d').date()
            while d<=de:
                iso=d.isoformat()
                if iso in days: leave_days.add(iso)
                d+=timedelta(days=1)
        except Exception: pass
    absent=len([d for d in days if d not in came and d not in leave_days])
    salary=float(p.get('salary') or 0); daily=salary/30.0; deduction=daily*absent
    advance=float(p.get('total_advance') or 0); bonus=float(p.get('monthly_bonus') or 0); payable=max(0.0,salary-deduction-advance)
    return {
        "id":p["id"],"full_name":p["full_name"],"department":p["department"],"salary":salary,
        "total_advance":advance,"monthly_bonus":bonus,"absent_days":absent,"absence_deduction":deduction,
        "daily_salary":daily,"remaining_salary":payable,"payable_salary":payable,"salary_month":month,
        "annual_leave_total":p.get("annual_leave_total") or 0,"annual_leave_used":p.get("annual_leave_used") or 0,
        "annual_leave_remaining":p.get("annual_leave_remaining") or 0,"phone":p.get("phone") or "",
        "address":p.get("address") or "","photo_url":p.get("photo_url") or "",
        "shift_name":p.get("shift_name") or "Sabah","shift_start":p.get("shift_start") or "09:00","shift_end":p.get("shift_end") or "18:00",
    }

def today_status_rows():
    today = today_str()
    rows = q("""
        select p.id,p.full_name,p.department,p.shift_name,p.shift_start,p.shift_end,
               l.event_type,l.event_time
        from personnel p
        left join lateral (
            select event_type,event_time
            from attendance_logs a
            where a.person_id=p.id and a.event_time like %s
            order by a.id desc limit 1
        ) l on true
        where p.active=1
        order by p.full_name
    """, (today + '%',), fetch=True)
    out=[]
    for p in rows:
        if not p.get('event_type'):
            status='Bekleniyor'; warning=''; last_time=''
        else:
            status='İşte' if p['event_type']=='entry' else 'Çıkış yaptı'
            last_time=p.get('event_time') or ''
            t=time_part(last_time)
            start=((p.get('shift_start') or '09:00')+':00')
            end=((p.get('shift_end') or '18:00')+':00')
            warning='Geç giriş' if p['event_type']=='entry' and t>start else ('Erken çıkış' if p['event_type']=='exit' and t<end else '')
        out.append({
            'id':p['id'],'full_name':p['full_name'],'department':p['department'],
            'status':status,'last_time':last_time,'warning':warning,
            'shift':f"{p.get('shift_name') or 'Sabah'} {p.get('shift_start') or '09:00'}-{p.get('shift_end') or '18:00'}"
        })
    return out

def monthly_puantaj_rows(month=None):
    """Ay sonu puantaj + maaş: günlük ücret her zaman aylık maaş / 30."""
    month, start, end = month_bounds(month)
    base_days = workdays_in_month(month)
    today = now_dt().date()
    try:
        month_start = datetime.strptime(month + "-01", "%Y-%m-%d").date()
    except Exception:
        month_start = today.replace(day=1)
    # İçinde bulunulan ayda gelecekteki günleri devamsız sayma.
    if month_start.year == today.year and month_start.month == today.month:
        base_days = [d for d in base_days if d <= today.isoformat()]
    elif month_start > today:
        base_days = []

    people = q("select id,full_name,department,salary,shift_name,shift_start,shift_end from personnel where active=1 order by full_name", fetch=True)
    if not people:
        return []
    ids = [x["id"] for x in people]

    attendance = q("""select person_id,substring(cast(event_time as text),1,10) d
        from attendance_logs where event_type='entry' and substring(cast(event_time as text),1,7)=%s
        group by person_id,substring(event_time,1,10)""", (month,), fetch=True)
    came_map = {}
    for r in attendance:
        came_map.setdefault(r['person_id'], set()).add(r['d'])

    leaves = q("select person_id,start_date,end_date from leaves where status='İzinli'", fetch=True)
    leave_map = {pid:set() for pid in ids}
    for lv in leaves:
        if lv.get('person_id') not in leave_map: continue
        try:
            ds=datetime.strptime(lv['start_date'],'%Y-%m-%d').date(); de=datetime.strptime(lv['end_date'],'%Y-%m-%d').date()
            d=ds
            while d<=de:
                iso=d.isoformat()
                if d.strftime('%Y-%m')==month and iso in base_days: leave_map[lv['person_id']].add(iso)
                d += timedelta(days=1)
        except Exception: pass

    try:
        custom_rows = q("select person_id,cast(day as text) day,is_work_day from monthly_shifts where month=%s", (month,), fetch=True)
    except Exception:
        custom_rows = []
    custom_map = {}
    for c in custom_rows:
        custom_map.setdefault(c['person_id'], {})[str(c['day'])[:10]] = int(c.get('is_work_day') or 0)

    try:
        adjustment_rows = q("select person_id,work_date,status,note from attendance_adjustments where substring(work_date,1,7)=%s", (month,), fetch=True)
    except Exception:
        adjustment_rows = []
    adjustment_map = {}
    for a in adjustment_rows:
        adjustment_map.setdefault(a['person_id'], {})[str(a.get('work_date') or '')[:10]] = {
            'status': str(a.get('status') or '').lower(),
            'note': a.get('note') or ''
        }

    try:
        advances = q("""select person_id,coalesce(sum(amount),0) total from advances
            where substring(coalesce(cast(created_at as text),''),1,7)=%s and status in ('Onaylandı','Beklemede') group by person_id""", (month,), fetch=True)
    except Exception:
        # Eski advances tablosunda created_at yoksa tüm onaylı/bekleyen avansları göster.
        try:
            advances = q("select person_id,coalesce(sum(amount),0) total from advances where status in ('Onaylandı','Beklemede') group by person_id", fetch=True)
        except Exception:
            advances = []
    advance_map={r['person_id']:float(r.get('total') or 0) for r in advances}
    try:
        bonuses = q("select person_id,coalesce(sum(amount),0) total from daily_bonuses where substring(cast(bonus_date as text),1,7)=%s group by person_id", (month,), fetch=True)
    except Exception:
        bonuses = []
    bonus_map={r['person_id']:float(r.get('total') or 0) for r in bonuses}
    try:
        payments = q("select person_id,amount,cast(created_at as text) created_at from salary_payments where month=%s order by id desc", (month,), fetch=True)
    except Exception:
        payments = []
    payment_map={}
    for r in payments:
        payment_map.setdefault(r['person_id'], r)

    rows=[]
    for person in people:
        pid=person['id']
        person_days=[d for d in base_days if custom_map.get(pid,{}).get(d,1)==1]
        came=came_map.get(pid,set()); auto_leave_days=leave_map.get(pid,set())
        person_adjustments = adjustment_map.get(pid,{})
        half_days=[]; manual_absent=[]; manual_leave=[]; reported_days=[]
        for d, adj in person_adjustments.items():
            if d not in person_days:
                continue
            st=adj.get('status')
            if st=='half_day': half_days.append(d)
            elif st=='absent': manual_absent.append(d)
            elif st=='leave': manual_leave.append(d)
            elif st=='reported': reported_days.append(d)
        no_cut_days = set(auto_leave_days) | set(manual_leave) | set(reported_days)
        # Yarım gün işaretlenen tarih tam gün devamsızlığa girmez.
        absent=[d for d in person_days if d not in came and d not in no_cut_days and d not in half_days]
        # Yönetici tam gün gelmedi seçtiyse, giriş kaydı olsa bile tam gün kesilir.
        absent = sorted(set(absent) | set(manual_absent))
        half_days = sorted(set(half_days) - set(manual_absent))
        leave_days = sorted(set(auto_leave_days) | set(manual_leave))
        reported_days = sorted(set(reported_days))
        salary=float(person.get('salary') or 0); daily=salary/30.0
        full_day_deduction=daily*len(absent)
        half_day_deduction=(daily/2.0)*len(half_days)
        deduction=full_day_deduction+half_day_deduction
        advance=advance_map.get(pid,0.0); bonus=bonus_map.get(pid,0.0)
        payable=max(0.0, salary-deduction-advance)
        payment=payment_map.get(pid)
        rows.append({
            'id':pid,'full_name':person['full_name'],'department':person['department'],
            'shift_name':person.get('shift_name') or 'Sabah','shift_start':person.get('shift_start') or '09:00','shift_end':person.get('shift_end') or '18:00',
            'workdays':len(person_days),'came_days':len(came),'leave_days':len(leave_days),'reported_days':len(reported_days),
            'absent_days':len(absent),'half_days':len(half_days),
            'absent_list':', '.join(absent) if absent else '-',
            'half_day_list':', '.join(half_days) if half_days else '-',
            'reported_list':', '.join(reported_days) if reported_days else '-',
            'salary':salary,'daily':daily,'full_day_deduction':full_day_deduction,
            'half_day_deduction':half_day_deduction,'deduction':deduction,
            'total_advance':advance,'monthly_bonus':bonus,'net_salary':payable,'payable':payable,
            'paid':bool(payment),'paid_amount':float(payment.get('amount') or 0) if payment else 0.0,'paid_at':payment.get('created_at') if payment else ''
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
        if u == ADMIN_USERNAME and pw == ADMIN_PASSWORD:
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
    stats = {"personel": len(ts), "avans": 0, "izin": 0}
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
        q("insert into advances(person_id,amount,note,status,created_at) values(%s,%s,%s,'Beklemede',%s)", (pid, amount, note, now_str()))
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
    rows = q("select lr.*,p.full_name from leave_requests lr join personnel p on p.id=lr.person_id where lr.status='Beklemede' order by lr.id desc limit 300", fetch=True)
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
    notify("İzin onaylandı", f"{req['days_count']} günlük izin talebiniz onaylandı.", req["person_id"], 'personel')
    flash("İzin onaylandı.")
    return redirect("/admin/leave-requests")


@app.route("/admin/leave-requests/<int:rid>/reject", methods=["POST", "GET"])
def reject_leave_request(rid):
    guard = admin_required()
    if guard: return guard
    req = q("select lr.*,p.full_name from leave_requests lr join personnel p on p.id=lr.person_id where lr.id=%s", (rid,), fetch=True, one=True)
    if not req:
        flash("Talep bulunamadı."); return redirect("/admin/leave-requests")
    q("update leave_requests set status='Reddedildi' where id=%s", (rid,))
    notify("İzin reddedildi", f"{req['start_date']} - {req['end_date']} tarihli izin talebiniz reddedildi.", req["person_id"], 'personel')
    flash("İzin talebi reddedildi.")
    return redirect("/admin/leave-requests")


@app.route("/admin/advance-requests")
def advance_requests_page():
    guard = admin_required()
    if guard: return guard
    rows = q("select ar.*,p.full_name from advance_requests ar join personnel p on p.id=ar.person_id order by case when ar.status='Beklemede' then 0 else 1 end, ar.id desc limit 300", fetch=True)
    return render_template("advance_requests.html", title="Avans Talepleri", rows=rows)

@app.route("/admin/advance-requests/<int:rid>/<decision>", methods=["POST", "GET"])
def decide_advance_request(rid, decision):
    guard = admin_required()
    if guard: return guard
    req = q("select ar.*,p.full_name from advance_requests ar join personnel p on p.id=ar.person_id where ar.id=%s", (rid,), fetch=True, one=True)
    if not req or req['status'] != 'Beklemede':
        flash("Talep bulunamadı veya daha önce sonuçlandı."); return redirect("/admin/advance-requests")
    if decision == 'approve':
        q("update advance_requests set status='Onaylandı',decided_at=%s where id=%s", (now_str(), rid))
        q("insert into advances(person_id,amount,note,status,created_at) values(%s,%s,%s,'Onaylandı',%s)", (req['person_id'], req['amount'], req.get('note') or 'Personel avans talebi', now_str()))
        notify("Avans onaylandı", f"{float(req['amount']):.2f} TL avans talebiniz onaylandı.", req['person_id'], 'personel')
        flash("Avans talebi onaylandı ve avans geçmişine eklendi.")
    else:
        q("update advance_requests set status='Reddedildi',decided_at=%s where id=%s", (now_str(), rid))
        notify("Avans reddedildi", f"{float(req['amount']):.2f} TL avans talebiniz reddedildi.", req['person_id'], 'personel')
        flash("Avans talebi reddedildi.")
    return redirect("/admin/advance-requests")

@app.route("/api/admin/live-status")
def admin_live_status():
    guard = admin_required()
    if guard: return jsonify({'status':'unauthorized'}), 401
    data = q("""select
        (select count(*) from leave_requests where status='Beklemede') leave_count,
        (select count(*) from advance_requests where status='Beklemede') advance_count,
        (select count(*) from notifications where audience='admin' and is_read=0 and archived=0) notification_count,
        (select id from notifications where audience='admin' and archived=0 order by id desc limit 1) latest_id,
        (select event_type from notifications where audience='admin' and archived=0 order by id desc limit 1) latest_type,
        (select message from notifications where audience='admin' and archived=0 order by id desc limit 1) latest_message
    """, fetch=True, one=True) or {}
    latest = None
    if data.get('latest_id'):
        latest = {'id': data['latest_id'], 'event_type': data.get('latest_type'), 'message': data.get('latest_message')}
    return jsonify({'status':'ok','leave_count':data.get('leave_count',0),'advance_count':data.get('advance_count',0),'notification_count':data.get('notification_count',0),'latest':latest})

@app.route("/api/employee-notifications/read", methods=["POST"])
def employee_notifications_read():
    token = val('token')
    p = q("select id from personnel where token=%s and active=1", (token,), fetch=True, one=True)
    if not p: return jsonify({'status':'error','message':'geçersiz giriş'}),401
    q("update notifications set is_read=1 where person_id=%s and audience='personel' and archived=0", (p['id'],))
    return jsonify({'status':'ok'})

@app.route("/admin/bonuses", methods=["GET", "POST"])
def bonuses():
    guard = admin_required()
    if guard: return guard
    month = request.args.get("month") or now_dt().strftime("%Y-%m")
    if request.method == "POST":
        pid=int(request.form.get("person_id") or 0)
        bdate=request.form.get("bonus_date") or today_str()
        try: amount=float(request.form.get("amount") or 0)
        except Exception: amount=0
        note=request.form.get("note") or ""
        if not pid or amount<=0:
            flash("Personel ve geçerli prim tutarı girin.")
        else:
            q("""insert into daily_bonuses(person_id,bonus_date,amount,note,created_at)
                 values(%s,%s,%s,%s,%s)
                 on conflict(person_id,bonus_date) do update set amount=excluded.amount,note=excluded.note,created_at=excluded.created_at""",
              (pid,bdate,amount,note,now_str()))
            person=q("select full_name from personnel where id=%s",(pid,),fetch=True,one=True)
            notify("Günlük prim", f"{bdate} tarihli {amount:.2f} TL priminiz eklendi.", pid, 'personel')
            flash(f"{person['full_name'] if person else 'Personel'} için prim kaydedildi.")
        return redirect(f"/admin/bonuses?month={bdate[:7]}")
    people=q("select id,full_name,department from personnel where active=1 order by full_name",fetch=True)
    rows=q("""select b.*,p.full_name,p.department,
        sum(b.amount) over(partition by b.person_id,substring(b.bonus_date,1,7)) month_total
        from daily_bonuses b join personnel p on p.id=b.person_id
        where substring(b.bonus_date,1,7)=%s order by b.bonus_date desc,b.id desc limit 500""",(month,),fetch=True)
    totals=q("""select p.id,p.full_name,p.department,coalesce(sum(b.amount),0) total
        from personnel p left join daily_bonuses b on b.person_id=p.id and substring(b.bonus_date,1,7)=%s
        where p.active=1 group by p.id order by p.full_name""",(month,),fetch=True)
    return render_template("bonuses.html", title="Günlük Prim", people=people, rows=rows, totals=totals, month=month, today=today_str())

@app.route("/admin/bonuses/<int:bid>/delete", methods=["POST"])
def delete_bonus(bid):
    guard=admin_required()
    if guard:return guard
    q("delete from daily_bonuses where id=%s",(bid,))
    flash("Prim kaydı silindi.")
    return redirect(request.referrer or "/admin/bonuses")

@app.route("/api/employee-bonuses")
def employee_bonuses():
    token=val("token")
    p=q("select id from personnel where token=%s and active=1",(token,),fetch=True,one=True)
    if not p:return jsonify({"status":"error","message":"geçersiz giriş"}),401
    month=val("month", now_dt().strftime("%Y-%m"))
    rows=q("select id,bonus_date,amount,note,created_at from daily_bonuses where person_id=%s and substring(cast(bonus_date as text),1,7)=%s order by bonus_date desc,id desc",(p['id'],month),fetch=True)
    total=sum(float(r.get('amount') or 0) for r in rows)
    return jsonify({"status":"ok","month":month,"total":total,"bonuses":[{**r,"amount":float(r.get('amount') or 0)} for r in rows]})

@app.route("/admin/salary")
def salary():
    guard = admin_required()
    if guard: return guard
    return redirect("/admin/monthly-puantaj")

@app.route("/admin/salary-paid", methods=["POST"])
def salary_paid():
    guard = admin_required()
    if guard:
        return guard

    month = (request.form.get("month") or now_dt().strftime("%Y-%m")).strip()
    try:
        pid = int(request.form.get("person_id") or 0)
        raw_amount = str(request.form.get("amount") or "0").strip().replace(",", ".")
        amount = round(float(raw_amount), 2)
        if pid <= 0 or amount < 0:
            raise ValueError("Geçersiz personel veya tutar")
        # Hatalı/uydurma personel kimliği ile kayıt oluşmasını engelle.
        person = q("select id,full_name from personnel where id=%s and active=1", (pid,), fetch=True, one=True)
        if not person:
            raise ValueError("Personel bulunamadı")

        # Eski veritabanlarında eksik kalmış ödeme sütunlarını çalışma anında da tamamla.
        for col, typ in [
            ("person_id", "integer"), ("amount", "numeric default 0"),
            ("month", "text default ''"), ("note", "text default ''"),
            ("created_at", "text default ''")
        ]:
            safe_alter(f"alter table salary_payments add column {col} {typ}")

        existing = q("select id from salary_payments where person_id=%s and cast(month as text)=%s order by id desc limit 1", (pid, month), fetch=True, one=True)
        note = request.form.get("note") or "Maaş yatırıldı"
        if existing:
            q("update salary_payments set amount=%s,month=%s,note=%s,created_at=%s where id=%s", (amount, month, note, now_str(), existing["id"]))
        else:
            q("insert into salary_payments(person_id,amount,month,note,created_at) values(%s,%s,%s,%s,%s)", (pid, amount, month, note, now_str()))

        # Bildirim tablosu eskiyse ödeme kaydını başarısız sayma; bildirim ayrı denenir.
        notification_sent = True
        try:
            notify("Maaş yatırıldı", f"{month} maaş ödemeniz yatırıldı. Tutar: {amount:.2f} TL", pid)
        except Exception as notify_error:
            notification_sent = False
            app.logger.exception("Maaş bildirimi gönderilemedi: %s", notify_error)

        if notification_sent:
            flash(f"{person['full_name']} için {amount:.2f} TL maaş ödendi olarak işaretlendi ve bildirim gönderildi.")
        else:
            flash(f"{person['full_name']} için {amount:.2f} TL maaş ödendi olarak işaretlendi; bildirim daha sonra tekrar denenebilir.")
    except (ValueError, TypeError) as exc:
        flash(f"Maaş kaydı yapılamadı: {exc}")
    except Exception as exc:
        app.logger.exception("Maaş ödendi işlemi hatası: %s", exc)
        flash("Maaş kaydı sırasında veritabanı hatası oluştu. Ödeme kaydı oluşturulamadı.")

    return redirect(f"/admin/monthly-puantaj?month={month}")

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
        mode = request.form.get("mode") or "days"
        pid = int(request.form.get("person_id") or 0)
        name = request.form.get("shift_name") or "Sabah"
        st = request.form.get("shift_start") or "09:00"
        en = request.form.get("shift_end") or "18:00"
        _, start_day, end_day = month_bounds(month)
        if request.form.get("apply_default") == "1":
            q("update personnel set shift_name=%s,shift_start=%s,shift_end=%s where id=%s", (name, st, en, pid))
        if mode == "pattern":
            pattern = (request.form.get("pattern") or "").replace(" ", "").upper()
            if not pattern:
                flash("Şablon boş olamaz. Örnek: AAAXBBX")
                return redirect("/admin/shifts?month=" + month)
            d = start_day; i = 0
            while d <= end_day:
                code = pattern[i % len(pattern)]
                if code in ["X", "O", "-"]:
                    sname, ss, se, work = "İzin", "", "", 0
                elif code == "B":
                    sname, ss, se, work = "Akşam", "16:00", "00:00", 1
                elif code == "C":
                    sname, ss, se, work = "Gece", "00:00", "08:00", 1
                else:
                    sname, ss, se, work = "Sabah", "08:00", "16:00", 1
                day = d.isoformat()
                q("delete from monthly_shifts where person_id=%s and day=%s", (pid, day))
                q("insert into monthly_shifts(person_id,month,day,shift_name,shift_start,shift_end,is_work_day) values(%s,%s,%s,%s,%s,%s,%s)", (pid, month, day, sname, ss, se, work))
                d += timedelta(days=1); i += 1
            flash("Aylık şablon uygulandı.")
        else:
            days = request.form.getlist("days")
            work = 0 if name in ["İzin", "Off", "X"] else 1
            if days:
                for day in days:
                    q("delete from monthly_shifts where person_id=%s and day=%s", (pid, day))
                    q("insert into monthly_shifts(person_id,month,day,shift_name,shift_start,shift_end,is_work_day) values(%s,%s,%s,%s,%s,%s,%s)", (pid, month, day, name, st, en, work))
                flash("Seçili günlere vardiya kaydedildi.")
    month, days, matrix, totals = build_shift_matrix(month)
    people = q("select * from personnel where active=1 order by full_name", fetch=True)
    return render_template("shifts.html", title="Aylık Vardiya", month=month, people=people, days=days, matrix=matrix, totals=totals)

@app.route("/admin/shifts/pdf")
def shifts_pdf():
    guard = admin_required()
    if guard: return guard
    month = request.args.get("month") or now_dt().strftime("%Y-%m")
    month, days, matrix, totals = build_shift_matrix(month)
    headers = ["Personel"] + [d[-2:] for d in days]
    data = []
    for r in matrix:
        data.append([r["person"]["full_name"]] + [c["code"] for c in r["cells"]])
    return make_pdf_response(f"vardiya_rotasyon_{month}.pdf", "Aylık Rotasyon Vardiya Listesi", f"Ay: {month} · A=Sabah, B=Akşam, C=Gece, X=İzin", headers, data)

@app.route("/api/employee-shifts")
def api_employee_shifts():
    token = val("token")
    month = val("month") or now_dt().strftime("%Y-%m")
    p = q("select * from personnel where token=%s and active=1", (token,), fetch=True, one=True)
    if not p:
        return jsonify({"status": "error", "message": "geçersiz giriş"}), 401
    month, days, _, _ = build_shift_matrix(month)
    custom = q("select day,shift_name,shift_start,shift_end,is_work_day from monthly_shifts where person_id=%s and month=%s", (p["id"], month), fetch=True)
    cmap = {r["day"]: r for r in custom}
    items = []
    for day in days:
        r = cmap.get(day)
        if r:
            code = "X" if int(r.get("is_work_day") or 0) == 0 else shift_code(r.get("shift_name"))
            items.append({"day": day, "code": code, "shift_name": r.get("shift_name") or "İzin", "shift_start": r.get("shift_start") or "", "shift_end": r.get("shift_end") or "", "is_work_day": int(r.get("is_work_day") or 0)})
        else:
            items.append({"day": day, "code": shift_code(p.get("shift_name")), "shift_name": p.get("shift_name") or "Sabah", "shift_start": p.get("shift_start") or "09:00", "shift_end": p.get("shift_end") or "18:00", "is_work_day": 1})
    return jsonify({"status":"ok", "month": month, "person": person_summary(p["id"]), "shifts": items})

@app.route("/admin/attendance-adjustment", methods=["POST"])
def attendance_adjustment():
    guard = admin_required()
    if guard: return guard
    person_id = request.form.get("person_id", type=int)
    work_date = (request.form.get("work_date") or "").strip()
    status = (request.form.get("status") or "").strip().lower()
    note = (request.form.get("note") or "").strip()
    month = (request.form.get("month") or now_dt().strftime("%Y-%m")).strip()
    allowed = {"half_day", "absent", "leave", "reported", "clear"}
    if not person_id or status not in allowed:
        flash("Personel veya durum geçersiz.")
        return redirect(f"/admin/monthly-puantaj?month={month}")
    try:
        datetime.strptime(work_date, "%Y-%m-%d")
    except Exception:
        flash("Geçerli bir tarih seçmelisiniz.")
        return redirect(f"/admin/monthly-puantaj?month={month}")
    if status == "clear":
        q("delete from attendance_adjustments where person_id=%s and work_date=%s", (person_id, work_date))
        flash("Özel puantaj kaydı kaldırıldı; otomatik hesaplama kullanılacak.")
    else:
        q("""insert into attendance_adjustments(person_id,work_date,status,note,created_at)
             values(%s,%s,%s,%s,%s)
             on conflict(person_id,work_date) do update set status=excluded.status,note=excluded.note,created_at=excluded.created_at""",
          (person_id, work_date, status, note, now_str()))
        labels={"half_day":"Yarım gün","absent":"Tam gün gelmedi","leave":"İzinli","reported":"Raporlu"}
        flash(f"Puantaj kaydedildi: {labels.get(status,status)}.")
    return redirect(f"/admin/monthly-puantaj?month={month}")

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
    data = [[r["full_name"], r["department"], str(r["came_days"]), str(r["leave_days"]), str(r["reported_days"]), str(r["half_days"]), str(r["absent_days"]), f"{r['salary']:.2f} TL", f"{r['deduction']:.2f} TL", f"{r['total_advance']:.2f} TL", f"{r['payable']:.2f} TL", "Ödendi" if r['paid'] else "Bekliyor"] for r in rows]
    return make_pdf_response(f"ay_sonu_maas_{month}.pdf", "Ay Sonu Puantaj ve Maaş", f"Ay: {month} · Tam gün 1 günlük, yarım gün 0,5 günlük kesinti", ["Personel", "Bölüm", "Geldi", "İzin", "Rapor", "Yarım", "Gelmedi", "Maaş", "Kesinti", "Avans", "Yatırılacak", "Durum"], data)

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
        ["Hesaplama Esası", "Aylık maaş / 30"], ["Geldiği Gün", str(r["came_days"])], ["İzinli Gün", str(r["leave_days"])], ["Raporlu Gün", str(r["reported_days"])],
        ["Tam Gün Gelmedi", str(r["absent_days"])], ["Gelmeyen Tarihler", r["absent_list"]],
        ["Yarım Gün", str(r["half_days"])], ["Yarım Gün Tarihleri", r["half_day_list"]], ["Aylık Maaş", f"{r['salary']:.2f} TL"],
        ["Günlük Ücret", f"{r['daily']:.2f} TL"], ["Tam Gün Kesintisi", f"{r['full_day_deduction']:.2f} TL"],
        ["Yarım Gün Kesintisi", f"{r['half_day_deduction']:.2f} TL"], ["Toplam Devamsızlık Kesintisi", f"{r['deduction']:.2f} TL"],
        ["Avans", f"{r['total_advance']:.2f} TL"], ["Yatırılacak", f"{r['payable']:.2f} TL"], ["Durum", "Ödendi" if r["paid"] else "Bekliyor"],
    ]
    return make_pdf_response(f"bordro_{r['full_name'].replace(' ','_')}_{month}.pdf", "Personel Bordro", f"Oluşturma: {now_str()}", ["Alan", "Bilgi"], data)

@app.route("/admin/notifications")
def notifications_page():
    guard = admin_required()
    if guard: return guard
    rows = q("select n.*,p.full_name from notifications n left join personnel p on p.id=n.person_id where n.audience='admin' and n.archived=0 order by n.id desc limit 300", fetch=True)
    q("update notifications set is_read=1 where audience='admin' and archived=0")
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
    action_text = "giriş yaptı" if event_type == "entry" else "çıkış yaptı"
    notify("Personel Giriş/Çıkış", f"{person['full_name']} {t[11:16]} saatinde {action_text}.", pid, "admin", "/admin/dashboard")
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
    if p: notify("Personel Giriş", f"{p['full_name']} {t[11:16]} saatinde giriş yaptı.", int(pid), "admin", "/admin/dashboard")
    return jsonify({"status": "ok", "full_name": p["full_name"] if p else "Personel", "event_type": "entry", "person_id": int(pid), "event_time": t, "warning": warning_for_person(int(pid), "entry", t)})

@app.route("/api/exit", methods=["GET", "POST"])
def api_exit():
    pid = val("person_id")
    if not pid:
        return jsonify({"status": "error", "message": "person_id eksik"}), 400
    t = now_str()
    q("insert into attendance_logs(person_id,event_type,event_time) values(%s,'exit',%s)", (pid, t))
    p = q("select full_name from personnel where id=%s", (pid,), fetch=True, one=True)
    if p: notify("Personel Çıkış", f"{p['full_name']} {t[11:16]} saatinde çıkış yaptı.", int(pid), "admin", "/admin/dashboard")
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

@app.route("/api/push/public-key")
def push_public_key():
    return jsonify({"status":"ok", "public_key":VAPID_PUBLIC_KEY})

@app.route("/api/push/subscribe", methods=["POST"])
def push_subscribe():
    data = request.get_json(silent=True) or {}
    sub = data.get("subscription") or data
    endpoint = sub.get("endpoint")
    keys = sub.get("keys") or {}
    audience = data.get("audience") or "personel"
    person_id = None
    if audience == "admin":
        if not admin_ok(): return jsonify({"status":"error","message":"Yetkisiz"}), 401
    else:
        token = data.get("token") or val("token")
        person = q("select id from personnel where token=%s and active=1", (token,), fetch=True, one=True)
        if not person: return jsonify({"status":"error","message":"Personel oturumu geçersiz"}), 401
        person_id = person["id"]
    if not endpoint or not keys.get("p256dh") or not keys.get("auth"):
        return jsonify({"status":"error","message":"Bildirim aboneliği eksik"}), 400
    q("""insert into push_subscriptions(endpoint,p256dh,auth,audience,person_id,created_at,last_seen)
         values(%s,%s,%s,%s,%s,%s,%s)
         on conflict(endpoint) do update set p256dh=excluded.p256dh,auth=excluded.auth,audience=excluded.audience,person_id=excluded.person_id,last_seen=excluded.last_seen""",
      (endpoint,keys["p256dh"],keys["auth"],audience,person_id,now_str(),now_str()))
    return jsonify({"status":"ok","message":"Kapalıyken bildirim etkinleştirildi"})

@app.route("/api/admin/live-feed")
def admin_live_feed():
    guard = admin_required()
    if guard: return jsonify({"status":"error"}), 401
    after = int(request.args.get("after_id") or 0)
    rows = q("""select a.id,a.event_type,a.event_time,p.full_name,p.department
                from attendance_logs a join personnel p on p.id=a.person_id
                where a.id>%s order by a.id asc limit 20""", (after,), fetch=True)
    latest_id = rows[-1]["id"] if rows else after
    return jsonify({"status":"ok","events":rows,"latest_id":latest_id})

@app.route("/api/admin/dashboard-summary")
def admin_dashboard_summary():
    guard = admin_required()
    if guard: return jsonify({"status":"error"}), 401
    ts = today_status_rows()
    return jsonify({"status":"ok","personel":len(ts),"inside":sum(1 for r in ts if r["status"]=="İşte"),"late":sum(1 for r in ts if r["warning"]=="Geç giriş"),"early":sum(1 for r in ts if r["warning"]=="Erken çıkış")})

@app.route("/admin-push-sw.js")
def admin_push_sw():
    return app.send_static_file("admin-push-sw.js"), 200, {"Content-Type":"application/javascript","Service-Worker-Allowed":"/"}

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
    notify("Yeni izin talebi", f"{p['full_name']} {count} günlük izin talebi gönderdi.", p["id"], 'admin')
    return jsonify({"status": "ok", "message": "İzin talebi gönderildi", "days_count": count})

@app.route("/api/employee-advance-request", methods=["POST"])
def employee_advance_request():
    token = val("token")
    p = q("select id,full_name from personnel where token=%s and active=1", (token,), fetch=True, one=True)
    if not p:
        return jsonify({"status":"error","message":"geçersiz giriş"}), 401
    try:
        amount = float(val("amount", 0) or 0)
    except Exception:
        amount = 0
    note = val("note", "")
    if amount <= 0:
        return jsonify({"status":"error","message":"Geçerli bir tutar girin."}), 400
    q("insert into advance_requests(person_id,amount,note,status,created_at) values(%s,%s,%s,'Beklemede',%s)", (p["id"], amount, note, now_str()))
    notify("Yeni avans talebi", f"{p['full_name']} {amount:.2f} TL avans talebi gönderdi.", p["id"], 'admin')
    return jsonify({"status":"ok","message":"Avans talebiniz gönderildi."})

@app.route("/api/employee-advance-requests")
def employee_advance_requests():
    token = val("token")
    p = q("select id from personnel where token=%s and active=1", (token,), fetch=True, one=True)
    if not p:
        return jsonify({"status":"error","message":"geçersiz giriş"}), 401
    rows = q("select id,amount,note,status,created_at,decided_at from advance_requests where person_id=%s order by id desc limit 50", (p["id"],), fetch=True)
    return jsonify({"status":"ok","requests":[{**r,"amount":float(r.get('amount') or 0)} for r in rows]})


@app.route("/api/employee-notifications/pending")
def employee_notifications_pending():
    """Yeni bildirimleri bir kez teslim eder. Aynı kayıt sonraki kontrolde dönmez."""
    token = val("token")
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute("select id from personnel where token=%s and active=1", (token,))
        person = cur.fetchone()
        if not person:
            conn.rollback()
            return jsonify({"status":"error","message":"geçersiz giriş"}), 401
        person_id = person[0]
        cur.execute("""select id,event_type,message,created_at from notifications
            where person_id=%s and audience='personel' and archived=0
              and coalesce(delivered_at,'')=''
            order by id asc limit 20 for update skip locked""", (person_id,))
        raw = cur.fetchall()
        rows = [{"id":r[0],"event_type":r[1],"message":r[2],"created_at":r[3]} for r in raw]
        if rows:
            ids = [r["id"] for r in rows]
            placeholders = ','.join(['%s'] * len(ids))
            cur.execute(f"update notifications set delivered_at=%s,delivery_count=coalesce(delivery_count,0)+1 where id in ({placeholders})", (now_str(), *ids))
        conn.commit()
        return jsonify({"status":"ok","notifications":rows})
    except Exception:
        conn.rollback()
        raise
    finally:
        try: cur.close()
        except Exception: pass
        conn.close()

@app.route("/api/employee-notifications", methods=["GET", "POST"])
def employee_notifications():
    token = val("token")
    p = q("select id from personnel where token=%s and active=1", (token,), fetch=True, one=True)
    if not p:
        return jsonify({"status": "error", "message": "geçersiz giriş"}), 401
    rows = q("select id,event_type,message,created_at,is_read from notifications where person_id=%s and audience='personel' and archived=0 order by id desc limit 50", (p["id"],), fetch=True)
    return jsonify({"status": "ok", "notifications": rows})

# ---------------- PERSONEL PWA / iOS SAFARI ----------------
@app.route("/personel")
@app.route("/personel/")
@app.route("/personel/login")
def personel_pwa():
    return render_template("personel_pwa.html")

@app.route("/manifest.json")
@app.route("/personel/manifest.webmanifest")
def pwa_manifest():
    return send_file("static/personel-pwa/manifest.webmanifest", mimetype="application/manifest+json")

@app.route("/sw.js")
@app.route("/personel/service-worker.js")
def pwa_service_worker():
    response = send_file("static/personel-pwa/service-worker.js", mimetype="application/javascript")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["Service-Worker-Allowed"] = "/"
    return response


# Veritabanı şemasını ilk ziyaretçiyi bekletmeden Gunicorn açılışında hazırla.
try:
    init_db()
except Exception as exc:
    print("DB başlangıç uyarısı:", exc, flush=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
