package com.smkpenerbangan.exambrowser;

import android.Manifest;
import android.app.Activity;
import android.app.AlertDialog;
import android.app.admin.DevicePolicyManager;
import android.content.ComponentName;
import android.content.Context;
import android.content.pm.PackageManager;
import android.content.res.Configuration;
import android.graphics.Color;
import android.graphics.Matrix;
import android.graphics.SurfaceTexture;
import android.graphics.drawable.GradientDrawable;
import android.hardware.Camera;
import android.os.Build;
import android.os.Bundle;
import android.os.Message;
import android.text.InputType;
import android.text.TextUtils;
import android.util.Log;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.MotionEvent;
import android.view.Surface;
import android.view.TextureView;
import android.view.View;
import android.view.ViewGroup;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.view.WindowManager;
import android.webkit.CookieManager;
import android.webkit.JsResult;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebStorage;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.TextView;
import android.widget.Toast;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.net.URL;
import java.util.List;

public class MainActivity extends Activity {

    private static final int REQ_CAMERA = 1001;
    private static final int MATCH = ViewGroup.LayoutParams.MATCH_PARENT;
    private static final String TAG = "XBrowser";

    private FrameLayout root;
    private WebView web;
    private TextureView camView;
    private View camBox;
    private Camera camera;
    private int mCameraId = -1;

    private JSONObject cfg;
    private String exitWord = "KELUAR";
    private String allowedHost = "";
    private boolean cameraEnabled = true;
    private boolean blockScreenshots = true;
    private int exitBackTaps = 2;
    private boolean clearDataOnExit = true;
    private int backTapCount = 0;
    private long lastBackTime = 0L;

    private int overlayWpx;
    private int overlayHpx;

