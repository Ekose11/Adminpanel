# app.py dosyanın en altına ekle (PERSONNEL listesi varsa direkt çalışır).
# Kartvizit ekranı fotoğraf/telefon/adres bilgilerini buradan çeker.

@app.route('/api/personnel-cards')
def api_personnel_cards():
    token = request.args.get('token', '')
    people = globals().get('PERSONNEL', globals().get('personnel', globals().get('employees', [])))
    cards = []
    if isinstance(people, dict):
        people = list(people.values())
    for p in people:
        if not isinstance(p, dict):
            continue
        cards.append({
            'id': p.get('id') or p.get('personel_id') or p.get('employee_id'),
            'full_name': p.get('full_name') or p.get('name') or p.get('ad_soyad') or p.get('username','Personel'),
            'department': p.get('department') or p.get('gorev') or p.get('role','Personel'),
            'phone': p.get('phone') or p.get('telefon',''),
            'address': p.get('address') or p.get('adres',''),
            'photo_data': p.get('photo_data') or p.get('photo') or p.get('image') or '',
            'attendance_status': p.get('attendance_status') or p.get('status','')
        })
    return jsonify({'status':'ok','personnel':cards})
