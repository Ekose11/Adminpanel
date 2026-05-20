KİŞİYE ÖZEL BİLDİRİM SERVER

Bu sürümde:
- Avans bildirimi sadece avans girilen personelin uygulamasında görünür.
- İzin onayı sadece ilgili personelde görünür.
- Personel uygulamasında /api/employee-notifications sadece token sahibinin bildirimlerini döndürür.

Render:
Build Command: pip install -r requirements.txt
Start Command: gunicorn --workers 1 --threads 4 --timeout 120 app:app
