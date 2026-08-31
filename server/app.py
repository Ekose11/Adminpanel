from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3, secrets, hashlib, datetime, os

app = Flask(__name__)
CORS(app)
DB = os.environ.get('BOZTEK_DB', 'boztek.db')


def con():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def now():
    return datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def make_token():
    return secrets.token_urlsafe(32)


def make_qr_secret():
    return secrets.token_urlsafe(24)


def qr_text(person_id, qr_secret):
    # QR içine yalnızca bu güvenli metin konur. Düz ID artık kabul edilmez.
    return f"BOZTEKQR|person_id={person_id}|qr_token={qr_secret}"


def init_db():
    db = con()
    db.execute('''CREATE TABLE IF NOT EXISTS personnel (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        full_name TEXT NOT NULL,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        department TEXT DEFAULT '',
        salary REAL DEFAULT 0,
        total_advance REAL DEFAULT 0,
        annual_leave_remaining INTEGER DEFAULT 14,
        active INTEGER DEFAULT 1,
        login_token TEXT,
        qr_secret TEXT UNIQUE,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        person_id INTEGER NOT NULL,
        action TEXT NOT NULL,
        created_at TEXT NOT NULL
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS leave_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        person_id INTEGER NOT NULL,
        start_date TEXT,
        end_date TEXT,
        note TEXT,
        status TEXT DEFAULT 'Bekliyor',
        created_at TEXT NOT NULL
    )''')
    db.execute('''CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        person_id INTEGER NOT NULL,
        event_type TEXT,
        message TEXT,
        created_at TEXT NOT NULL
    )''')
    db.commit()

    # Eski kayıtlarda qr_secret yoksa üret.
    rows = db.execute("SELECT id FROM personnel WHERE qr_secret IS NULL OR qr_secret='' ").fetchall()
    for r in rows:
        db.execute('UPDATE personnel SET qr_secret=? WHERE id=?', (make_qr_secret(), r['id']))
    db.commit()

    # Test için personel yoksa iki demo personel oluştur.
    if db.execute('SELECT COUNT(*) c FROM personnel').fetchone()['c'] == 0:
        demo = [
            ('Ahmet Yılmaz', 'ahmet', '1234', 'Servis', 30000, 0, 14),
            ('Mehmet Kaya', 'mehmet', '1234', 'Teknik', 32000, 0, 14),
        ]
        for d in demo:
            db.execute('''INSERT INTO personnel
                (full_name, username, password, department, salary, total_advance, annual_leave_remaining, qr_secret)
                VALUES (?,?,?,?,?,?,?,?)''', (*d, make_qr_secret()))
        db.commit()
    db.close()


def person_json(p):
    return {
        'id': p['id'],
        'full_name': p['full_name'],
        'username': p['username'],
        'department': p['department'] or '',
        'salary': p['salary'] or 0,
        'total_advance': p['total_advance'] or 0,
        'remaining_salary': (p['salary'] or 0) - (p['total_advance'] or 0),
        'annual_leave_remaining': p['annual_leave_remaining'] or 0,
        'active': bool(p['active']),
    }


def get_logged_person(db):
    token = request.values.get('token', '').strip()
    if not token:
        return None
    return db.execute('SELECT * FROM personnel WHERE login_token=? AND active=1', (token,)).fetchone()


def extract_qr(qr_raw):
    raw = (qr_raw or '').strip()
    if not raw.startswith('BOZTEKQR|'):
        return None, None
    parts = {}
    for part in raw.split('|'):
        if '=' in part:
            k, v = part.split('=', 1)
            parts[k.strip()] = v.strip()
    try:
        return int(parts.get('person_id', '0')), parts.get('qr_token', '')
    except Exception:
        return None, None


@app.route('/')
def home():
    return jsonify(status='ok', app='Boztek Server', qr='secure_person_qr_enabled')


@app.route('/api/employee-login')
def employee_login():
    username = request.args.get('username', '').strip()
    password = request.args.get('password', '').strip()
    db = con()
    p = db.execute('SELECT * FROM personnel WHERE username=? AND password=? AND active=1', (username, password)).fetchone()
    if not p:
        db.close()
        return jsonify(status='error', message='Kullanıcı adı veya şifre hatalı')
    token = make_token()
    db.execute('UPDATE personnel SET login_token=? WHERE id=?', (token, p['id']))
    db.commit()
    p = db.execute('SELECT * FROM personnel WHERE id=?', (p['id'],)).fetchone()
    out = jsonify(status='ok', token=token, person=person_json(p))
    db.close()
    return out


@app.route('/api/employee-me')
def employee_me():
    db = con()
    p = get_logged_person(db)
    if not p:
        db.close()
        return jsonify(status='error', message='Oturum geçersiz')
    out = jsonify(status='ok', person=person_json(p))
    db.close()
    return out


