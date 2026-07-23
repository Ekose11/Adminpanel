Render ayarları:
Build Command: pip install -r requirements.txt
Start Command: gunicorn --workers 1 --threads 4 --timeout 120 app:app

Yeni özellikler:
- Server /admin/shifts sayfasında Excel benzeri aylık rotasyon vardiya tablosu
- A/B/C/X kodları ile vardiya planı
- Aylık şablon girme: örn AAAXBBX
- PDF çıktı: /admin/shifts/pdf
- Personel uygulaması için API: /api/employee-shifts
