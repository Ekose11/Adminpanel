QR eksik veya bozuk hatası düzeltildi.

Yapılanlar:
- QR payload URL encoded gelirse server artık çözer.
- QR görsel URL'si okunursa data parametresi ayıklanır.
- PERSONEL:id:token formatı korunur.
- QR Kartları sayfasındaki QR data alanı doğru encode edilir.

Render:
1) Bu ZIP içeriğini eski server üstüne yaz.
2) Manual Deploy -> Clear build cache & deploy.
3) /admin/qr-cards sayfasından yeni QR kartları okut.
