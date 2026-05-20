BOZTEK TEMIZ PDF EKLI PAKET

Bu pakette:
- app.py sadece Python kodudur.
- HTML dosyaları templates klasöründedir.
- requirements.txt temizdir.
- Aylık PDF raporu eklenmiştir.

Render ayarları:
Build Command:
pip install -r requirements.txt

Start Command:
gunicorn --workers 1 --threads 4 --timeout 120 app:app

Environment:
DATABASE_URL = Neon connection string

PDF:
Panel > Aylık Rapor > Aylık Raporu PDF İndir
