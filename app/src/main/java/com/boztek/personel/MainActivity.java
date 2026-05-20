package com.boztek.personel;

import android.Manifest;
import android.app.Activity;
import android.os.Bundle;
import android.os.Vibrator;
import android.content.Context;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.Bitmap;
import android.graphics.drawable.GradientDrawable;
import android.view.Gravity;
import android.widget.*;

import com.journeyapps.barcodescanner.BarcodeCallback;
import com.journeyapps.barcodescanner.BarcodeResult;
import com.journeyapps.barcodescanner.BarcodeView;
import com.google.zxing.ResultPoint;
import com.google.zxing.BarcodeFormat;
import com.google.zxing.common.BitMatrix;
import com.google.zxing.qrcode.QRCodeWriter;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public class MainActivity extends Activity {

    public static final String SERVER_URL = "https://adminpanel-wvp1.onrender.com";
    private static final int REQ_CAMERA = 77;

    LinearLayout root;
    SharedPreferences prefs;
    String token = "";

    TextView statusText, nameText, deptText, salaryValue, advanceValue, remainingValue, leaveValue;
    FrameLayout cameraBox;
    BarcodeView barcodeView;
    boolean entryMode = true;
    boolean busy = false;
    long lastScanTime = 0;

    final int BG1 = Color.rgb(8,17,31);
    final int BG2 = Color.rgb(15,23,42);
    final int WHITE = Color.WHITE;
    final int TEXT = Color.rgb(15,23,42);
    final int MUTED = Color.rgb(100,116,139);
    final int BLUE = Color.rgb(37,99,235);
    final int GREEN = Color.rgb(22,163,74);
    final int RED = Color.rgb(220,38,38);
    final int ORANGE = Color.rgb(245,158,11);

    @Override
    public void onCreate(Bundle b) {
        super.onCreate(b);
        prefs = getSharedPreferences("boztek", MODE_PRIVATE);
        token = prefs.getString("token", "");
        if (token.length() > 0) {
            showPanel();
            loadMe();
        } else {
            showLogin();
        }
    }

    @Override
    protected void onPause() {
        super.onPause();
        stopScannerOnly();
    }

    int dp(int v) {
        return (int)(v * getResources().getDisplayMetrics().density + 0.5f);
    }

    GradientDrawable round(int color, int radius) {
        GradientDrawable g = new GradientDrawable();
        g.setColor(color);
        g.setCornerRadius(dp(radius));
        return g;
    }

    GradientDrawable bg() {
        return new GradientDrawable(GradientDrawable.Orientation.TOP_BOTTOM, new int[]{BG1, BG2});
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

    LinearLayout card() {
        LinearLayout c = new LinearLayout(this);
        c.setOrientation(LinearLayout.VERTICAL);
        c.setPadding(dp(20), dp(20), dp(20), dp(20));
        c.setBackground(round(WHITE, 24));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.setMargins(0, dp(10), 0, dp(10));
        c.setLayoutParams(lp);
        return c;
    }

    Button btn(String s, int color) {
        Button b = new Button(this);
        b.setText(s);
        b.setTextSize(16);
        b.setTextColor(WHITE);
        b.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        b.setAllCaps(false);
        b.setBackground(round(color, 18));
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, dp(60));
        lp.setMargins(0, dp(7), 0, dp(7));
        b.setLayoutParams(lp);
        return b;
    }

    EditText input(String hint, boolean pass) {
        EditText e = new EditText(this);
        e.setHint(hint);
        e.setTextSize(18);
        e.setSingleLine(true);
        e.setPadding(dp(15), dp(13), dp(15), dp(13));
        e.setBackground(round(Color.rgb(248,250,252), 16));
        if (pass) e.setInputType(0x00000081);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-1, -2);
        lp.setMargins(0, dp(8), 0, dp(8));
        e.setLayoutParams(lp);
        return e;
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
        TextView title = text("Boztek Personel", 34, WHITE, Typeface.BOLD);
        title.setGravity(Gravity.CENTER);
        root.addView(title);
        TextView sub = text("Maaş • Avans • İzin • QR Giriş Çıkış", 16, Color.rgb(203,213,225), Typeface.NORMAL);
        sub.setGravity(Gravity.CENTER);
        root.addView(sub);

        LinearLayout c = card();
        c.addView(text("Personel Girişi", 25, TEXT, Typeface.BOLD));
        EditText u = input("Kullanıcı adı", false);
        EditText p = input("Şifre", true);
        Button login = btn("Giriş Yap", BLUE);
        statusText = text("", 15, RED, Typeface.BOLD);

        c.addView(u);
        c.addView(p);
        c.addView(login);
        c.addView(statusText);
        root.addView(c);

        login.setOnClickListener(v -> {
            String user = u.getText().toString().trim();
            String pass = p.getText().toString().trim();
            if (user.length() == 0 || pass.length() == 0) {
                statusText.setText("Kullanıcı adı ve şifre gir.");
                return;
            }
            doLogin(user, pass);
        });
    }

    void showPanel() {
        makeRoot();
        root.addView(text("Boztek Personel", 32, WHITE, Typeface.BOLD));
        root.addView(text("Kişisel bilgiler ve QR giriş/çıkış", 15, Color.rgb(203,213,225), Typeface.NORMAL));

        LinearLayout profile = card();
        nameText = text("-", 29, TEXT, Typeface.BOLD);
        deptText = text("-", 17, MUTED, Typeface.BOLD);
        profile.addView(nameText);
        profile.addView(deptText);
        root.addView(profile);

        LinearLayout s = card();
        s.addView(text("Maaş", 15, BLUE, Typeface.BOLD));
        salaryValue = text("-", 30, TEXT, Typeface.BOLD);
        s.addView(salaryValue);
        root.addView(s);

        LinearLayout a = card();
        a.addView(text("Toplam Avans", 15, ORANGE, Typeface.BOLD));
        advanceValue = text("-", 30, TEXT, Typeface.BOLD);
        a.addView(advanceValue);
        root.addView(a);

        LinearLayout r = card();
        r.addView(text("Kalan Maaş", 15, GREEN, Typeface.BOLD));
        remainingValue = text("-", 32, GREEN, Typeface.BOLD);
        r.addView(remainingValue);
        root.addView(r);

        LinearLayout l = card();
        l.addView(text("Kalan Yıllık İzin", 15, BLUE, Typeface.BOLD));
        leaveValue = text("-", 30, BLUE, Typeface.BOLD);
        l.addView(leaveValue);
        root.addView(l);

        Button refresh = btn("Verileri Yenile", BLUE);
        Button myQr = btn("Bana Ait Barkodu Göster", BLUE);
        Button qrEntry = btn("QR Giriş Kamerası", GREEN);
        Button qrExit = btn("QR Çıkış Kamerası", RED);
        Button adv = btn("Avans Geçmişi", ORANGE);
        Button leaveReq = btn("İzin Talebi Gönder", GREEN);
        Button nots = btn("Bildirimler", BLUE);
        Button logout = btn("Çıkış Yap", RED);
        statusText = text("", 15, Color.rgb(203,213,225), Typeface.BOLD);

        root.addView(refresh);
        root.addView(myQr);
        root.addView(qrEntry);
        root.addView(qrExit);
        root.addView(adv);
        root.addView(leaveReq);
        root.addView(nots);
        root.addView(logout);
        root.addView(statusText);

        refresh.setOnClickListener(v -> loadMe());
        myQr.setOnClickListener(v -> showMyBarcode());
        qrEntry.setOnClickListener(v -> showQr(true));
        qrExit.setOnClickListener(v -> showQr(false));
        adv.setOnClickListener(v -> loadAdvances());
        leaveReq.setOnClickListener(v -> showLeaveRequest());
        nots.setOnClickListener(v -> loadNotifications());
        logout.setOnClickListener(v -> {
            prefs.edit().clear().apply();
            token = "";
            showLogin();
        });
    }

    void doLogin(String u, String p) {
        statusText.setText("Giriş yapılıyor...");
        new Thread(() -> {
            try {
                String res = httpGet(SERVER_URL + "/api/employee-login?username=" + enc(u) + "&password=" + enc(p));
                JSONObject o = new JSONObject(res);
                if (o.optString("status").equals("ok")) {
                    token = o.getString("token");
                    prefs.edit().putString("token", token).apply();
                    runOnUiThread(() -> {
                        showPanel();
                        fill(o.optJSONObject("person"));
                    });
                } else {
                    runOnUiThread(() -> statusText.setText(o.optString("message", "Giriş başarısız")));
                }
            } catch (Exception e) {
                runOnUiThread(() -> statusText.setText("Bağlantı hatası: " + e.getMessage()));
            }
        }).start();
    }

    void loadMe() {
        statusText.setText("Veriler yenileniyor...");
        new Thread(() -> {
            try {
                JSONObject o = new JSONObject(httpGet(SERVER_URL + "/api/employee-me?token=" + enc(token)));
                if (o.optString("status").equals("ok")) {
                    runOnUiThread(() -> fill(o.optJSONObject("person")));
                } else {
                    runOnUiThread(() -> {
                        prefs.edit().clear().apply();
                        showLogin();
                    });
                }
            } catch (Exception e) {
                runOnUiThread(() -> statusText.setText("Bağlantı hatası"));
            }
        }).start();
    }

    void fill(JSONObject p) {
        if (p == null) return;
        nameText.setText(p.optString("full_name", "-"));
        deptText.setText(p.optString("department", "-"));
        salaryValue.setText(money(p.optDouble("salary", 0)) + " TL");
        advanceValue.setText(money(p.optDouble("total_advance", 0)) + " TL");
        remainingValue.setText(money(p.optDouble("remaining_salary", 0)) + " TL");
        leaveValue.setText(p.optInt("annual_leave_remaining", 0) + " gün");
        statusText.setText("Güncel veri alındı");
    }

    void showMyBarcode() {
        makeRoot();
        root.addView(text("Kişisel Barkodum", 30, WHITE, Typeface.BOLD));
        root.addView(text("Bu barkod sadece senin hesabın için geçerlidir.", 15, Color.rgb(203,213,225), Typeface.NORMAL));
        statusText = text("Barkod serverdan alınıyor...", 15, Color.rgb(203,213,225), Typeface.BOLD);
        root.addView(statusText);

        LinearLayout c = card();
        ImageView img = new ImageView(this);
        c.addView(img, new LinearLayout.LayoutParams(-1, dp(300)));
        root.addView(c);

        Button back = btn("Ana Ekrana Dön", BLUE);
        root.addView(back);
        back.setOnClickListener(v -> { showPanel(); loadMe(); });

        new Thread(() -> {
            try {
                JSONObject o = new JSONObject(httpGet(SERVER_URL + "/api/my-qr?token=" + enc(token)));
                if ("ok".equals(o.optString("status"))) {
                    String qr = o.optString("qr_text", "");
                    Bitmap bm = makeQrBitmap(qr, 900, 900);
                    runOnUiThread(() -> {
                        img.setImageBitmap(bm);
                        statusText.setText("Barkod hazır");
                    });
                } else {
                    runOnUiThread(() -> statusText.setText(o.optString("message", "Barkod alınamadı")));
                }
            } catch (Exception e) {
                runOnUiThread(() -> statusText.setText("Barkod alınamadı: " + e.getMessage()));
            }
        }).start();
    }

    Bitmap makeQrBitmap(String text, int w, int h) throws Exception {
        BitMatrix matrix = new QRCodeWriter().encode(text, BarcodeFormat.QR_CODE, w, h);
        Bitmap bmp = Bitmap.createBitmap(w, h, Bitmap.Config.RGB_565);
        for (int x = 0; x < w; x++) {
            for (int y = 0; y < h; y++) {
                bmp.setPixel(x, y, matrix.get(x, y) ? Color.BLACK : Color.WHITE);
            }
        }
        return bmp;
    }

    void showQr(boolean entry) {
        entryMode = entry;
        makeRoot();
        root.addView(text(entry ? "QR Giriş" : "QR Çıkış", 32, WHITE, Typeface.BOLD));
        root.addView(text("Sadece server tarafından üretilen kişiye özel barkod kabul edilir", 15, Color.rgb(203,213,225), Typeface.NORMAL));

        statusText = text("Kamera başlatılıyor...", 15, Color.rgb(203,213,225), Typeface.BOLD);
        root.addView(statusText);

        cameraBox = new FrameLayout(this);
        cameraBox.setBackground(round(Color.rgb(2,6,23), 26));
        LinearLayout.LayoutParams camLp = new LinearLayout.LayoutParams(-1, dp(380));
        camLp.setMargins(0, dp(12), 0, dp(12));
        root.addView(cameraBox, camLp);

        Button start = btn("Kamerayı Başlat", BLUE);
        Button stop = btn("Kamerayı Kapat", ORANGE);
        Button back = btn("Ana Ekrana Dön", RED);

        root.addView(start);
        root.addView(stop);
        root.addView(back);

        LinearLayout info = card();
        info.addView(text("Güvenli QR Sistemi", 21, TEXT, Typeface.BOLD));
        info.addView(text("QR içeriği server token ile kontrol edilir.", 15, MUTED, Typeface.NORMAL));
        info.addView(text("Başkasına ait barkod okutulursa kayıt reddedilir.", 15, MUTED, Typeface.NORMAL));
        root.addView(info);

        start.setOnClickListener(v -> startScanner());
        stop.setOnClickListener(v -> stopScanner());
        back.setOnClickListener(v -> {
            stopScannerOnly();
            showPanel();
            loadMe();
        });

        startScanner();
    }

    void startScanner() {
        if (android.os.Build.VERSION.SDK_INT >= 23) {
            if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
                requestPermissions(new String[]{Manifest.permission.CAMERA}, REQ_CAMERA);
                return;
            }
        }

        try {
            cameraBox.removeAllViews();
            barcodeView = new BarcodeView(this);
            cameraBox.addView(barcodeView, new FrameLayout.LayoutParams(-1, -1));
            barcodeView.decodeContinuous(callback);
            barcodeView.resume();
            busy = false;
            statusText.setText("Kamera açık. QR okut.");
        } catch (Exception e) {
            statusText.setText("Kamera açılamadı: " + e.getMessage());
            showCameraClosed("KAMERA AÇILAMADI");
        }
    }

    void stopScannerOnly() {
        try {
            if (barcodeView != null) barcodeView.pause();
        } catch (Exception ignored) {}
        busy = false;
    }

    void stopScanner() {
        stopScannerOnly();
        showCameraClosed("KAMERA KAPALI");
        statusText.setText("Kamera kapalı.");
    }

    void showCameraClosed(String msg) {
        if (cameraBox == null) return;
        cameraBox.removeAllViews();
        TextView t = text(msg, 24, Color.rgb(148,163,184), Typeface.BOLD);
        t.setGravity(Gravity.CENTER);
        cameraBox.addView(t, new FrameLayout.LayoutParams(-1, -1));
    }

    BarcodeCallback callback = new BarcodeCallback() {
        @Override
        public void barcodeResult(BarcodeResult result) {
            if (result == null || result.getText() == null) return;
            long now = System.currentTimeMillis();
            if (busy || now - lastScanTime < 2500) return;

            String raw = result.getText().trim();
            if (raw.length() < 8) {
                statusText.setText("Geçersiz barkod");
                lastScanTime = now;
                return;
            }

            busy = true;
            lastScanTime = now;
            vibrate();
            sendQrEvent(raw, entryMode);
        }

        @Override
        public void possibleResultPoints(List<ResultPoint> resultPoints) {}
    };

    int parsePersonId(String raw) {
        try {
            if (raw == null) return -1;
            raw = raw.trim();

            if (raw.matches("\\d+")) return Integer.parseInt(raw);

            String[] keys = {"person_id=", "personId=", "person=", "pid=", "id="};
            for (String key : keys) {
                int idx = raw.indexOf(key);
                if (idx >= 0) {
                    String part = raw.substring(idx + key.length());
                    int amp = part.indexOf("&");
                    if (amp >= 0) part = part.substring(0, amp);
                    part = part.replaceAll("[^0-9]", "");
                    if (part.length() > 0) return Integer.parseInt(part);
                }
            }

            Matcher m = Pattern.compile("(\\d+)").matcher(raw);
            int last = -1;
            while (m.find()) {
                last = Integer.parseInt(m.group(1));
            }
            return last;
        } catch (Exception e) {
            return -1;
        }
    }

    void sendQrEvent(String qrText, boolean entry) {
        statusText.setText(entry ? "Güvenli giriş doğrulanıyor..." : "Güvenli çıkış doğrulanıyor...");
        new Thread(() -> {
            try {
                String action = entry ? "entry" : "exit";
                String form = "token=" + enc(token) + "&qr_text=" + enc(qrText) + "&action=" + enc(action);
                String res = httpPost(SERVER_URL + "/api/qr/verify", form);
                JSONObject obj = new JSONObject(res);

                runOnUiThread(() -> {
                    busy = false;
                    if ("ok".equals(obj.optString("status"))) {
                        statusText.setText(obj.optString("message", entry ? "Giriş kaydedildi" : "Çıkış kaydedildi"));
                    } else {
                        statusText.setText(obj.optString("message", "Bu barkod bu kullanıcıya ait değil"));
                    }
                });
            } catch (Exception e) {
                runOnUiThread(() -> {
                    busy = false;
                    statusText.setText("Server bağlantı hatası: " + e.getMessage());
                });
            }
        }).start();
    }

    void loadAdvances() {
        makeRoot();
        root.addView(text("Avans Geçmişi", 30, WHITE, Typeface.BOLD));
        statusText = text("Avans geçmişi alınıyor...", 15, Color.rgb(203,213,225), Typeface.BOLD);
        root.addView(statusText);

        new Thread(() -> {
            try {
                JSONObject o = new JSONObject(httpGet(SERVER_URL + "/api/employee-advances?token=" + enc(token)));
                JSONArray arr = o.optJSONArray("advances");
                runOnUiThread(() -> {
                    statusText.setText("Avans geçmişi");
                    if (arr != null) {
                        for (int i = 0; i < arr.length(); i++) {
                            JSONObject a = arr.optJSONObject(i);
                            LinearLayout c = card();
                            c.addView(text(money(a.optDouble("amount",0)) + " TL", 25, ORANGE, Typeface.BOLD));
                            c.addView(text(a.optString("status",""), 16, MUTED, Typeface.BOLD));
                            root.addView(c);
                        }
                    }
                    Button back = btn("Ana Ekrana Dön", BLUE);
                    root.addView(back);
                    back.setOnClickListener(v -> { showPanel(); loadMe(); });
                });
            } catch (Exception e) {
                runOnUiThread(() -> statusText.setText("Avanslar alınamadı"));
            }
        }).start();
    }

    void showLeaveRequest() {
        makeRoot();
        root.addView(text("İzin Talebi", 30, WHITE, Typeface.BOLD));
        LinearLayout c = card();
        EditText start = input("Başlangıç: 2026-05-20", false);
        EditText end = input("Bitiş: 2026-05-21", false);
        EditText note = input("Not", false);
        Button send = btn("Talep Gönder", GREEN);
        c.addView(start);
        c.addView(end);
        c.addView(note);
        c.addView(send);
        root.addView(c);

        statusText = text("", 15, Color.rgb(203,213,225), Typeface.BOLD);
        root.addView(statusText);

        Button back = btn("Ana Ekrana Dön", BLUE);
        root.addView(back);
        back.setOnClickListener(v -> { showPanel(); loadMe(); });

        send.setOnClickListener(v -> sendLeaveRequest(
                start.getText().toString().trim(),
                end.getText().toString().trim(),
                note.getText().toString().trim()
        ));
    }

    void sendLeaveRequest(String s, String e, String n) {
        statusText.setText("Talep gönderiliyor...");
        new Thread(() -> {
            try {
                String form = "token=" + enc(token) + "&start_date=" + enc(s) + "&end_date=" + enc(e) + "&note=" + enc(n);
                String res = httpPost(SERVER_URL + "/api/employee-leave-request", form);
                JSONObject o = new JSONObject(res);
                runOnUiThread(() -> statusText.setText(o.optString("message", "Talep gönderildi")));
            } catch (Exception ex) {
                runOnUiThread(() -> statusText.setText("Talep gönderilemedi"));
            }
        }).start();
    }

    void loadNotifications() {
        makeRoot();
        root.addView(text("Bildirimler", 30, WHITE, Typeface.BOLD));
        statusText = text("Bildirimler alınıyor...", 15, Color.rgb(203,213,225), Typeface.BOLD);
        root.addView(statusText);

        new Thread(() -> {
            try {
                JSONObject o = new JSONObject(httpGet(SERVER_URL + "/api/employee-notifications?token=" + enc(token)));
                JSONArray arr = o.optJSONArray("notifications");
                runOnUiThread(() -> {
                    statusText.setText("Bildirimler");
                    if (arr != null) {
                        for (int i = 0; i < arr.length(); i++) {
                            JSONObject n = arr.optJSONObject(i);
                            LinearLayout c = card();
                            c.addView(text(n.optString("event_type","Bildirim"), 20, BLUE, Typeface.BOLD));
                            c.addView(text(n.optString("message",""), 16, TEXT, Typeface.BOLD));
                            c.addView(text(n.optString("created_at",""), 14, MUTED, Typeface.NORMAL));
                            root.addView(c);
                        }
                    }
                    Button back = btn("Ana Ekrana Dön", BLUE);
                    root.addView(back);
                    back.setOnClickListener(v -> { showPanel(); loadMe(); });
                });
            } catch (Exception e) {
                runOnUiThread(() -> statusText.setText("Bildirimler alınamadı"));
            }
        }).start();
    }

    void vibrate() {
        try {
            Vibrator v = (Vibrator) getSystemService(Context.VIBRATOR_SERVICE);
            if (v != null) v.vibrate(120);
        } catch (Exception ignored) {}
    }

    String money(double d) {
        return String.format(java.util.Locale.US, "%.2f", d);
    }

    String enc(String s) throws Exception {
        return URLEncoder.encode(s, "UTF-8");
    }

    String httpGet(String u) throws Exception {
        HttpURLConnection c = (HttpURLConnection)new URL(u).openConnection();
        c.setRequestMethod("GET");
        c.setConnectTimeout(20000);
        c.setReadTimeout(20000);
        return read(c);
    }

    String httpPost(String u, String form) throws Exception {
        HttpURLConnection c = (HttpURLConnection)new URL(u).openConnection();
        c.setRequestMethod("POST");
        c.setDoOutput(true);
        c.setRequestProperty("Content-Type", "application/x-www-form-urlencoded; charset=UTF-8");
        c.setConnectTimeout(20000);
        c.setReadTimeout(20000);
        OutputStream os = c.getOutputStream();
        os.write(form.getBytes("UTF-8"));
        os.flush();
        os.close();
        return read(c);
    }

    String read(HttpURLConnection c) throws Exception {
        InputStream is = c.getResponseCode() >= 400 ? c.getErrorStream() : c.getInputStream();
        BufferedReader br = new BufferedReader(new InputStreamReader(is, "UTF-8"));
        StringBuilder sb = new StringBuilder();
        String line;
        while ((line = br.readLine()) != null) sb.append(line);
        br.close();
        return sb.toString();
    }
}