@app.route('/api/my-qr')
def my_qr():
    db = con()
    p = get_logged_person(db)
    if not p:
        db.close()
        return jsonify(status='error', message='Oturum geçersiz')
    if not p['qr_secret']:
        secret = make_qr_secret()
        db.execute('UPDATE personnel SET qr_secret=? WHERE id=?', (secret, p['id']))
        db.commit()
        p = db.execute('SELECT * FROM personnel WHERE id=?', (p['id'],)).fetchone()
    out = jsonify(status='ok', person_id=p['id'], qr_text=qr_text(p['id'], p['qr_secret']))
    db.close()
    return out


@app.route('/api/regenerate-qr', methods=['POST'])
def regenerate_qr():
    # Barkod kaybolursa/şüphelenilirse yenilemek için.
    db = con()
    p = get_logged_person(db)
    if not p:
        db.close()
        return jsonify(status='error', message='Oturum geçersiz')
    secret = make_qr_secret()
    db.execute('UPDATE personnel SET qr_secret=? WHERE id=?', (secret, p['id']))
    db.commit()
    out = jsonify(status='ok', message='Yeni kişisel barkod oluşturuldu', qr_text=qr_text(p['id'], secret))
    db.close()
    return out


@app.route('/api/qr/verify', methods=['POST'])
def verify_qr():
    db = con()
    logged = get_logged_person(db)
    if not logged:
        db.close()
        return jsonify(status='error', message='Oturum geçersiz')

    action = request.form.get('action', 'entry').strip()
    qr_raw = request.form.get('qr_text', '').strip()
    person_id, qr_secret = extract_qr(qr_raw)

    if action not in ('entry', 'exit'):
        db.close()
        return jsonify(status='error', message='Geçersiz işlem')
    if not person_id or not qr_secret:
        db.close()
        return jsonify(status='error', message='Geçersiz barkod. Eski ID barkodları kabul edilmez.')

    # En önemli güvenlik: okutulan barkod giriş yapan kullanıcıya ait mi?
    if int(logged['id']) != int(person_id):
        db.close()
        return jsonify(status='error', message='Bu barkod bu kullanıcıya ait değil')

    owner = db.execute('SELECT * FROM personnel WHERE id=? AND qr_secret=? AND active=1', (person_id, qr_secret)).fetchone()
    if not owner:
        db.close()
        return jsonify(status='error', message='Barkod token hatalı veya iptal edilmiş')

    db.execute('INSERT INTO attendance (person_id, action, created_at) VALUES (?,?,?)', (person_id, action, now()))
    db.execute('INSERT INTO notifications (person_id, event_type, message, created_at) VALUES (?,?,?,?)',
               (person_id, 'QR', 'Giriş kaydedildi' if action == 'entry' else 'Çıkış kaydedildi', now()))
    db.commit()
    db.close()
    return jsonify(status='ok', message='Giriş kaydedildi' if action == 'entry' else 'Çıkış kaydedildi')


@app.route('/api/employee-advances')
def employee_advances():
    db = con()
    p = get_logged_person(db)
    if not p:
        db.close()
        return jsonify(status='error', advances=[])
    db.close()
    return jsonify(status='ok', advances=[])


@app.route('/api/employee-leave-request', methods=['POST'])
def employee_leave_request():
    db = con()
    p = get_logged_person(db)
    if not p:
        db.close()
        return jsonify(status='error', message='Oturum geçersiz')
    db.execute('INSERT INTO leave_requests (person_id,start_date,end_date,note,created_at) VALUES (?,?,?,?,?)',
               (p['id'], request.form.get('start_date',''), request.form.get('end_date',''), request.form.get('note',''), now()))
    db.commit()
    db.close()
    return jsonify(status='ok', message='İzin talebi gönderildi')


@app.route('/api/employee-notifications')
def employee_notifications():
    db = con()
    p = get_logged_person(db)
    if not p:
        db.close()
        return jsonify(status='error', notifications=[])
    rows = db.execute('SELECT event_type,message,created_at FROM notifications WHERE person_id=? ORDER BY id DESC LIMIT 30', (p['id'],)).fetchall()
    out = [dict(r) for r in rows]
    db.close()
    return jsonify(status='ok', notifications=out)


# Eski uygulamalar bozulmasın diye bırakıldı; güvenli kullanım için /api/qr/verify kullanın.
@app.route('/api/entry', methods=['POST'])
def legacy_entry():
    return jsonify(status='error', message='Güvenlik için eski ID ile giriş kapatıldı. /api/qr/verify kullanın.')

@app.route('/api/exit', methods=['POST'])
def legacy_exit():
    return jsonify(status='error', message='Güvenlik için eski ID ile çıkış kapatıldı. /api/qr/verify kullanın.')


init_db()
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
