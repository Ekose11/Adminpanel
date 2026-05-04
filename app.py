from flask import Flask, render_template, request, redirect, session, flash, jsonify
from datetime import datetime
from urllib.parse import urlparse, unquote
import os, secrets, pg8000

app=Flask(__name__)
app.secret_key=os.environ.get("SECRET_KEY","boztek-pro-secret")
DATABASE_URL=os.environ.get("DATABASE_URL")
SUPER_USERNAME=os.environ.get("SUPER_USERNAME","saban")
SUPER_PASSWORD=os.environ.get("SUPER_PASSWORD","5109")
READY=False

def parse_db_url():
    if not DATABASE_URL: raise RuntimeError("DATABASE_URL yok")
    u=urlparse(DATABASE_URL)
    return {"user":unquote(u.username or ""),"password":unquote(u.password or ""),"host":u.hostname,"port":u.port or 5432,"database":(u.path or "/neondb").lstrip("/")}

def db():
    c=parse_db_url()
    return pg8000.connect(user=c["user"],password=c["password"],host=c["host"],port=c["port"],database=c["database"],ssl_context=True,timeout=20)

def rows_to_dicts(cur,rows):
    if not rows: return []
    cols=[c["name"] if isinstance(c,dict) else c[0] for c in cur.description]
    return [dict(zip(cols,r)) for r in rows]

def q(sql,params=None,fetch=False,one=False):
    conn=db()
    try:
        cur=conn.cursor(); cur.execute(sql,params or ())
        data=None
        if fetch:
            data=rows_to_dicts(cur,cur.fetchall())
            if one: data=data[0] if data else None
        conn.commit(); cur.close(); return data
    finally:
        conn.close()

def col(table,name,definition):
    r=q("select column_name from information_schema.columns where table_name=%s and column_name=%s",(table,name),fetch=True,one=True)
    if not r: q(f"alter table {table} add column {definition}")

def init_db():
    global READY
    q("create table if not exists firms(id serial primary key,name text not null,logo_url text,admin_username text unique not null,admin_password text not null,active integer default 1)")
    q("create table if not exists personnel(id serial primary key,firm_id integer references firms(id) on delete cascade,full_name text not null,department text not null,annual_leave_total integer default 14,annual_leave_used integer default 0,annual_leave_remaining integer default 14,salary numeric default 0,active integer default 1,username text,password text,token text unique)")
    q("create table if not exists advances(id serial primary key,firm_id integer references firms(id) on delete cascade,person_id integer references personnel(id) on delete cascade,amount numeric not null,note text,status text default 'Beklemede')")
    q("create table if not exists leaves(id serial primary key,firm_id integer references firms(id) on delete cascade,person_id integer references personnel(id) on delete cascade,start_date text not null,end_date text not null,days_count integer default 0,status text default 'İzinli')")
    q("create table if not exists attendance_logs(id serial primary key,firm_id integer references firms(id) on delete cascade,person_id integer references personnel(id) on delete cascade,event_type text not null,event_time text not null)")
    col("personnel","firm_id","firm_id integer references firms(id) on delete cascade")
    col("advances","firm_id","firm_id integer references firms(id) on delete cascade")
    col("leaves","firm_id","firm_id integer references firms(id) on delete cascade")
    col("attendance_logs","firm_id","firm_id integer references firms(id) on delete cascade")
    if not q("select id from firms limit 1",fetch=True,one=True):
        q("insert into firms(name,logo_url,admin_username,admin_password,active) values(%s,'',%s,%s,1)",("Boztek Demo",SUPER_USERNAME,SUPER_PASSWORD))
    READY=True

@app.before_request
def before():
    global READY
    if not READY: init_db()

def fid(): return session.get("firm_id")
def logged(): return fid() is not None
def firm():
    return q("select * from firms where id=%s",(fid(),),fetch=True,one=True) if logged() else None
def fname():
    f=firm(); return f["name"] if f else "Boztek PRO"
@app.context_processor
def inject(): return {"firm_name":fname()}
def val(n,d=None): return request.form.get(n) or request.args.get(n) or d
def days_between(a,b):
    s=datetime.strptime(a,"%Y-%m-%d").date(); e=datetime.strptime(b,"%Y-%m-%d").date()
    return max((e-s).days+1,1)

