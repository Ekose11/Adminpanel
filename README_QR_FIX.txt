QR SUNUCU HATASI DÜZELTME

Eklenen/düzeltilen endpointler:
- POST/GET /api/qr/verify
- POST/GET /api/my-qr
- GET /api/server-time

QR formatı:
PERSONEL:{personel_id}:{token}

Render komutları:
Build Command: pip install -r requirements.txt
Start Command: gunicorn app:app

Deploy sonrası: Manual Deploy -> Clear build cache & deploy
