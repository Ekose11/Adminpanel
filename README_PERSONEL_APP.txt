PERSONEL SISTEMI PREMIUM ANDROID UYGULAMASI

Ozellikler:
- Premium koyu gorunum
- Server ile ayni logo
- Boztek yazilari kaldirildi
- Kullanici adi / sifre girisi
- Profil duzenleme: fotograf, telefon, adres
- Profil bilgileri server'a POST /api/employee-profile ile kaydedilir
- Guvenli QR okutma: POST /api/qr/verify
- Bana ait barkod: GET /api/my-qr
- Maas, avans, kalan izin, bildirim ve izin talebi ekranlari

Server adresi:
app/src/main/java/com/boztek/personel/MainActivity.java icinde SERVER_URL satirini kendi Render adresinle degistir.

Android Studio:
1. ZIP'i cikar.
2. Android Studio > Open > bu klasoru sec.
3. Build > Rebuild Project.
4. Run veya APK olustur.
