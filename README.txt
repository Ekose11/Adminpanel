BOZTEK ÇOK FİRMALI PRO - ADIM 1

Özellik:
- Her firma kendi kullanıcı adı/şifresiyle giriş yapar.
- Her firma sadece kendi personel, avans, izin, maaş ve giriş/çıkış kayıtlarını görür.
- Firma ayarları menüsü vardır.
- İlk firma otomatik oluşur:
  kullanıcı: saban
  şifre: 5109

Render:
Build Command:
pip install -r requirements.txt

Start Command:
gunicorn --workers 1 --threads 4 --timeout 120 app:app

Yeni firma açma:
https://SERVER/api/firm-create?master=5109&name=ABC%20Servis&username=abc&password=1234

Sonraki adım:
PDF rapor sistemi.
