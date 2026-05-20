PREMIUM PERSONEL SERVER

Giriş:
Kullanıcı adı: eren
Şifre: 1234

Render:
Build Command: pip install -r requirements.txt
Start Command: gunicorn --workers 1 --threads 4 --timeout 120 app:app

Yeni özellikler:
- Türkiye saatine göre canlı saat: /api/server-time
- Server içinde üretilen güvenli QR: /admin/qr-cards
- QR doğrulama: /api/qr/verify
- Maaş yatırıldı bildirimi butonu: /admin/salary
- Puantaj sistemi: /admin/puantaj
- Personel gelmediği gün maaşından otomatik kesinti
