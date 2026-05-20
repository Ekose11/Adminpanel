BOZTEK FULL UPGRADE SERVER

Eklenenler:
- Profesyonel aylık PDF raporu:
  logo, tarih/saat, toplam çalışma günü, geç giriş, erken çıkış, maaş + avans özeti.
- Canlı dashboard:
  işte olan kişi sayısı, bugün giriş yapanlar, geç kalanlar, erken çıkanlar.
- Bildirim sistemi:
  yeni avans, izin onaylandı, maaş yattı bildirimi.
- Personel uygulaması API:
  avans geçmişi, izin talebi gönderme, bildirimler.

Render:
Build Command:
pip install -r requirements.txt

Start Command:
gunicorn --workers 1 --threads 4 --timeout 120 app:app
