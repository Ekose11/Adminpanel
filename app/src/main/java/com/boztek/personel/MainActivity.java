package com.boztek.personel;

import android.Manifest;
import android.app.Activity;
import android.os.Bundle;
import android.os.Vibrator;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.provider.MediaStore;
import android.util.Base64;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.widget.*;

import com.journeyapps.barcodescanner.BarcodeCallback;
import com.journeyapps.barcodescanner.BarcodeResult;
import com.journeyapps.barcodescanner.BarcodeView;
import com.google.zxing.ResultPoint;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.util.List;

public class MainActivity extends Activity {

    // Render adresini kendi server adresinle değiştir.
    public static final String SERVER_URL = "https://adminpanel-wvp1.onrender.com";
    private static final int REQ_CAMERA = 77;
    private static final int REQ_PHOTO = 88;

    LinearLayout root;
    SharedPreferences prefs;
    String token = "";
    String selectedPhotoData = "";

    TextView statusText, nameText, deptText, salaryValue, advanceValue, remainingValue, leaveValue, phoneText, addressText, clockText;
    ImageView avatarView;
    FrameLayout cameraBox;
    BarcodeView barcodeView;
    boolean entryMode = true;
    boolean busy = false;
    long lastScanTime = 0;
    Handler liveHandler = new Handler(Looper.getMainLooper());
    Runnable personnelLiveRunnable;

    final int BG1 = Color.rgb(6,13,26);
    final int BG2 = Color.rgb(15,23,42);
    final int WHITE = Color.WHITE;
    final int TEXT = Color.rgb(15,23,42);
    final int MUTED = Color.rgb(100,116,139);
    final int BLUE = Color.rgb(37,99,235);
    final int SKY = Color.rgb(14,165,233);
    final int GREEN = Color.rgb(22,163,74);
    final int RED = Color.rgb(220,38,38);
    final int ORANGE = Color.rgb(245,158,11);

    @Override
    public void onCreate(Bundle b) {
        super.onCreate(b);
        prefs = getSharedPreferences("personel_sistemi", MODE_PRIVATE);
        token = prefs.getString("token", "");
        if (token.length() > 0) {
            showPanel();
            loadMe();
            loadServerTime();
        } else {
            showLogin();
        }
    }

    @Override
    protected void onPause() {
        super.onPause();
        stopScannerOnly();
        stopPersonnelLive();
    }

    int dp(int v) { return (int)(v * getResources().getDisplayMetrics().density + 0.5f); }

    GradientDrawable round(int color, int radius) {
        GradientDrawable g = new GradientDrawable();
        g.setColor(color);
        g.setCornerRadius(dp(radius));
        return g;
    }

    GradientDrawable bg() {
        return new GradientDrawable(GradientDrawable.Orientation.TOP_BOTTOM, new int[]{BG1, BG2});
    }

    GradientDrawable premiumBg(int color, int strokeColor) {
        GradientDrawable g = new GradientDrawable(GradientDrawable.Orientation.TL_BR, new int[]{color, Color.rgb(15,23,42)});
        g.setCornerRadius(dp(26));
        g.setStroke(dp(1), strokeColor);
        return g;
    }

    TextView text(String s, int size, int color, int style) {
        TextView v = new TextView(this);
        v.setText(s);
        v.setTextSize(size);
        v.setTextColor(color);
        v.setTypeface(Typeface.DEFAULT, style);
        v.setPadding(0, dp(4), 0, dp(4));
        return v;
    }

