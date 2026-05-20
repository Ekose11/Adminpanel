# Bu endpointi server app.py dosyana ekle.
# Personel kartvizit sekmesi, fotoğraf/telefon/adres bilgilerini bu adresten canlı çeker.

@app.route('/api/personnel-cards')
def api_personnel_cards():
    token = request.args.get('token', '')
    # token kontrol fonksiyonun varsa burada kullan:
    # user = get_employee_by_token(token)
    # if not user: return jsonify({'status':'error','message':'Yetkisiz'}), 401
    cards = []
    for p in PERSONNEL:
        cards.append({
            'id': p.get('id'),
            'full_name': p.get('full_name') or p.get('name',''),
            'department': p.get('department','Personel'),
            'phone': p.get('phone',''),
            'address': p.get('address',''),
            'photo_data': p.get('photo_data',''),
            'attendance_status': p.get('attendance_status','')
        })
    return jsonify({'status':'ok','personnel':cards})
