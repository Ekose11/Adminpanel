BOZTEK SERVER QR GUVENLIK GUNCELLEMESI

Eklenen endpointler:

GET /api/my-qr?token=...
- Giriş yapan personele ait özel QR metnini üretir/döndürür.
- QR metni: BOZTEKQR|person_id=ID|qr_token=GIZLI_TOKEN

POST /api/qr/verify
Form:
- token: giriş yapan personelin tokeni
- qr_text: okutulan QR içeriği
- action: entry veya exit

Server kontrolü:
1) token geçerli mi?
2) QR formatı doğru mu?
3) QR person_id, giriş yapan kullanıcı id ile aynı mı?
4) QR token serverdaki qr_secret ile aynı mı?

Başkasının barkodu okutulursa:
{status:error, message:"Bu barkod bu kullanıcıya ait değil"}

Render için:
Build Command: pip install -r server/requirements.txt
Start Command: gunicorn server.app:app
