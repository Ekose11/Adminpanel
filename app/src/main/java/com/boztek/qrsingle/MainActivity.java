package com.boztek.qrsingle;

import android.Manifest;
import android.app.Activity;
import android.os.Bundle;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.widget.*;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.util.concurrent.atomic.AtomicBoolean;

import org.json.JSONArray;
import org.json.JSONObject;

public class MainActivity extends Activity {

    public static final String SERVER_URL = "https://adminpanel-wvpi.onrender.com";

    private static final int REQ_CAMERA = 44;
    private static final int REQ_SCAN = 45;

    LinearLayout root;
    LinearLayout list;
    TextView statusText;
    TextView modeText;
    Button scanButton;

    boolean entryMode = true;
    private final AtomicBoolean scanInProgress = new AtomicBoolean(false);
    private final AtomicBoolean sending = new AtomicBoolean(false);

    final int BG1 = Color.rgb(8, 17, 31);
    final int BG2 = Color.rgb(15, 23, 42);
    final int TEXT = Color.rgb(15, 23, 42);
    final int MUTED = Color.rgb(100, 116, 139);
    final int BLUE = Color.rgb(37, 99, 235);
    final int GREEN = Color.rgb(22, 163, 74);
    final int RED = Color.rgb(220, 38, 38);
    final int ORANGE = Color.rgb(245, 158, 11);

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        buildUi();
        loadPeople();
    }

    int dp(int value) {
        return (int) (value * getResources().getDisplayMetrics().density + 0.5f);
    }

    GradientDrawable round(int color, int radius) {
        GradientDrawable drawable = new GradientDrawable();
        drawable.setColor(color);
        drawable.setCornerRadius(dp(radius));
        return drawable;
    }

    GradientDrawable background() {
        return new GradientDrawable(
                GradientDrawable.Orientation.TOP_BOTTOM,
                new int[]{BG1, BG2}
        );
    }

    TextView text(String value, int size, int color, int style) {
        TextView view = new TextView(this);
        view.setText(value);
        view.setTextSize(size);
        view.setTextColor(color);
        view.setTypeface(Typeface.DEFAULT, style);
        view.setPadding(0, dp(4), 0, dp(4));
        return view;
    }

    LinearLayout card() {
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setPadding(dp(18), dp(18), dp(18), dp(18));
        layout.setBackground(round(Color.WHITE, 24));

        LinearLayout.LayoutParams params =
                new LinearLayout.LayoutParams(-1, -2);
        params.setMargins(0, dp(10), 0, dp(10));
        layout.setLayoutParams(params);

        return layout;
    }

    Button button(String value, int color) {
        Button button = new Button(this);
        button.setText(value);
        button.setTextSize(17);
        button.setTextColor(Color.WHITE);
        button.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        button.setAllCaps(false);
        button.setBackground(round(color, 16));
        return button;
    }

    void buildUi() {
        ScrollView scrollView = new ScrollView(this);
        scrollView.setBackground(background());

        root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setPadding(dp(20), dp(26), dp(20), dp(26));

        scrollView.addView(root);
        setContentView(scrollView);

        root.addView(text(
                "Boztek QR Tek Kayıt",
                31,
                Color.WHITE,
                Typeface.BOLD
        ));

        root.addView(text(
                "Giriş modunda 1 giriş, çıkış modunda 1 çıkış",
                16,
                Color.rgb(203, 213, 225),
                Typeface.NORMAL
        ));

        statusText = text(
                "Hazır",
                15,
                Color.rgb(203, 213, 225),
                Typeface.BOLD
        );
        root.addView(statusText);

        LinearLayout modeCard = card();
        modeText = text("Mod: GİRİŞ", 24, GREEN, Typeface.BOLD);
        modeCard.addView(modeText);

        LinearLayout modeRow = new LinearLayout(this);
        modeRow.setOrientation(LinearLayout.HORIZONTAL);
        modeRow.setPadding(0, dp(12), 0, 0);

        Button entryButton = button("Giriş Modu", GREEN);
        Button exitButton = button("Çıkış Modu", RED);

        LinearLayout.LayoutParams leftParams =
                new LinearLayout.LayoutParams(0, dp(58), 1);
        leftParams.setMargins(0, 0, dp(6), 0);

        LinearLayout.LayoutParams rightParams =
                new LinearLayout.LayoutParams(0, dp(58), 1);
        rightParams.setMargins(dp(6), 0, 0, 0);

        modeRow.addView(entryButton, leftParams);
        modeRow.addView(exitButton, rightParams);
        modeCard.addView(modeRow);
        root.addView(modeCard);

        entryButton.setOnClickListener(view -> {
            if (sending.get() || scanInProgress.get()) {
                return;
            }
            entryMode = true;
            modeText.setText("Mod: GİRİŞ");
            modeText.setTextColor(GREEN);
        });

        exitButton.setOnClickListener(view -> {
            if (sending.get() || scanInProgress.get()) {
                return;
            }
            entryMode = false;
            modeText.setText("Mod: ÇIKIŞ");
            modeText.setTextColor(RED);
        });

        scanButton = button("QR OKUT", BLUE);
        LinearLayout.LayoutParams scanParams =
                new LinearLayout.LayoutParams(-1, dp(70));
        scanParams.setMargins(0, dp(10), 0, dp(10));
        root.addView(scanButton, scanParams);

        scanButton.setOnClickListener(view -> startQr());

        Button refreshButton = button("Personelleri Yenile", ORANGE);
        LinearLayout.LayoutParams refreshParams =
                new LinearLayout.LayoutParams(-1, dp(58));
        refreshParams.setMargins(0, dp(4), 0, dp(12));
        root.addView(refreshButton, refreshParams);

        refreshButton.setOnClickListener(view -> loadPeople());

        LinearLayout header = card();
        header.addView(text(
                "Personel Listesi",
                24,
                TEXT,
                Typeface.BOLD
        ));
        header.addView(text(
                "QR içeriği: 1 veya person_id=1",
                15,
                MUTED,
                Typeface.NORMAL
        ));
        root.addView(header);

        list = new LinearLayout(this);
        list.setOrientation(LinearLayout.VERTICAL);
        root.addView(list);
    }

    void startQr() {
        if (!scanInProgress.compareAndSet(false, true)) {
            return;
        }

        if (sending.get()) {
            scanInProgress.set(false);
            return;
        }

        if (android.os.Build.VERSION.SDK_INT >= 23
                && checkSelfPermission(Manifest.permission.CAMERA)
                != PackageManager.PERMISSION_GRANTED) {

            scanInProgress.set(false);
            requestPermissions(
                    new String[]{Manifest.permission.CAMERA},
                    REQ_CAMERA
            );
            return;
        }

        scanButton.setEnabled(false);
        statusText.setText("Kamera açılıyor...");

        Intent intent = new Intent(this, ScannerActivity.class);
        startActivityForResult(intent, REQ_SCAN);
    }

    @Override
    public void onRequestPermissionsResult(
            int requestCode,
            String[] permissions,
            int[] grantResults
    ) {
        super.onRequestPermissionsResult(
                requestCode,
                permissions,
                grantResults
        );

        if (requestCode == REQ_CAMERA) {
            if (grantResults.length > 0
                    && grantResults[0]
                    == PackageManager.PERMISSION_GRANTED) {
                startQr();
            } else {
                statusText.setText("Kamera izni verilmedi.");
            }
        }
    }

    @Override
    protected void onActivityResult(
            int requestCode,
            int resultCode,
            Intent data
    ) {
        super.onActivityResult(requestCode, resultCode, data);

        if (requestCode != REQ_SCAN) {
            return;
        }

        scanInProgress.set(false);
        scanButton.setEnabled(true);

        if (resultCode != RESULT_OK || data == null) {
            statusText.setText("QR okuma iptal edildi.");
            return;
        }

        String raw = data.getStringExtra("qr_value");

        if (raw == null || raw.trim().isEmpty()) {
            statusText.setText("QR boş veya geçersiz.");
            return;
        }

        int personId = parsePersonId(raw.trim());

        if (personId <= 0) {
            statusText.setText("QR geçersiz: " + raw);
            return;
        }

        sendEvent(personId, entryMode);
    }

    int parsePersonId(String raw) {
        try {
            if (raw.matches("\\d+")) {
                return Integer.parseInt(raw);
            }

            String key = "person_id=";
            int index = raw.indexOf(key);

            if (index >= 0) {
                String value = raw.substring(index + key.length());
                int ampersand = value.indexOf("&");

                if (ampersand >= 0) {
                    value = value.substring(0, ampersand);
                }

                return Integer.parseInt(value.trim());
            }

            key = "id=";
            index = raw.indexOf(key);

            if (index >= 0) {
                String value = raw.substring(index + key.length());
                int ampersand = value.indexOf("&");

                if (ampersand >= 0) {
                    value = value.substring(0, ampersand);
                }

                return Integer.parseInt(value.trim());
            }
        } catch (Exception ignored) {
            return -1;
        }

        return -1;
    }

    void loadPeople() {
        statusText.setText("Personeller yenileniyor...");

        new Thread(() -> {
            try {
                String response = httpGet(
                        SERVER_URL + "/api/personnel"
                );

                JSONArray people = new JSONArray(response);

                runOnUiThread(() -> {
                    list.removeAllViews();

                    for (int i = 0; i < people.length(); i++) {
                        JSONObject person = people.optJSONObject(i);

                        if (person != null) {
                            addPersonCard(person);
                        }
                    }

                    statusText.setText(
                            "Güncellendi. Personel: "
                                    + people.length()
                    );
                });
            } catch (Exception error) {
                runOnUiThread(() ->
                        statusText.setText(
                                "Server bağlantı hatası: "
                                        + error.getMessage()
                        )
                );
            }
        }).start();
    }

    void addPersonCard(JSONObject person) {
        int id = person.optInt("id");
        String name = person.optString("full_name", "-");
        String department =
                person.optString("department", "-");

        int days = person.optInt("monthly_days", 0);
        int leave =
                person.optInt("annual_leave_remaining", 0);

        LinearLayout personCard = card();

        personCard.addView(text(
                name,
                24,
                TEXT,
                Typeface.BOLD
        ));

        personCard.addView(text(
                department,
                16,
                MUTED,
                Typeface.BOLD
        ));

        personCard.addView(text(
                "ID: " + id
                        + " • Bu ay: " + days
                        + " gün • Kalan izin: "
                        + leave + " gün",
                15,
                MUTED,
                Typeface.NORMAL
        ));

        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setPadding(0, dp(12), 0, 0);

        Button entryButton = button("GİRİŞ", GREEN);
        Button exitButton = button("ÇIKIŞ", RED);

        LinearLayout.LayoutParams leftParams =
                new LinearLayout.LayoutParams(0, dp(58), 1);
        leftParams.setMargins(0, 0, dp(6), 0);

        LinearLayout.LayoutParams rightParams =
                new LinearLayout.LayoutParams(0, dp(58), 1);
        rightParams.setMargins(dp(6), 0, 0, 0);

        row.addView(entryButton, leftParams);
        row.addView(exitButton, rightParams);
        personCard.addView(row);

        entryButton.setOnClickListener(
                view -> sendEvent(id, true)
        );

        exitButton.setOnClickListener(
                view -> sendEvent(id, false)
        );

        list.addView(personCard);
    }

    void sendEvent(int personId, boolean entry) {
        if (!sending.compareAndSet(false, true)) {
            return;
        }

        scanButton.setEnabled(false);

        statusText.setText(
                entry
                        ? "Giriş gönderiliyor..."
                        : "Çıkış gönderiliyor..."
        );

        new Thread(() -> {
            try {
                String path =
                        entry ? "/api/entry" : "/api/exit";

                String form =
                        "person_id="
                                + encode(
                                String.valueOf(personId)
                        );

                String response = httpPost(
                        SERVER_URL + path,
                        form
                );

                JSONObject result =
                        new JSONObject(response);

                runOnUiThread(() -> {
                    sending.set(false);
                    scanButton.setEnabled(true);

                    if ("ok".equals(
                            result.optString("status")
                    )) {
                        statusText.setText(
                                (entry
                                        ? "Tek giriş kaydedildi"
                                        : "Tek çıkış kaydedildi")
                                        + " • ID: "
                                        + personId
                        );
                    } else {
                        statusText.setText(
                                result.optString(
                                        "message",
                                        "Kayıt hatası"
                                )
                        );
                    }
                });
            } catch (Exception error) {
                runOnUiThread(() -> {
                    sending.set(false);
                    scanButton.setEnabled(true);

                    statusText.setText(
                            "Server bağlantı hatası: "
                                    + error.getMessage()
                    );
                });
            }
        }).start();
    }

    String encode(String value) throws Exception {
        return URLEncoder.encode(value, "UTF-8");
    }

    String httpGet(String urlValue) throws Exception {
        String separator =
                urlValue.contains("?") ? "&" : "?";

        HttpURLConnection connection =
                (HttpURLConnection) new URL(
                        urlValue
                                + separator
                                + "_t="
                                + System.currentTimeMillis()
                ).openConnection();

        connection.setRequestMethod("GET");
        connection.setConnectTimeout(20000);
        connection.setReadTimeout(20000);

        return read(connection);
    }

    String httpPost(
            String urlValue,
            String form
    ) throws Exception {

        HttpURLConnection connection =
                (HttpURLConnection) new URL(
                        urlValue
                ).openConnection();

        connection.setRequestMethod("POST");
        connection.setDoOutput(true);
        connection.setConnectTimeout(20000);
        connection.setReadTimeout(20000);

        connection.setRequestProperty(
                "Content-Type",
                "application/x-www-form-urlencoded; charset=UTF-8"
        );

        OutputStream outputStream =
                connection.getOutputStream();

        outputStream.write(
                form.getBytes("UTF-8")
        );
        outputStream.flush();
        outputStream.close();

        return read(connection);
    }

    String read(
            HttpURLConnection connection
    ) throws Exception {

        InputStream inputStream =
                connection.getResponseCode() >= 400
                        ? connection.getErrorStream()
                        : connection.getInputStream();

        if (inputStream == null) {
            throw new Exception(
                    "Server boş cevap verdi"
            );
        }

        BufferedReader reader =
                new BufferedReader(
                        new InputStreamReader(
                                inputStream,
                                "UTF-8"
                        )
                );

        StringBuilder result =
                new StringBuilder();

        String line;

        while ((line = reader.readLine()) != null) {
            result.append(line);
        }

        reader.close();
        return result.toString();
    }
}