@app.route("/")
def home(): return redirect("/admin/dashboard") if logged() else redirect("/admin/login")

@app.route("/admin/login",methods=["GET","POST"])
def login():
    if request.method=="POST":
        f=q("select * from firms where admin_username=%s and admin_password=%s and active=1",(request.form.get("username"),request.form.get("password")),fetch=True,one=True)
        if f:
            session["firm_id"]=f["id"]; return redirect("/admin/dashboard")
        flash("Firma kullanıcı adı veya şifre hatalı")
    return render_template("login.html")

@app.route("/admin/logout")
def logout(): session.clear(); return redirect("/admin/login")

@app.route("/admin/dashboard")
def dashboard():
    if not logged(): return redirect("/admin/login")
    id=fid()
    stats=q("select (select count(*) from personnel where firm_id=%s) personel,(select count(*) from leaves where firm_id=%s) izin,(select count(*) from advances where firm_id=%s) avans,(select count(*) from attendance_logs where firm_id=%s) logs",(id,id,id,id),fetch=True,one=True)
    return render_template("dashboard.html",title="Dashboard",stats=stats)

@app.route("/admin/personnel",methods=["GET","POST"])
def personnel():
    if not logged(): return redirect("/admin/login")
    id=fid()
    if request.method=="POST":
        total=int(request.form.get("annual_leave_total",14)); salary=float(request.form.get("salary",0))
        q("insert into personnel(firm_id,full_name,department,annual_leave_total,annual_leave_used,annual_leave_remaining,salary,active,username,password,token) values(%s,%s,%s,%s,0,%s,%s,1,%s,%s,%s)",(id,request.form["full_name"],request.form["department"],total,total,salary,request.form.get("username") or None,request.form.get("password") or None,secrets.token_hex(24)))
        flash("Personel firmaya eklendi.")
    rows=q("select * from personnel where firm_id=%s order by id desc",(id,),fetch=True)
    return render_template("personnel.html",title="Personel",rows=rows)

@app.route("/admin/personnel/<int:pid>/edit",methods=["GET","POST"])
def edit_person(pid):
    if not logged(): return redirect("/admin/login")
    id=fid(); p=q("select * from personnel where id=%s and firm_id=%s",(pid,id),fetch=True,one=True)
    if not p: return redirect("/admin/personnel")
    if request.method=="POST":
        total=int(request.form.get("annual_leave_total",0)); used=int(request.form.get("annual_leave_used",0)); rem=max(total-used,0); token=p.get("token") or secrets.token_hex(24)
        q("update personnel set full_name=%s,department=%s,username=%s,password=%s,annual_leave_total=%s,annual_leave_used=%s,annual_leave_remaining=%s,salary=%s,active=%s,token=%s where id=%s and firm_id=%s",(request.form["full_name"],request.form["department"],request.form.get("username") or None,request.form.get("password") or None,total,used,rem,float(request.form.get("salary",0)),int(request.form.get("active",1)),token,pid,id))
        flash("Personel güncellendi."); return redirect("/admin/personnel")
    return render_template("edit.html",title="Düzenle",p=p)

@app.route("/admin/personnel/<int:pid>/delete",methods=["POST"])
def delete_person(pid):
    if not logged(): return redirect("/admin/login")
    q("delete from personnel where id=%s and firm_id=%s",(pid,fid())); flash("Personel silindi."); return redirect("/admin/personnel")

@app.route("/admin/settings",methods=["GET","POST"])
def settings():
    if not logged(): return redirect("/admin/login")
    if request.method=="POST":
        q("update firms set name=%s,logo_url=%s where id=%s",(request.form.get("name"),request.form.get("logo_url"),fid()))
        flash("Firma ayarları kaydedildi."); return redirect("/admin/settings")
    return render_template("settings.html",title="Firma Ayarları",firm=firm())

