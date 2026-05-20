{% extends "base.html" %}
{% block content %}
<div class="hero"><div class="title">QR Kartları</div><div class="subtitle">Her kart personele özeldir. QR okutulunca server otomatik giriş/çıkış kaydı alır.</div></div>
<div class="card"><button class="btn btn-green" onclick="window.print()">QR Kartlarını Yazdır</button></div>
<div class="qr-grid">
{% for p in rows %}
  <div class="qr-card">
    <div class="qr-logo">◆</div>
    <div class="qr-name">{{p.full_name}}</div>
    <div class="qr-dept">{{p.department}}</div>
    <img src="https://api.qrserver.com/v1/create-qr-code/?size=240x240&data={{ p.qr_url|urlencode }}" alt="QR">
    <div class="qr-code">{{p.qr_payload}}</div>
    <div class="qr-hint">Kişiye özel güvenli kart</div>
  </div>
{% endfor %}
</div>
{% endblock %}
