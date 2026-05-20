QR GİRİŞ SERVER

Eklenen:
- Panel menüsü: QR Kartları
- Her personel için QR kod: BOZTEK:personel_id
- QR terminal uygulaması bu kodu okutunca /api/entry veya /api/exit gönderir.

Render:
Build Command: pip install -r requirements.txt
Start Command: gunicorn --workers 1 --threads 4 --timeout 120 app:app
