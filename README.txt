BOZTEK PERSONEL APP + SERVER TARAFI KISIYE OZEL BARKOD

Bu paket, gonderdigin mevcut uygulamanin ustune duzenlendi.

Android tarafinda:
- Ana ekrana "Bana Ait Barkodu Goster" eklendi.
- Barkod serverdan /api/my-qr ile alinir.
- Kamera artik eski duz ID barkodunu guvenli kabul etmez.
- Okutulan barkod /api/qr/verify endpointine gonderilir.
- Server onaylamadan giris/cikis kaydi yapilmaz.

Server tarafinda:
- server/app.py eklendi.
- Her personele qr_secret olusturur.
- Kisiye ozel barkod metni uretir.
- Baskasina ait barkod okutulursa reddeder.
- Eski /api/entry ve /api/exit ID kaydi guvenlik icin kapatildi.

Yeni endpointler:
GET  /api/my-qr?token=...
POST /api/qr/verify
POST /api/regenerate-qr

Render ayari:
Build Command: pip install -r server/requirements.txt
Start Command: gunicorn server.app:app

Onemli:
MainActivity.java icinde SERVER_URL satiri halen su adrese ayarli:
https://adminpanel-wvp1.onrender.com
Kendi Render linkin degisirse bu satiri guncelle.