@app.route("/admin/advances",methods=["GET","POST"])
def advances():
    if not logged(): return redirect("/admin/login")
    id=fid()
    if request.method=="POST":
        q("insert into advances(firm_id,person_id,amount,note,status) values(%s,%s,%s,'','Beklemede')",(id,request.form["person_id"],request.form["amount"])); flash("Avans kaydedildi.")
    people=q("select * from personnel where firm_id=%s order by full_name",(id,),fetch=True)
    rows=q("select a.*,p.full_name from advances a join personnel p on p.id=a.person_id where a.firm_id=%s order by a.id desc",(id,),fetch=True)
    opts="".join([f"<option value='{p['id']}'>{p['full_name']}</option>" for p in people])
    trs="".join([f"<tr><td>{r['full_name']}</td><td>{float(r['amount']):.2f} ₺</td><td><span class='badge orange'>{r['status']}</span></td></tr>" for r in rows])
    body=f"<div class='card'><form method='post' class='form-grid'><div class='field'><label>Personel</label><select name='person_id'>{opts}</select></div><div class='field'><label>Tutar</label><input name='amount' type='number' step='0.01' required></div><div><button class='btn btn-orange'>Avans Ekle</button></div></form></div><div class='card'><table class='table'><tr><th>Personel</th><th>Tutar</th><th>Durum</th></tr>{trs}</table></div>"
    return render_template("table.html",title="Avanslar",subtitle="Sadece bu firmanın kayıtları.",body=body)

@app.route("/admin/leaves",methods=["GET","POST"])
def leaves():
    if not logged(): return redirect("/admin/login")
    id=fid()
    if request.method=="POST":
        pid=request.form["person_id"]; start=request.form["start_date"]; end=request.form["end_date"]; count=days_between(start,end)
        p=q("select * from personnel where id=%s and firm_id=%s",(pid,id),fetch=True,one=True)
        if p and p["annual_leave_remaining"]>=count:
            q("insert into leaves(firm_id,person_id,start_date,end_date,days_count,status) values(%s,%s,%s,%s,%s,'İzinli')",(id,pid,start,end,count))
            q("update personnel set annual_leave_used=annual_leave_used+%s,annual_leave_remaining=annual_leave_remaining-%s where id=%s and firm_id=%s",(count,count,pid,id))
            flash("İzin kaydedildi.")
        else: flash("Yetersiz izin.")
    people=q("select * from personnel where firm_id=%s order by full_name",(id,),fetch=True)
    rows=q("select l.*,p.full_name from leaves l join personnel p on p.id=l.person_id where l.firm_id=%s order by l.id desc",(id,),fetch=True)
    opts="".join([f"<option value='{p['id']}'>{p['full_name']} - Kalan {p['annual_leave_remaining']}</option>" for p in people])
    trs="".join([f"<tr><td>{r['full_name']}</td><td>{r['start_date']} - {r['end_date']}</td><td>{r['days_count']}</td><td>{r['status']}</td></tr>" for r in rows])
    body=f"<div class='card'><form method='post' class='form-grid'><div class='field'><label>Personel</label><select name='person_id'>{opts}</select></div><div class='field'><label>Başlangıç</label><input name='start_date' type='date' required></div><div class='field'><label>Bitiş</label><input name='end_date' type='date' required></div><div><button class='btn btn-green'>İzin Ekle</button></div></form></div><div class='card'><table class='table'><tr><th>Personel</th><th>Tarih</th><th>Gün</th><th>Durum</th></tr>{trs}</table></div>"
    return render_template("table.html",title="İzinler",subtitle="Sadece bu firmanın kayıtları.",body=body)

@app.route("/admin/salary")
def salary():
    if not logged(): return redirect("/admin/login")
    id=fid()
    rows=q("select p.*,coalesce(sum(a.amount),0) total_advance from personnel p left join advances a on a.person_id=p.id and a.firm_id=%s where p.firm_id=%s group by p.id order by p.full_name",(id,id),fetch=True)
    trs=""
    for r in rows:
        s=float(r["salary"] or 0); a=float(r["total_advance"] or 0)
        trs+=f"<tr><td>{r['full_name']}</td><td>{r['department']}</td><td>{s:.2f} ₺</td><td>{a:.2f} ₺</td><td><b>{s-a:.2f} ₺</b></td></tr>"
    return render_template("table.html",title="Maaşlar",subtitle="Firmaya özel maaş özeti.",body=f"<div class='card'><table class='table'><tr><th>Personel</th><th>Bölüm</th><th>Maaş</th><th>Avans</th><th>Kalan</th></tr>{trs}</table></div>")

