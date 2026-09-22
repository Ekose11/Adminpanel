BOZTEK QR TEK KAYIT FINAL

Bu sürümde:
- ScannerActivity içinde AtomicBoolean kullanılır.
- QR callback ikinci kez gelse bile işlenmez.
- Kamera ilk okumada pauseAndWait ile kapanır.
- Ana ekranda scanInProgress ikinci taramayı engeller.
- Server isteği sırasında sending kilidi aktiftir.
- Giriş modunda sadece 1 giriş kaydı oluşur.
- Çıkış modunda sadece 1 çıkış kaydı oluşur.
- Kısa bip ve titreşim vardır.

SERVER:
https://adminpanel-wvpi.onrender.com

QR örnekleri:
1
person_id=1
https://site.com/?person_id=1

Kurulum:
1. Eski QR uygulamasını telefondan kaldır.
2. ZIP'i Türkçe karakter olmayan klasöre çıkar:
   C:\Android\BoztekQRTekKayitFinal
3. Android Studio ile aç.
4. Gradle JDK: Embedded JDK.
5. Sync Now.
6. Build APK.