    private int dragDownX, dragDownY, startLeft, startTop;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        cfg = readConfig();
        exitWord = cfg.optString("exit_word", "KELUAR");
        cameraEnabled = cfg.optBoolean("camera_enabled", true);
        blockScreenshots = cfg.optBoolean("block_screenshots", true);
        exitBackTaps = Math.max(1, cfg.optInt("exit_back_taps", 2));
        clearDataOnExit = cfg.optBoolean("clear_data_on_exit", true);
        int[] camSize = intArray(cfg.optJSONArray("camera_size"), new int[]{160, 120});

        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        if (blockScreenshots) {
            getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);
        }

        root = new FrameLayout(this);
        root.setBackgroundColor(Color.BLACK);
        setContentView(root);
        goImmersive();
        enterLockTask();

        overlayWpx = dp(camSize[0]);
        overlayHpx = dp(camSize[1]);

        setupWebView();
        addMarquee();
        addExitHotspot();

        String url = cfg.optString("url", "https://cbt.smkpenerbangan.sch.id");
        try {
            allowedHost = new URL(url).getHost();
        } catch (Exception e) {
            allowedHost = "";
        }
        web.loadUrl(url);

        if (cameraEnabled) {
            requestCameraIfNeeded();
        }
    }

    // ---------------------------------------------------------------- config

    private JSONObject readConfig() {
        String json = null;
        try {
            File ext = new File(getExternalFilesDir(null), "config.json");
            if (ext.exists()) {
                json = slurp(new FileInputStream(ext));
            }
        } catch (Exception e) {
            json = null;
        }
        if (json == null) {
            try {
                json = slurp(getAssets().open("config.json"));
            } catch (Exception e) {
                json = null;
            }
        }
        try {
            return json != null ? new JSONObject(json) : new JSONObject();
        } catch (Exception e) {
            return new JSONObject();
        }
    }

    private static String slurp(InputStream in) throws Exception {
        try {
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            byte[] buf = new byte[8192];
            int n;
            while ((n = in.read(buf)) > 0) {
                out.write(buf, 0, n);
            }
            return new String(out.toByteArray(), "UTF-8");
        } finally {
            try { in.close(); } catch (Exception e) { }
        }
    }

    // ---------------------------------------------------------------- webview

    private void setupWebView() {
        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        s.setAllowFileAccess(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setJavaScriptCanOpenWindowsAutomatically(false);
        s.setSupportMultipleWindows(true);

        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onCreateWindow(WebView view, boolean isDialog, boolean isUserGesture, Message resultMsg) {
                // Block all attempts to open a new tab/window (window.open, target=_blank)
                Log.d(TAG, "BLOCK new window/tab request");
                return false;
            }

            @Override
            public boolean onJsAlert(WebView view, String url, String message, JsResult result) {
                result.confirm();
                return true;
            }

            @Override
            public boolean onJsConfirm(WebView view, String url, String message, android.webkit.JsResult result) {
                result.confirm();
                return true;
            }
        });

        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                return isBlocked(url);
            }

            @Override
            public void onPageFinished(WebView view, String url) {
                raiseCamera();
            }
        });

        root.addView(web, new FrameLayout.LayoutParams(MATCH, MATCH));
    }

    private boolean isBlocked(String url) {
        if (url == null) {
            return true;
        }
        String lurl = url.toLowerCase(java.util.Locale.US);
        if (lurl.startsWith("about:") || lurl.startsWith("data:")
                || lurl.startsWith("blob:") || lurl.startsWith("file:")) {
            return false;
        }
        boolean blocked = true;
        int ci = url.indexOf(':');
        if (ci > 0) {
            String scheme = lurl.substring(0, ci);
            if (scheme.equals("http") || scheme.equals("https")) {
                try {
                    String host = new URL(url).getHost();
                    blocked = host == null || allowedHost.isEmpty()
                            || !(host.equals(allowedHost) || host.endsWith("." + allowedHost));
                } catch (Exception e) {
                    blocked = true;
                }
            }
        }
        if (blocked) {
            Log.d(TAG, "BLOCK navigation: " + url);
        }
        return blocked;
    }

    // ---------------------------------------------------------------- marquee

    private void addMarquee() {
        JSONObject m = cfg.optJSONObject("marquee");
        if (m == null || !m.optBoolean("enabled", true)) {
            return;
        }
        int hp = m.optInt("height_percent", 10);
        int screenH = getResources().getDisplayMetrics().heightPixels;
        int hpx = Math.max(dp(28), screenH * hp / 100);

        TextView tv = new TextView(this);
        tv.setText(m.optString("text", ""));
        tv.setSingleLine(true);
        tv.setEllipsize(TextUtils.TruncateAt.MARQUEE);
        tv.setMarqueeRepeatLimit(-1);
        tv.setSelected(true);
        tv.setHorizontallyScrolling(true);
        tv.setGravity(Gravity.CENTER_VERTICAL);
        tv.setPadding(dp(12), 0, dp(12), 0);
        tv.setTextColor(parseColor(m.optString("color", "#ffffff"), Color.WHITE));
        tv.setTextSize(TypedValue.COMPLEX_UNIT_PX, hpx * 0.45f);
        tv.setShadowLayer(6f, 0f, 2f, 0xAA000000);
        tv.setBackground(gradient(m));

        FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(MATCH, hpx);
        lp.gravity = Gravity.BOTTOM;
        root.addView(tv, lp);
    }

    private GradientDrawable gradient(JSONObject m) {
        int[] colors;
        Object bg = m.opt("background");
        if (bg instanceof JSONArray) {
            JSONArray arr = (JSONArray) bg;
            colors = new int[arr.length()];
            for (int i = 0; i < arr.length(); i++) {
                colors[i] = parseColor(arr.optString(i, "#222222"), Color.DKGRAY);
            }
        } else {
            colors = new int[]{parseColor(m.optString("background", "#222222"), Color.DKGRAY)};
        }
        GradientDrawable g = new GradientDrawable(GradientDrawable.Orientation.LEFT_RIGHT, colors);
        g.setGradientType(GradientDrawable.LINEAR_GRADIENT);
        return g;
    }

    // ---------------------------------------------------------------- exit

    private void addExitHotspot() {
        View v = new View(this);
        v.setOnLongClickListener(new View.OnLongClickListener() {
            @Override
            public boolean onLongClick(View view) {
                showExitDialog();
                return true;
            }
        });
        FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(dp(72), dp(72));
        lp.gravity = Gravity.TOP | Gravity.START;
        root.addView(v, lp);
    }

    private void showExitDialog() {
        Log.d(TAG, "showExitDialog");
        final EditText et = new EditText(this);
        et.setInputType(InputType.TYPE_CLASS_TEXT);
        et.setHint("Ketik " + exitWord);
        new AlertDialog.Builder(this)
                .setTitle("Keluar Exam Browser")
                .setMessage("Ketik \"" + exitWord + "\" untuk keluar. Login dan cache akan dihapus.")
                .setView(et)
                .setPositiveButton("OK", new android.content.DialogInterface.OnClickListener() {
                    @Override
                    public void onClick(android.content.DialogInterface d, int w) {
                        if (exitWord.equalsIgnoreCase(et.getText().toString().trim())) {
                            shutdown();
                        } else {
                            Toast.makeText(MainActivity.this,
                                    "Ketik \"" + exitWord + "\" untuk keluar", Toast.LENGTH_SHORT).show();
                        }
                    }
                })
                .setNegativeButton("Batal", null)
                .show();
    }

    private void shutdown() {
        releaseCamera();
        if (clearDataOnExit) {
            clearSessionData();
        }
        exitLockTask();
        finishAffinity();
    }

    private void clearSessionData() {
        try {
            CookieManager cm = CookieManager.getInstance();
            cm.removeAllCookies(null);
            cm.flush();
        } catch (Exception e) {
            Log.d(TAG, "clear cookies: " + e);
        }
        try {
            WebStorage.getInstance().deleteAllData();
        } catch (Exception e) {
            Log.d(TAG, "clear webstorage: " + e);
        }
        try {
            if (web != null) {
                web.clearCache(true);
                web.clearFormData();
                web.clearHistory();
                web.clearSslPreferences();
            }
        } catch (Exception e) {
            Log.d(TAG, "clear webview: " + e);
        }
        try {
            deleteDatabase("webview.db");
            deleteDatabase("webviewCache.db");
            deleteDatabase("webviewCookiesChromium.db");
            deleteDatabase("webviewCookiesChromiumPrivate.db");
        } catch (Exception e) {
            // ignore
        }
        try {
            deleteRecursive(getCacheDir());
        } catch (Exception e) {
            // ignore
        }
        Log.d(TAG, "session data cleared (login reset)");
    }

    private void deleteRecursive(File f) {
        if (f == null || !f.exists()) {
            return;
        }
        if (f.isDirectory()) {
            File[] children = f.listFiles();
            if (children != null) {
                for (File c : children) {
                    deleteRecursive(c);
                }
            }
        }
        f.delete();
    }

    // ---------------------------------------------------------------- camera

    private void requestCameraIfNeeded() {
        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{Manifest.permission.CAMERA}, REQ_CAMERA);
        } else {
            addCameraOverlay();
        }
    }

    @Override
    public void onRequestPermissionsResult(int req, String[] perms, int[] grants) {
        super.onRequestPermissionsResult(req, perms, grants);
        if (req == REQ_CAMERA) {
            if (grants.length > 0 && grants[0] == PackageManager.PERMISSION_GRANTED) {
                addCameraOverlay();
            } else {
                Toast.makeText(this, "Izin kamera ditolak", Toast.LENGTH_SHORT).show();
            }
        }
    }

    private void addCameraOverlay() {
        if (camBox != null) {
            return;
        }
        mCameraId = findFrontCamera();
        if (mCameraId < 0) {
            return;
        }
        try {
            camera = Camera.open(mCameraId);
        } catch (Exception e) {
            camera = null;
            return;
        }

        FrameLayout box = new FrameLayout(this);
        box.setBackground(border());
        camView = new TextureView(this);
        camView.setScaleX(-1f);
        FrameLayout.LayoutParams cvlp = new FrameLayout.LayoutParams(MATCH, MATCH);
        int m = dp(3);
        cvlp.setMargins(m, m, m, m);
        box.addView(camView, cvlp);

        int screenW = getResources().getDisplayMetrics().widthPixels;
        FrameLayout.LayoutParams lp = new FrameLayout.LayoutParams(overlayWpx, overlayHpx);
        lp.gravity = Gravity.TOP | Gravity.START;
        lp.leftMargin = Math.max(0, screenW - overlayWpx - dp(12));
        lp.topMargin = dp(12);
        root.addView(box, lp);
        box.bringToFront();
        camBox = box;
        makeDraggable(box, lp);

        camView.setSurfaceTextureListener(new TextureView.SurfaceTextureListener() {
            @Override
            public void onSurfaceTextureAvailable(SurfaceTexture st, int w, int h) {
                startPreview(st);
            }

            @Override
            public void onSurfaceTextureSizeChanged(SurfaceTexture st, int w, int h) {
            }

            @Override
            public boolean onSurfaceTextureDestroyed(SurfaceTexture st) {
                return true;
            }

            @Override
            public void onSurfaceTextureUpdated(SurfaceTexture st) {
            }
        });
    }

    private int findFrontCamera() {
        int n = Camera.getNumberOfCameras();
        Camera.CameraInfo info = new Camera.CameraInfo();
        for (int i = 0; i < n; i++) {
            Camera.getCameraInfo(i, info);
            if (info.facing == Camera.CameraInfo.CAMERA_FACING_FRONT) {
                return i;
            }
        }
        return n > 0 ? 0 : -1;
    }

    private void startPreview(SurfaceTexture st) {
        if (camera == null) {
            return;
        }
        try {
            camera.setPreviewTexture(st);
            Camera.Parameters p = camera.getParameters();
            Camera.Size best = bestSize(p.getSupportedPreviewSizes(), 640, 480);
            if (best != null) {
                p.setPreviewSize(best.width, best.height);
            }
            camera.setParameters(p);
            applyDisplayOrientation();
            camera.startPreview();
        } catch (Exception e) {
            // ignore
        }
    }

    private void applyDisplayOrientation() {
        try {
            Camera.CameraInfo info = new Camera.CameraInfo();
            Camera.getCameraInfo(mCameraId, info);
            int rotation = getWindowManager().getDefaultDisplay().getRotation();
            int degrees = 0;
            switch (rotation) {
                case Surface.ROTATION_0: degrees = 0; break;
                case Surface.ROTATION_90: degrees = 90; break;
                case Surface.ROTATION_180: degrees = 180; break;
                case Surface.ROTATION_270: degrees = 270; break;
                default: break;
            }
            int result;
            if (info.facing == Camera.CameraInfo.CAMERA_FACING_FRONT) {
                result = (info.orientation + degrees) % 360;
                result = (360 - result) % 360;
            } else {
                result = (info.orientation - degrees + 360) % 360;
            }
            camera.setDisplayOrientation(result);
        } catch (Exception e) {
            // ignore
        }
    }

    private Camera.Size bestSize(List<Camera.Size> sizes, int tw, int th) {
        if (sizes == null || sizes.isEmpty()) {
            return null;
        }
        double target = (double) tw / th;
        Camera.Size best = sizes.get(0);
        long bestScore = Long.MAX_VALUE;
        for (Camera.Size s : sizes) {
            double r = (double) s.width / s.height;
            long score = (long) (Math.abs(r - target) * 10000) + Math.abs(s.width - tw);
            if (score < bestScore) {
                bestScore = score;
                best = s;
            }
        }
        return best;
    }

    private void makeDraggable(final View box, final FrameLayout.LayoutParams lp) {
        box.setOnTouchListener(new View.OnTouchListener() {
            @Override
            public boolean onTouch(View v, MotionEvent e) {
                switch (e.getActionMasked()) {
                    case MotionEvent.ACTION_DOWN:
                        dragDownX = (int) e.getRawX();
                        dragDownY = (int) e.getRawY();
                        startLeft = lp.leftMargin;
                        startTop = lp.topMargin;
                        return true;
                    case MotionEvent.ACTION_MOVE: {
                        int screenW = getResources().getDisplayMetrics().widthPixels;
                        int screenH = getResources().getDisplayMetrics().heightPixels;
                        int nl = startLeft + ((int) e.getRawX() - dragDownX);
                        int nt = startTop + ((int) e.getRawY() - dragDownY);
                        nl = Math.max(0, Math.min(nl, screenW - overlayWpx));
                        nt = Math.max(0, Math.min(nt, screenH - overlayHpx));
                        lp.leftMargin = nl;
                        lp.topMargin = nt;
                        box.setLayoutParams(lp);
                        return true;
                    }
                    default:
                        return false;
                }
            }
        });
    }

    private void raiseCamera() {
        if (camBox != null) {
            camBox.bringToFront();
        }
    }

    private void releaseCamera() {
        if (camera != null) {
            try { camera.stopPreview(); } catch (Exception e) { }
            try { camera.release(); } catch (Exception e) { }
            camera = null;
        }
    }

    // ---------------------------------------------------------------- window

    private void goImmersive() {
        if (Build.VERSION.SDK_INT >= 30) {
            WindowInsetsController c = getWindow().getInsetsController();
            if (c != null) {
                c.hide(WindowInsets.Type.systemBars());
                c.setSystemBarsBehavior(WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE);
            }
        } else {
            getWindow().getDecorView().setSystemUiVisibility(
                    View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY
                            | View.SYSTEM_UI_FLAG_HIDE_NAVIGATION
                            | View.SYSTEM_UI_FLAG_FULLSCREEN
                            | View.SYSTEM_UI_FLAG_LAYOUT_STABLE
                            | View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION
                            | View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN);
        }
    }

    // ---------------------------------------------------------------- kiosk

    private void enterLockTask() {
        if (!cfg.optBoolean("lock_task", true)) {
            return;
        }
        try {
            DevicePolicyManager dpm =
                    (DevicePolicyManager) getSystemService(Context.DEVICE_POLICY_SERVICE);
            ComponentName admin = new ComponentName(this, AdminReceiver.class);
            if (dpm != null && dpm.isDeviceOwnerApp(getPackageName())) {
                dpm.setLockTaskPackages(admin, new String[]{getPackageName()});
                Log.d(TAG, "device owner: lock task allowlisted");
            }
        } catch (Exception e) {
            Log.d(TAG, "dpm setup skipped: " + e);
        }
        try {
            startLockTask();
            Log.d(TAG, "startLockTask requested");
        } catch (Exception e) {
            Log.d(TAG, "startLockTask failed: " + e);
        }
    }

    private void exitLockTask() {
        try {
            stopLockTask();
        } catch (Exception e) {
            // ignore
        }
    }

    @Override
    public void onWindowFocusChanged(boolean hasFocus) {
        super.onWindowFocusChanged(hasFocus);
        if (hasFocus) {
            goImmersive();
            raiseCamera();
        }
    }

    @Override
    public void onConfigurationChanged(Configuration newConfig) {
        super.onConfigurationChanged(newConfig);
        goImmersive();
        if (camBox != null) {
            FrameLayout.LayoutParams lp = (FrameLayout.LayoutParams) camBox.getLayoutParams();
            int screenW = getResources().getDisplayMetrics().widthPixels;
            int screenH = getResources().getDisplayMetrics().heightPixels;
            lp.leftMargin = Math.max(0, Math.min(lp.leftMargin, screenW - overlayWpx));
            lp.topMargin = Math.max(0, Math.min(lp.topMargin, screenH - overlayHpx));
            camBox.setLayoutParams(lp);
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (camera != null) {
            try { camera.startPreview(); } catch (Exception e) { }
        }
    }

    @Override
    protected void onPause() {
        if (camera != null) {
            try { camera.stopPreview(); } catch (Exception e) { }
        }
        super.onPause();
    }

    @Override
    protected void onDestroy() {
        releaseCamera();
        super.onDestroy();
    }

    @Override
    @SuppressWarnings("deprecation")
    public void onBackPressed() {
        // Exit only after tapping the back button N times (default 2) quickly.
        long now = System.currentTimeMillis();
        if (now - lastBackTime > 1500L) {
            backTapCount = 0;
        }
        backTapCount++;
        lastBackTime = now;
        Log.d(TAG, "back tap " + backTapCount + "/" + exitBackTaps);
        if (backTapCount >= exitBackTaps) {
            backTapCount = 0;
            showExitDialog();
        } else {
            Toast.makeText(this,
                    "Tekan kembali " + (exitBackTaps - backTapCount) + "x lagi untuk keluar",
                    Toast.LENGTH_SHORT).show();
        }
    }

    // ---------------------------------------------------------------- utils

    private GradientDrawable border() {
        GradientDrawable g = new GradientDrawable();
        g.setColor(0xFF0B1220);
        g.setStroke(dp(2), 0xFF2563EB);
        g.setCornerRadius(dp(6));
        return g;
    }

    private int dp(float v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }

    private int parseColor(String s, int fallback) {
        try {
            return Color.parseColor(s);
        } catch (Exception e) {
            return fallback;
        }
    }

    private int[] intArray(JSONArray a, int[] fallback) {
        if (a == null) {
            return fallback;
        }
        try {
            int[] r = new int[a.length()];
            for (int i = 0; i < r.length; i++) {
                r[i] = a.getInt(i);
            }
            return r;
        } catch (Exception e) {
            return fallback;
        }
    }
}
