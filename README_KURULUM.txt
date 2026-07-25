BOZTEK PERSONEL PWA - IOS / ANDROID TARAYICI SÜRÜMÜ

İÇERİK
- Vardiya menüsü tamamen kaldırıldı.
- Profesyonel personel ana ekranı.
- Hızlı QR giriş ve QR çıkış.
- QR algılanınca kamera anında kapanır.
- 8 saniyelik istemci kilidi ve tek istek koruması vardır.
- Her QR isteğinde benzersiz request_id gönderilir.
- İzin talebi.
- Bildirimler.
- Avans geçmişi.
- Profil düzenleme ve fotoğraf yükleme.
- iPhone Safari Ana Ekrana Ekle desteği.

SERVERA YÜKLEME
1) Bu ZIP'i açın.
2) templates ve static klasörlerini çalışan Flask server projenizin ana klasörüne kopyalayın.
3) personel_pwa_routes.py dosyasını app.py ile aynı klasöre koyun.
4) APP_PY_EKLE.txt içindeki iki satırı app.py dosyanıza ekleyin.
5) GitHub'a yükleyin ve Render deploy işlemini bekleyin.

PERSONEL LİNKİ
https://adminpanel-wvpi.onrender.com/personel/

iPHONE KURULUMU
1) Linki Safari ile açın.
2) Paylaş simgesine basın.
3) Ana Ekrana Ekle seçeneğine basın.
4) Personel simgesine ana ekrandan girin.

ÖNEMLİ
- Kamera yalnızca HTTPS adresinde çalışır. Render adresi HTTPS olduğu için uygundur.
- İlk kamera kullanımında Safari kamera izni ister; İzin Ver seçilmelidir.
- QR tarama motoru html5-qrcode 2.3.8 sürümüne sabitlenmiştir.
- En kesin çift kayıt koruması için server /api/qr/verify endpointinde request_id alanının benzersiz tutulması önerilir. Uygulama bu alanı hazır gönderir.