    Button btn(String s, int color) {
        Button b = new Button(this);
        b.setText(s);
        b.setTextSize(15);
        b.setTextColor(WHITE);
        b.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        b.setAllCaps(false);
        b.setBackground(round(color, 18));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, dp(58));
        lp.setMargins(0, dp(7), 0, dp(7));
        b.setLayoutParams(lp);
        return b;
    }

    Button menuBtn(String s, int color) {
        Button b = btn(s, color);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0, dp(58), 1);
        lp.setMargins(dp(5), dp(5), dp(5), dp(5));
        b.setLayoutParams(lp);
        return b;
    }

    EditText input(String hint, boolean pass) {
        EditText e = new EditText(this);
        e.setHint(hint);
        e.setTextSize(17);
        e.setSingleLine(!hint.toLowerCase().contains("adres"));
        e.setPadding(dp(15), dp(13), dp(15), dp(13));
        e.setBackground(round(Color.rgb(248,250,252), 16));
        if (pass) e.setInputType(0x00000081);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.setMargins(0, dp(8), 0, dp(8));
        e.setLayoutParams(lp);
        return e;
    }

    ImageView logoView(int size) {
        ImageView img = new ImageView(this);
        img.setImageResource(getResources().getIdentifier("premium_logo", "drawable", getPackageName()));
        img.setAdjustViewBounds(true);
        img.setScaleType(ImageView.ScaleType.FIT_CENTER);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(dp(size), dp(size));
        lp.gravity = Gravity.CENTER_HORIZONTAL;
        lp.setMargins(0, dp(4), 0, dp(10));
        img.setLayoutParams(lp);
        return img;
    }

    LinearLayout premiumCard() {
        LinearLayout c = new LinearLayout(this);
        c.setOrientation(LinearLayout.VERTICAL);
        c.setPadding(dp(18), dp(18), dp(18), dp(18));
        c.setBackground(premiumBg(Color.rgb(17,24,39), Color.rgb(51,65,85)));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.setMargins(0, dp(10), 0, dp(10));
        c.setLayoutParams(lp);
        return c;
    }

    LinearLayout whiteCard() {
        LinearLayout c = new LinearLayout(this);
        c.setOrientation(LinearLayout.VERTICAL);
        c.setPadding(dp(20), dp(20), dp(20), dp(20));
        c.setBackground(round(WHITE, 24));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.setMargins(0, dp(10), 0, dp(10));
        c.setLayoutParams(lp);
        return c;
    }

    LinearLayout row() {
        LinearLayout r = new LinearLayout(this);
        r.setOrientation(LinearLayout.HORIZONTAL);
        r.setGravity(Gravity.CENTER);
        r.setLayoutParams(new LinearLayout.LayoutParams(-1, -2));
        return r;
    }

    LinearLayout statCard(String label, TextView value, int accent) {
        LinearLayout c = new LinearLayout(this);
        c.setOrientation(LinearLayout.VERTICAL);
        c.setPadding(dp(14), dp(14), dp(14), dp(14));
        c.setBackground(premiumBg(Color.rgb(15,23,42), accent));
        c.addView(text(label, 12, Color.rgb(203,213,225), Typeface.BOLD));
        value.setTextSize(21);
        value.setTextColor(WHITE);
        value.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        c.addView(value);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0, dp(94), 1);
        lp.setMargins(dp(5), dp(5), dp(5), dp(5));
        c.setLayoutParams(lp);
        return c;
    }

    void makeRoot() {
        ScrollView s = new ScrollView(this);
        s.setBackground(bg());
        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(20), dp(26), dp(20), dp(26));
        s.addView(root);
        setContentView(s);
    }

    void showLogin() {
        makeRoot();
        root.addView(logoView(104));
        TextView title = text("Personel Sistemi", 32, WHITE, Typeface.BOLD);
        title.setGravity(Gravity.CENTER);
        root.addView(title);
        TextView sub = text("Profil • Maaş • Puantaj • Güvenli QR", 15, Color.rgb(203,213,225), Typeface.BOLD);
        sub.setGravity(Gravity.CENTER);
        root.addView(sub);

        LinearLayout c = whiteCard();
        c.addView(text("Personel Girişi", 25, TEXT, Typeface.BOLD));
        EditText u = input("Kullanıcı adı", false);
        EditText p = input("Şifre", true);
        Button login = btn("Giriş Yap", BLUE);
        statusText = text("", 15, RED, Typeface.BOLD);
        c.addView(u); c.addView(p); c.addView(login); c.addView(statusText);
        root.addView(c);

        login.setOnClickListener(v -> doLogin(u.getText().toString().trim(), p.getText().toString().trim()));
    }

    void showPanel() {
        makeRoot();
        root.addView(logoView(78));
        TextView head = text("Personel Sistemi", 29, WHITE, Typeface.BOLD);
        head.setGravity(Gravity.CENTER);
        root.addView(head);
        clockText = text("Saat alınıyor...", 14, Color.rgb(203,213,225), Typeface.BOLD);
        clockText.setGravity(Gravity.CENTER);
        root.addView(clockText);

        LinearLayout profile = premiumCard();
        LinearLayout top = row();
        avatarView = new ImageView(this);
        avatarView.setScaleType(ImageView.ScaleType.CENTER_CROP);
        avatarView.setBackground(round(Color.rgb(30,41,59), 22));
        LinearLayout.LayoutParams avlp = new LinearLayout.LayoutParams(dp(84), dp(84));
        avlp.setMargins(0, 0, dp(14), 0);
        top.addView(avatarView, avlp);
        LinearLayout info = new LinearLayout(this);
        info.setOrientation(LinearLayout.VERTICAL);
        info.setLayoutParams(new LinearLayout.LayoutParams(0, -2, 1));
        nameText = text("-", 25, WHITE, Typeface.BOLD);
        deptText = text("-", 14, Color.rgb(148,163,184), Typeface.BOLD);
        phoneText = text("Telefon: -", 13, Color.rgb(203,213,225), Typeface.BOLD);
        addressText = text("Adres: -", 13, Color.rgb(203,213,225), Typeface.BOLD);
        info.addView(text("Aktif Personel", 12, Color.rgb(56,189,248), Typeface.BOLD));
        info.addView(nameText); info.addView(deptText); info.addView(phoneText); info.addView(addressText);
        top.addView(info);
        profile.addView(top);
        root.addView(profile);

        salaryValue = text("-", 22, WHITE, Typeface.BOLD);
        advanceValue = text("-", 22, WHITE, Typeface.BOLD);
        remainingValue = text("-", 22, WHITE, Typeface.BOLD);
        leaveValue = text("-", 22, WHITE, Typeface.BOLD);
        LinearLayout row1 = row(); row1.addView(statCard("Maaş", salaryValue, BLUE)); row1.addView(statCard("Avans", advanceValue, ORANGE)); root.addView(row1);
        LinearLayout row2 = row(); row2.addView(statCard("Kalan Maaş", remainingValue, GREEN)); row2.addView(statCard("Kalan İzin", leaveValue, SKY)); root.addView(row2);

        LinearLayout menu = premiumCard();
        menu.addView(text("Menüler", 19, WHITE, Typeface.BOLD));
        Button profileBtn = menuBtn("Profil", SKY);
        Button personnelBtn = menuBtn("Personeller", Color.rgb(99,102,241));
        Button refresh = menuBtn("Yenile", BLUE);
        Button qrEntry = menuBtn("QR Giriş", GREEN);
        Button qrExit = menuBtn("QR Çıkış", RED);
        Button adv = menuBtn("Avans", ORANGE);
        Button nots = menuBtn("Bildirim", BLUE);
        Button leaveReq = menuBtn("İzin Talebi", GREEN);
        Button myQr = menuBtn("Barkodum", Color.rgb(124,58,237));
        LinearLayout m1 = row(); m1.addView(profileBtn); m1.addView(personnelBtn); menu.addView(m1);
        LinearLayout m0 = row(); m0.addView(refresh); menu.addView(m0);
        LinearLayout m2 = row(); m2.addView(qrEntry); m2.addView(qrExit); menu.addView(m2);
        LinearLayout m3 = row(); m3.addView(adv); m3.addView(nots); menu.addView(m3);
        LinearLayout m4 = row(); m4.addView(leaveReq); m4.addView(myQr); menu.addView(m4);
        root.addView(menu);

        Button logout = btn("Çıkış Yap", RED);
        statusText = text("", 15, Color.rgb(203,213,225), Typeface.BOLD);
        statusText.setGravity(Gravity.CENTER);
        root.addView(logout); root.addView(statusText);

        profileBtn.setOnClickListener(v -> showProfile());
        personnelBtn.setOnClickListener(v -> showPersonnelCards());
        refresh.setOnClickListener(v -> { loadMe(); loadServerTime(); });
        qrEntry.setOnClickListener(v -> showQr(true));
        qrExit.setOnClickListener(v -> showQr(false));
        adv.setOnClickListener(v -> loadAdvances());
        nots.setOnClickListener(v -> loadNotifications());
        leaveReq.setOnClickListener(v -> showLeaveRequest());
        myQr.setOnClickListener(v -> loadMyQr());
        logout.setOnClickListener(v -> { prefs.edit().clear().apply(); token = ""; showLogin(); });
    }

    void doLogin(String u, String p) {
        if (u.length() == 0 || p.length() == 0) { statusText.setText("Kullanıcı adı ve şifre gir."); return; }
        statusText.setText("Giriş yapılıyor...");
        new Thread(() -> {
            try {
                String res = httpGet(SERVER_URL + "/api/employee-login?username=" + enc(u) + "&password=" + enc(p));
                JSONObject o = new JSONObject(res);
                if (o.optString("status").equals("ok")) {
                    token = o.getString("token");
                    prefs.edit().putString("token", token).apply();
                    runOnUiThread(() -> { showPanel(); fill(o.optJSONObject("person")); loadServerTime(); });
                } else runOnUiThread(() -> statusText.setText(o.optString("message", "Giriş başarısız")));
            } catch (Exception e) { runOnUiThread(() -> statusText.setText("Bağlantı hatası: " + e.getMessage())); }
        }).start();
    }

    void loadMe() {
        if (statusText != null) statusText.setText("Veriler yenileniyor...");
        new Thread(() -> {
            try {
                JSONObject o = new JSONObject(httpGet(SERVER_URL + "/api/employee-me?token=" + enc(token)));
                if (o.optString("status").equals("ok")) runOnUiThread(() -> fill(o.optJSONObject("person")));
                else runOnUiThread(() -> { prefs.edit().clear().apply(); showLogin(); });
            } catch (Exception e) { runOnUiThread(() -> { if (statusText != null) statusText.setText("Bağlantı hatası"); }); }
        }).start();
    }

    void loadServerTime() {
        new Thread(() -> {
            try {
                JSONObject o = new JSONObject(httpGet(SERVER_URL + "/api/server-time"));
                String time = o.optString("datetime", o.optString("time", ""));
                runOnUiThread(() -> { if (clockText != null) clockText.setText("Güncel saat: " + time); });
            } catch (Exception ignored) {}
        }).start();
    }

    void fill(JSONObject p) {
        if (p == null) return;
        nameText.setText(p.optString("full_name", "-"));
        deptText.setText(p.optString("department", "-"));
        phoneText.setText("Telefon: " + (p.optString("phone", "").length() == 0 ? "Eklenmedi" : p.optString("phone", "")));
        addressText.setText("Adres: " + (p.optString("address", "").length() == 0 ? "Eklenmedi" : p.optString("address", "")));
        salaryValue.setText(money(p.optDouble("salary", 0)) + " TL");
        advanceValue.setText(money(p.optDouble("total_advance", 0)) + " TL");
        remainingValue.setText(money(p.optDouble("remaining_salary", 0)) + " TL");
        leaveValue.setText(p.optInt("annual_leave_remaining", 0) + " gün");
        selectedPhotoData = p.optString("photo_data", "");
        setImageFromData(avatarView, selectedPhotoData, p.optString("full_name", "P"));
        if (statusText != null) statusText.setText("Güncel veri alındı");
    }

    void showProfile() {
        makeRoot();
        root.addView(logoView(70));
        TextView title = text("Profil Düzenle", 30, WHITE, Typeface.BOLD); title.setGravity(Gravity.CENTER); root.addView(title);
        LinearLayout c = whiteCard();
        ImageView preview = new ImageView(this);
        preview.setScaleType(ImageView.ScaleType.CENTER_CROP);
        LinearLayout.LayoutParams plp = new LinearLayout.LayoutParams(dp(140), dp(140)); plp.gravity = Gravity.CENTER_HORIZONTAL; plp.setMargins(0,0,0,dp(10));
        c.addView(preview, plp);
        setImageFromData(preview, selectedPhotoData, "P");
        EditText phone = input("Telefon numarası", false);
        EditText address = input("Adres", false);
        try { phone.setText(phoneText.getText().toString().replace("Telefon: ", "").replace("Eklenmedi", "")); } catch(Exception ignored) {}
        try { address.setText(addressText.getText().toString().replace("Adres: ", "").replace("Eklenmedi", "")); } catch(Exception ignored) {}
        Button choose = btn("Fotoğraf Seç", BLUE);
        Button save = btn("Profili Server'a Kaydet", GREEN);
        Button back = btn("Geri", RED);
        statusText = text("Fotoğraf, telefon ve adres server'a kaydedilir.", 14, MUTED, Typeface.BOLD);
        c.addView(choose); c.addView(phone); c.addView(address); c.addView(save); c.addView(statusText);
        root.addView(c); root.addView(back);
        choose.setOnClickListener(v -> {
            Intent i = new Intent(Intent.ACTION_OPEN_DOCUMENT);
            i.setType("image/*");
            i.addCategory(Intent.CATEGORY_OPENABLE);
            startActivityForResult(i, REQ_PHOTO);
        });
        save.setOnClickListener(v -> saveProfile(phone.getText().toString().trim(), address.getText().toString().trim()));
        back.setOnClickListener(v -> { showPanel(); loadMe(); });
    }

    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQ_PHOTO && resultCode == RESULT_OK && data != null && data.getData() != null) {
            try {
                Uri uri = data.getData();
                Bitmap bmp = MediaStore.Images.Media.getBitmap(getContentResolver(), uri);
                int max = 520;
                int w = bmp.getWidth(), h = bmp.getHeight();
                float scale = Math.min(1f, (float)max / Math.max(w, h));
                Bitmap small = Bitmap.createScaledBitmap(bmp, Math.max(1,(int)(w*scale)), Math.max(1,(int)(h*scale)), true);
                ByteArrayOutputStream bos = new ByteArrayOutputStream();
                small.compress(Bitmap.CompressFormat.JPEG, 70, bos);
                selectedPhotoData = "data:image/jpeg;base64," + Base64.encodeToString(bos.toByteArray(), Base64.NO_WRAP);
                Toast.makeText(this, "Fotoğraf seçildi", Toast.LENGTH_SHORT).show();
                showProfile();
            } catch (Exception e) { Toast.makeText(this, "Fotoğraf alınamadı", Toast.LENGTH_SHORT).show(); }
        }
    }

    void saveProfile(String phone, String address) {
        statusText.setText("Profil kaydediliyor...");
        new Thread(() -> {
            try {
                String form = "token=" + enc(token) + "&phone=" + enc(phone) + "&address=" + enc(address) + "&photo_data=" + enc(selectedPhotoData);
                JSONObject o = new JSONObject(httpPost(SERVER_URL + "/api/employee-profile", form));
                runOnUiThread(() -> {
                    statusText.setText(o.optString("message", "Profil kaydedildi"));
                    if (o.optString("status").equals("ok")) fill(o.optJSONObject("person"));
                });
            } catch (Exception e) { runOnUiThread(() -> statusText.setText("Profil kaydedilemedi: " + e.getMessage())); }
        }).start();
    }

    void showQr(boolean entry) {
        entryMode = entry;
        makeRoot();
        root.addView(logoView(70));
        TextView qrTitle = text(entry ? "QR Giriş" : "QR Çıkış", 31, WHITE, Typeface.BOLD); qrTitle.setGravity(Gravity.CENTER); root.addView(qrTitle);
        TextView qrSub = text("Kişiye özel barkod doğrulama", 15, Color.rgb(203,213,225), Typeface.BOLD); qrSub.setGravity(Gravity.CENTER); root.addView(qrSub);
        statusText = text("Kamera başlatılıyor...", 15, Color.rgb(203,213,225), Typeface.BOLD); root.addView(statusText);
        cameraBox = new FrameLayout(this); cameraBox.setBackground(round(Color.rgb(2,6,23), 26));
        LinearLayout.LayoutParams camLp = new LinearLayout.LayoutParams(-1, dp(380)); camLp.setMargins(0, dp(12), 0, dp(12)); root.addView(cameraBox, camLp);
        Button start = btn("Kamerayı Başlat", BLUE); Button stop = btn("Kamerayı Kapat", ORANGE); Button back = btn("Ana Ekran", RED);
        root.addView(start); root.addView(stop); root.addView(back);
        start.setOnClickListener(v -> startScanner()); stop.setOnClickListener(v -> stopScanner()); back.setOnClickListener(v -> { stopScannerOnly(); showPanel(); loadMe(); });
        startScanner();
    }

    void startScanner() {
        if (android.os.Build.VERSION.SDK_INT >= 23 && checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.CAMERA}, REQ_CAMERA); return;
        }
        try {
            cameraBox.removeAllViews(); barcodeView = new BarcodeView(this); cameraBox.addView(barcodeView, new FrameLayout.LayoutParams(-1, -1));
            barcodeView.decodeContinuous(callback); barcodeView.resume(); busy = false; statusText.setText("Kamera açık. QR okut.");
        } catch (Exception e) { statusText.setText("Kamera açılamadı: " + e.getMessage()); showCameraClosed("KAMERA AÇILAMADI"); }
    }

    void stopScannerOnly() { try { if (barcodeView != null) barcodeView.pause(); } catch (Exception ignored) {} busy = false; }
    void stopScanner() { stopScannerOnly(); showCameraClosed("KAMERA KAPALI"); statusText.setText("Kamera kapalı."); }
    void showCameraClosed(String msg) { if (cameraBox == null) return; cameraBox.removeAllViews(); TextView t = text(msg, 24, Color.rgb(148,163,184), Typeface.BOLD); t.setGravity(Gravity.CENTER); cameraBox.addView(t, new FrameLayout.LayoutParams(-1, -1)); }

    BarcodeCallback callback = new BarcodeCallback() {
        @Override public void barcodeResult(BarcodeResult result) {
            if (result == null || result.getText() == null) return;
            long now = System.currentTimeMillis(); if (busy || now - lastScanTime < 2500) return;
            String raw = result.getText().trim(); busy = true; lastScanTime = now; vibrate(); sendQrVerify(raw, entryMode);
        }
        @Override public void possibleResultPoints(List<ResultPoint> resultPoints) {}
    };

    void sendQrVerify(String qrPayload, boolean entry) {
        statusText.setText(entry ? "Giriş doğrulanıyor..." : "Çıkış doğrulanıyor...");
        new Thread(() -> {
            try {
                String form = "token=" + enc(token) + "&qr_payload=" + enc(qrPayload) + "&action=" + enc(entry ? "entry" : "exit");
                JSONObject obj = new JSONObject(httpPost(SERVER_URL + "/api/qr/verify", form));
                runOnUiThread(() -> {
                    busy = false;
                    if ("ok".equals(obj.optString("status"))) statusText.setText((entry ? "Giriş kaydedildi" : "Çıkış kaydedildi") + " • " + obj.optString("full_name", ""));
                    else statusText.setText(obj.optString("message", "QR doğrulanamadı"));
                });
            } catch (Exception e) { runOnUiThread(() -> { busy = false; statusText.setText("Server bağlantı hatası: " + e.getMessage()); }); }
        }).start();
    }

    void loadMyQr() {
        makeRoot(); root.addView(logoView(70)); root.addView(text("Bana Ait Barkod", 30, WHITE, Typeface.BOLD));
        statusText = text("QR bilgisi alınıyor...", 15, Color.rgb(203,213,225), Typeface.BOLD); root.addView(statusText);
        new Thread(() -> {
            try {
                JSONObject o = new JSONObject(httpGet(SERVER_URL + "/api/my-qr?token=" + enc(token)));
                runOnUiThread(() -> {
                    String payload = o.optString("qr_payload", "");
                    statusText.setText(payload.length() > 0 ? "Bu QR yalnızca sana aittir." : o.optString("message", "QR alınamadı"));
                    LinearLayout c = whiteCard();
                    c.addView(text("QR İçeriği", 20, TEXT, Typeface.BOLD));
                    TextView pay = text(payload, 14, MUTED, Typeface.BOLD); pay.setGravity(Gravity.CENTER); c.addView(pay);
                    root.addView(c);
                    Button back = btn("Ana Ekran", BLUE); root.addView(back); back.setOnClickListener(v -> { showPanel(); loadMe(); });
                });
            } catch (Exception e) { runOnUiThread(() -> statusText.setText("QR alınamadı")); }
        }).start();
    }

    void loadAdvances() {
        makeRoot(); root.addView(text("Avans Geçmişi", 30, WHITE, Typeface.BOLD)); statusText = text("Avans geçmişi alınıyor...", 15, Color.rgb(203,213,225), Typeface.BOLD); root.addView(statusText);
        new Thread(() -> {
            try {
                JSONObject o = new JSONObject(httpGet(SERVER_URL + "/api/employee-advances?token=" + enc(token))); JSONArray arr = o.optJSONArray("advances");
                runOnUiThread(() -> { statusText.setText("Avans geçmişi"); if (arr != null) for (int i=0;i<arr.length();i++){ JSONObject a=arr.optJSONObject(i); LinearLayout c=whiteCard(); c.addView(text(money(a.optDouble("amount",0))+" TL",25,ORANGE,Typeface.BOLD)); c.addView(text(a.optString("status",""),16,MUTED,Typeface.BOLD)); root.addView(c);} addBack(); });
            } catch (Exception e) { runOnUiThread(() -> statusText.setText("Avanslar alınamadı")); }
        }).start();
    }

    void showLeaveRequest() {
        makeRoot(); root.addView(text("İzin Talebi", 30, WHITE, Typeface.BOLD)); LinearLayout c=whiteCard();
        EditText start=input("Başlangıç: 2026-05-20",false); EditText end=input("Bitiş: 2026-05-21",false); EditText note=input("Not",false); Button send=btn("Talep Gönder",GREEN);
        c.addView(start); c.addView(end); c.addView(note); c.addView(send); root.addView(c); statusText=text("",15,Color.rgb(203,213,225),Typeface.BOLD); root.addView(statusText); addBack();
        send.setOnClickListener(v -> sendLeaveRequest(start.getText().toString().trim(), end.getText().toString().trim(), note.getText().toString().trim()));
    }

    void sendLeaveRequest(String s, String e, String n) {
        statusText.setText("Talep gönderiliyor...");
        new Thread(() -> { try { String form="token="+enc(token)+"&start_date="+enc(s)+"&end_date="+enc(e)+"&note="+enc(n); JSONObject o=new JSONObject(httpPost(SERVER_URL+"/api/employee-leave-request",form)); runOnUiThread(() -> statusText.setText(o.optString("message","Talep gönderildi"))); } catch(Exception ex){ runOnUiThread(() -> statusText.setText("Talep gönderilemedi")); } }).start();
    }

    void loadNotifications() {
        makeRoot(); root.addView(text("Bildirimler", 30, WHITE, Typeface.BOLD)); statusText=text("Bildirimler alınıyor...",15,Color.rgb(203,213,225),Typeface.BOLD); root.addView(statusText);
        new Thread(() -> { try { JSONObject o=new JSONObject(httpGet(SERVER_URL+"/api/employee-notifications?token="+enc(token))); JSONArray arr=o.optJSONArray("notifications"); runOnUiThread(() -> { statusText.setText("Bildirimler"); if(arr!=null) for(int i=0;i<arr.length();i++){ JSONObject n=arr.optJSONObject(i); LinearLayout c=whiteCard(); c.addView(text(n.optString("event_type","Bildirim"),20,BLUE,Typeface.BOLD)); c.addView(text(n.optString("message",""),16,TEXT,Typeface.BOLD)); c.addView(text(n.optString("created_at",""),14,MUTED,Typeface.NORMAL)); root.addView(c);} addBack(); }); } catch(Exception e){ runOnUiThread(() -> statusText.setText("Bildirimler alınamadı")); } }).start();
    }


    void showPersonnelCards() {
        makeRoot();
        root.addView(logoView(70));
        TextView title = text("Personel Kartvizitleri", 28, WHITE, Typeface.BOLD);
        title.setGravity(Gravity.CENTER);
        root.addView(title);
        TextView sub = text("Fotoğraf ve iletişim bilgileri serverdan canlı güncellenir", 14, Color.rgb(203,213,225), Typeface.BOLD);
        sub.setGravity(Gravity.CENTER);
        root.addView(sub);
        statusText = text("Personeller alınıyor...", 15, Color.rgb(203,213,225), Typeface.BOLD);
        statusText.setGravity(Gravity.CENTER);
        root.addView(statusText);
        Button refresh = btn("Anlık Yenile", BLUE);
        Button back = btn("Ana Ekran", RED);
        root.addView(refresh);
        root.addView(back);
        refresh.setOnClickListener(v -> loadPersonnelCards(false));
        back.setOnClickListener(v -> { stopPersonnelLive(); showPanel(); loadMe(); });
        loadPersonnelCards(false);
        startPersonnelLive();
    }

    void startPersonnelLive() {
        stopPersonnelLive();
        personnelLiveRunnable = new Runnable() {
            @Override public void run() {
                loadPersonnelCards(true);
                liveHandler.postDelayed(this, 10000);
            }
        };
        liveHandler.postDelayed(personnelLiveRunnable, 10000);
    }

    void stopPersonnelLive() {
        try { if (personnelLiveRunnable != null) liveHandler.removeCallbacks(personnelLiveRunnable); } catch(Exception ignored) {}
        personnelLiveRunnable = null;
    }

    void loadPersonnelCards(boolean silent) {
        if (!silent && statusText != null) statusText.setText("Personeller alınıyor...");
        new Thread(() -> {
            try {
                JSONObject o;
                try {
                    o = new JSONObject(httpGet(SERVER_URL + "/api/personnel-cards?token=" + enc(token)));
                } catch (Exception first) {
                    o = new JSONObject(httpGet(SERVER_URL + "/api/employees?token=" + enc(token)));
                }
                JSONArray arr = o.optJSONArray("personnel");
                if (arr == null) arr = o.optJSONArray("employees");
                final JSONArray finalArr = arr;
                runOnUiThread(() -> renderPersonnelCards(finalArr));
            } catch (Exception e) {
                runOnUiThread(() -> { if (statusText != null) statusText.setText("Personel listesi alınamadı. Serverda /api/personnel-cards endpointini kontrol et."); });
            }
        }).start();
    }

    void renderPersonnelCards(JSONArray arr) {
        // Başlık, açıklama, durum, yenile ve geri butonlarını tut; eski kartları kaldır.
        while (root.getChildCount() > 5) root.removeViewAt(5);
        if (statusText != null) statusText.setText(arr == null ? "Kayıt bulunamadı" : ("Canlı güncellendi • " + arr.length() + " personel"));
        if (arr == null || arr.length() == 0) return;
        for (int i = 0; i < arr.length(); i++) {
            JSONObject p = arr.optJSONObject(i);
            if (p == null) continue;
            root.addView(personnelBusinessCard(p));
        }
    }

    LinearLayout personnelBusinessCard(JSONObject p) {
        LinearLayout card = new LinearLayout(this);
        card.setOrientation(LinearLayout.HORIZONTAL);
        card.setGravity(Gravity.CENTER_VERTICAL);
        card.setPadding(dp(14), dp(14), dp(14), dp(14));
        card.setBackground(premiumBg(Color.rgb(15,23,42), Color.rgb(56,189,248)));
        LinearLayout.LayoutParams clp = new LinearLayout.LayoutParams(-1, -2);
        clp.setMargins(0, dp(8), 0, dp(8));
        card.setLayoutParams(clp);

        ImageView photo = new ImageView(this);
        photo.setScaleType(ImageView.ScaleType.CENTER_CROP);
        photo.setBackground(round(Color.rgb(30,41,59), 22));
        LinearLayout.LayoutParams ilp = new LinearLayout.LayoutParams(dp(74), dp(74));
        ilp.setMargins(0, 0, dp(12), 0);
        card.addView(photo, ilp);
        setImageFromData(photo, p.optString("photo_data", p.optString("photo", "")), p.optString("full_name", "P"));

        LinearLayout info = new LinearLayout(this);
        info.setOrientation(LinearLayout.VERTICAL);
        info.setLayoutParams(new LinearLayout.LayoutParams(0, -2, 1));
        info.addView(text(p.optString("full_name", p.optString("name", "Personel")), 20, WHITE, Typeface.BOLD));
        info.addView(text(p.optString("department", p.optString("role", "Personel")), 13, Color.rgb(148,163,184), Typeface.BOLD));
        String phone = p.optString("phone", p.optString("phone_number", ""));
        String address = p.optString("address", "");
        info.addView(text("☎ " + (phone.length() == 0 ? "Telefon eklenmedi" : phone), 14, Color.rgb(226,232,240), Typeface.BOLD));
        info.addView(text("⌂ " + (address.length() == 0 ? "Adres eklenmedi" : address), 13, Color.rgb(203,213,225), Typeface.NORMAL));
        String status = p.optString("attendance_status", p.optString("status", ""));
        if (status.length() > 0) info.addView(text("Durum: " + status, 12, Color.rgb(56,189,248), Typeface.BOLD));
        card.addView(info);
        return card;
    }

    void addBack() { Button back=btn("Ana Ekrana Dön", BLUE); root.addView(back); back.setOnClickListener(v -> { showPanel(); loadMe(); }); }

    void setImageFromData(ImageView img, String data, String initial) {
        if (img == null) return;
        try {
            if (data != null && data.startsWith("data:image")) {
                String base = data.substring(data.indexOf(",") + 1);
                byte[] bytes = Base64.decode(base, Base64.DEFAULT);
                Bitmap bmp = BitmapFactory.decodeByteArray(bytes, 0, bytes.length);
                img.setImageBitmap(bmp); return;
            }
        } catch (Exception ignored) {}
        img.setImageResource(getResources().getIdentifier("premium_logo", "drawable", getPackageName()));
    }

    void vibrate() { try { Vibrator v=(Vibrator)getSystemService(Context.VIBRATOR_SERVICE); if(v!=null) v.vibrate(120); } catch(Exception ignored) {} }
    String money(double d) { return String.format(java.util.Locale.US, "%.2f", d); }
    String enc(String s) throws Exception { return URLEncoder.encode(s == null ? "" : s, "UTF-8"); }
    String httpGet(String u) throws Exception { HttpURLConnection c=(HttpURLConnection)new URL(u).openConnection(); c.setRequestMethod("GET"); c.setConnectTimeout(20000); c.setReadTimeout(20000); return read(c); }
    String httpPost(String u, String form) throws Exception { HttpURLConnection c=(HttpURLConnection)new URL(u).openConnection(); c.setRequestMethod("POST"); c.setDoOutput(true); c.setRequestProperty("Content-Type","application/x-www-form-urlencoded; charset=UTF-8"); c.setConnectTimeout(20000); c.setReadTimeout(20000); OutputStream os=c.getOutputStream(); os.write(form.getBytes("UTF-8")); os.flush(); os.close(); return read(c); }
    String read(HttpURLConnection c) throws Exception { InputStream is=c.getResponseCode()>=400?c.getErrorStream():c.getInputStream(); BufferedReader br=new BufferedReader(new InputStreamReader(is,"UTF-8")); StringBuilder sb=new StringBuilder(); String line; while((line=br.readLine())!=null) sb.append(line); br.close(); return sb.toString(); }
}