@app.route("/admin/attendance")
def attendance():
    if not logged(): return redirect("/admin/login")
    rows=q("select a.*,p.full_name from attendance_logs a join personnel p on p.id=a.person_id where a.firm_id=%s order by a.id desc limit 300",(fid(),),fetch=True)
    trs="".join([f"<tr><td>{r['full_name']}</td><td>{'Giriş' if r['event_type']=='entry' else 'Çıkış'}</td><td>{r['event_time']}</td></tr>" for r in rows])
    return render_template("table.html",title="Giriş / Çıkış",subtitle="Firmaya özel kayıtlar.",body=f"<div class='card'><table class='table'><tr><th>Personel</th><th>Tip</th><th>Zaman</th></tr>{trs}</table></div>")

@app.route("/admin/annual-leave")
def annual():
    if not logged(): return redirect("/admin/login")
    rows=q("select * from personnel where firm_id=%s order by full_name",(fid(),),fetch=True)
    trs="".join([f"<tr><td>{r['full_name']}</td><td>{r['department']}</td><td>{r['annual_leave_total']}</td><td>{r['annual_leave_used']}</td><td>{r['annual_leave_remaining']}</td></tr>" for r in rows])
    return render_template("table.html",title="Yıllık İzin",subtitle="Firma personellerinin yıllık izin hakları.",body=f"<div class='card'><table class='table'><tr><th>Personel</th><th>Bölüm</th><th>Toplam</th><th>Kullanılan</th><th>Kalan</th></tr>{trs}</table></div>")

@app.route("/admin/reports")
def reports(): return salary()

@app.route("/api/health")
def health():
    q("select 1",fetch=True,one=True); return jsonify({"status":"ok","database":"connected","mode":"multi-firm-pro"})

@app.route("/api/firm-create",methods=["GET","POST"])
def firm_create():
    if val("master")!=SUPER_PASSWORD: return jsonify({"status":"error","message":"yetkisiz"}),403
    name=val("name"); username=val("username"); password=val("password")
    if not name or not username or not password: return jsonify({"status":"error","message":"eksik alan"}),400
    q("insert into firms(name,logo_url,admin_username,admin_password,active) values(%s,'',%s,%s,1)",(name,username,password))
    return jsonify({"status":"ok","firm":name,"username":username})

@app.route("/api/personnel")
def api_personnel():
    id=val("firm_id")
    if not id:
        first=q("select id from firms order by id limit 1",fetch=True,one=True); id=first["id"] if first else 0
    return jsonify(q("select * from personnel where firm_id=%s and active=1 order by full_name",(id,),fetch=True))

@app.route("/api/entry",methods=["GET","POST"])
def api_entry():
    pid=val("person_id"); p=q("select * from personnel where id=%s",(pid,),fetch=True,one=True)
    if not p: return jsonify({"status":"error","message":"personel yok"}),404
    t=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    q("insert into attendance_logs(firm_id,person_id,event_type,event_time) values(%s,%s,'entry',%s)",(p["firm_id"],pid,t))
    return jsonify({"status":"ok","firm_id":p["firm_id"],"person_id":int(pid),"event_type":"entry","event_time":t})

@app.route("/api/exit",methods=["GET","POST"])
def api_exit():
    pid=val("person_id"); p=q("select * from personnel where id=%s",(pid,),fetch=True,one=True)
    if not p: return jsonify({"status":"error","message":"personel yok"}),404
    t=datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    q("insert into attendance_logs(firm_id,person_id,event_type,event_time) values(%s,%s,'exit',%s)",(p["firm_id"],pid,t))
    return jsonify({"status":"ok","firm_id":p["firm_id"],"person_id":int(pid),"event_type":"exit","event_time":t})

@app.route("/api/employee-login",methods=["GET","POST"])
def employee_login():
    u=val("username"); pw=val("password")
    p=q("select * from personnel where username=%s and password=%s and active=1",(u,pw),fetch=True,one=True)
    if not p: return jsonify({"status":"error","message":"hatalı giriş"}),401
    token=p.get("token") or secrets.token_hex(24)
    q("update personnel set token=%s where id=%s",(token,p["id"]))
    return jsonify({"status":"ok","token":token,"person":p})

if __name__=="__main__":
    app.run(host="0.0.0.0",port=int(os.environ.get("PORT",10000)))
