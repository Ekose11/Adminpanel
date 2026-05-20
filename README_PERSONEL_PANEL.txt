PREMIUM PERSONEL PANEL + SERVER

Girisler:
Yonetici: /admin/login
Varsayilan: eren / 1234

Personel panel:
/personel/login
Personel kullanicilari admin panelindeki Personel sayfasindan eklenir.

Eklenenler:
- Profil duzenleme: fotograf, telefon, adres
- Bilgiler server veritabanina kaydedilir
- API: /api/employee-profile GET/POST
- API: /api/my-qr
- API: /api/qr/verify
- API: /api/server-time
- Puantaj sistemi: /admin/puantaj
- Maas yatirildi bildirimi butonu
- Premium logolu koyu cam efektli tasarim

Render:
Build Command: pip install -r requirements.txt
Start Command: gunicorn --workers 1 --threads 4 --timeout 120 app:app
Runtime: python-3.11.9

Not:
Fotoğraf base64 olarak database'e kaydedilir. Büyük fotoğraf seçmeyin; telefon kamerasinda düşük boyutlu görsel daha iyi olur.
