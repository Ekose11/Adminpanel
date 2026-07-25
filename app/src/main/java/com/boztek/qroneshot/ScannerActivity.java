package com.boztek.qroneshot;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.graphics.Color;
import android.view.Gravity;
import android.widget.LinearLayout;
import android.widget.TextView;

import com.journeyapps.barcodescanner.BarcodeCallback;
import com.journeyapps.barcodescanner.BarcodeResult;
import com.journeyapps.barcodescanner.DecoratedBarcodeView;

import java.util.List;

public class ScannerActivity extends Activity {

    private DecoratedBarcodeView barcodeView;
    private boolean handled = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(Color.BLACK);

        TextView title = new TextView(this);
        title.setText("QR kodu kameraya göster");
        title.setTextColor(Color.WHITE);
        title.setTextSize(19);
        title.setGravity(Gravity.CENTER);
        title.setPadding(16, 24, 16, 24);
        root.addView(title, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                LinearLayout.LayoutParams.WRAP_CONTENT
        ));

        barcodeView = new DecoratedBarcodeView(this);
        barcodeView.setStatusText("İlk okumadan sonra kamera otomatik kapanır");
        root.addView(barcodeView, new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT,
                0,
                1f
        ));

        setContentView(root);

        barcodeView.decodeSingle(new BarcodeCallback() {
            @Override
            public void barcodeResult(BarcodeResult result) {
                if (handled || result == null || result.getText() == null) {
                    return;
                }

                handled = true;
                barcodeView.pauseAndWait();

                Intent data = new Intent();
                data.putExtra("qr_value", result.getText().trim());
                setResult(RESULT_OK, data);

                // İlk okumada tarayıcı ekranını kesin olarak kapat.
                finish();
            }

            @Override
            public void possibleResultPoints(List resultPoints) {
            }
        });
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (!handled && barcodeView != null) {
            barcodeView.resume();
        }
    }

    @Override
    protected void onPause() {
        if (barcodeView != null) {
            barcodeView.pauseAndWait();
        }
        super.onPause();
    }

    @Override
    public void onBackPressed() {
        setResult(RESULT_CANCELED);
        finish();
    }
}
