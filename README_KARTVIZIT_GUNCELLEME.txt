Yeni personel uygulamasında "Personeller" sekmesi eklendi.

Özellikler:
- Personeller kartvizit tarzında tek sekmede görünür.
- Fotoğraf, telefon ve adres bilgileri serverdan çekilir.
- Sekme açıkken 10 saniyede bir otomatik yenilenir.
- Manuel "Anlık Yenile" butonu vardır.
- /api/personnel-cards çalışmazsa uygulama /api/employees endpointini denemeye devam eder.

Serverda /api/personnel-cards yoksa, SERVER_PERSONEL_CARDS_ENDPOINT_PATCH.py içindeki endpointi app.py dosyana ekle.
