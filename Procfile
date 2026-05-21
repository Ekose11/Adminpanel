{% extends "base.html" %}
{% block content %}
<div class="hero"><div class="title">QR Kartları</div><div class="subtitle">Bu kartları yazdır. Terminal uygulamasında QR okutunca giriş/çıkış kaydı server’a düşer.</div></div>
<div class="card"><button class="btn btn-green" onclick="window.print()">QR Kartlarını Yazdır</button></div>
<div class="qr-grid">
{% for p in rows %}
  <div class="qr-card">
    <div class="qr-name">{{p.full_name}}</div>
    <div>{{p.department}}</div>
    <img src="https://api.qrserver.com/v1/create-qr-code/?size=220x220&data=BOZTEK:{{p.id}}" alt="QR">
    <div class="qr-code">BOZTEK:{{p.id}}</div>
  </div>
{% endfor %}
</div>
{% endblock %}
