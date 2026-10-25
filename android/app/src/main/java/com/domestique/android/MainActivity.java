// Copyright (c) 2026 Domestique contributors
// SPDX-License-Identifier: Apache-2.0
package com.domestique.android;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.util.Base64;
import android.util.Log;
import android.view.Gravity;
import android.view.View;
import android.webkit.JavascriptInterface;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ProgressBar;
import android.widget.TextView;
import android.widget.Toast;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.ByteArrayOutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.CompletableFuture;

public class MainActivity extends Activity {
    private static final int PICK_FILE = 10, SAVE_FILE = 11;
    private static final int MAX_EXPORT = 32 * 1024 * 1024;
    private WebView web;
    private String origin;
    private ValueCallback<Uri[]> filePicker;
    private byte[] pendingExport;
    private Bundle savedWebState;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        savedWebState = state;
        // Keep the web content outside system bars, including Android 15 edge-to-edge.
        getWindow().getDecorView().setOnApplyWindowInsetsListener((view, insets) -> {
            view.setPadding(insets.getSystemWindowInsetLeft(), insets.getSystemWindowInsetTop(),
                insets.getSystemWindowInsetRight(), insets.getSystemWindowInsetBottom());
            return insets.consumeSystemWindowInsets();
        });
        boot();
    }

    private void boot() {
        LinearLayout loading = new LinearLayout(this);
        loading.setOrientation(LinearLayout.VERTICAL);
        loading.setGravity(Gravity.CENTER);
        loading.setPadding(32, 32, 32, 32);
        loading.setBackgroundColor(Color.rgb(10, 14, 20));
        TextView title = new TextView(this);
        title.setText(R.string.starting);
        title.setTextColor(Color.WHITE);
        title.setTextSize(18);
        title.setGravity(Gravity.CENTER);
        loading.addView(title);
        loading.addView(new ProgressBar(this));
        setContentView(loading);
        Backend.start(this).whenComplete((url, error) -> runOnUiThread(() -> {
            if (isFinishing() || isDestroyed()) return;
            if (error != null) {
                Log.e("Domestique", "Startup failed", error);
                loading.removeViewAt(1);
                Throwable cause = error;
                while (cause.getCause() != null) cause = cause.getCause();
                title.setText(getString(R.string.startup_failure, cause.getMessage()));
                Button retry = new Button(this);
                retry.setText(R.string.retry);
                retry.setOnClickListener(v -> boot());
                loading.addView(retry);
            } else {
                origin = url;
                showApp();
            }
        }));
    }

    private boolean isLocal(Uri uri) {
        Uri base = Uri.parse(origin);
        return "http".equals(uri.getScheme()) && base.getHost().equals(uri.getHost())
            && base.getPort() == uri.getPort();
    }

    private void external(Uri uri) {
        if (!"https".equals(uri.getScheme()) && !"mailto".equals(uri.getScheme())) return;
        try { startActivity(new Intent(Intent.ACTION_VIEW, uri)); }
        catch (ActivityNotFoundException e) { toast("No app is available to open this link."); }
    }

    private void showApp() {
        web = new WebView(this);
        web.setBackgroundColor(Color.rgb(10, 14, 20));
        web.getSettings().setJavaScriptEnabled(true);
        web.getSettings().setDomStorageEnabled(true);
        web.getSettings().setAllowFileAccess(false);
        web.getSettings().setAllowContentAccess(true); // Android document picker uploads
        web.getSettings().setJavaScriptCanOpenWindowsAutomatically(false);
        // _blank is handled as navigation, then the client opens HTTPS externally.
        web.getSettings().setSupportMultipleWindows(false);
        if (BuildConfig.DEBUG) WebView.setWebContentsDebuggingEnabled(true);
        web.addJavascriptInterface(new ExportBridge(), "DomestiqueAndroid");
        web.setWebViewClient(new WebViewClient() {
            @Override public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
                if (isLocal(req.getUrl())) return false;
                if (req.isForMainFrame()) external(req.getUrl());
                return true;
            }
            @Override public void onPageFinished(WebView view, String url) {
                if (!isLocal(Uri.parse(url))) return;
                try (InputStream in = getAssets().open("mobile.js")) {
                    view.evaluateJavascript(new String(readBytes(in, 1024 * 1024), StandardCharsets.UTF_8), null);
                } catch (Exception e) { Log.e("Domestique", "Mobile UI setup failed", e); }
            }
        });
        web.setWebChromeClient(new WebChromeClient() {
            @Override public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback,
                                                       FileChooserParams params) {
                if (filePicker != null) filePicker.onReceiveValue(null);
                filePicker = callback;
                Intent pick = new Intent(Intent.ACTION_OPEN_DOCUMENT);
                pick.addCategory(Intent.CATEGORY_OPENABLE);
                pick.setType("*/*"); // FIT files are often labelled application/octet-stream.
                pick.putExtra(Intent.EXTRA_ALLOW_MULTIPLE,
                    params.getMode() == FileChooserParams.MODE_OPEN_MULTIPLE);
                try { startActivityForResult(pick, PICK_FILE); }
                catch (ActivityNotFoundException e) {
                    filePicker.onReceiveValue(null);
                    filePicker = null;
                    toast("No document picker is available.");
                }
                return true;
            }
        });
        web.setDownloadListener((url, ua, disposition, mime, length) -> {
            if (isLocal(Uri.parse(url))) download(url, "workout", mime);
        });
        setContentView(web);
        // The process can restart with a new ephemeral port: restore only same-origin state.
        if (savedWebState != null && origin.equals(savedWebState.getString("origin"))) {
            web.restoreState(savedWebState);
        }
        if (web.getUrl() == null) web.loadUrl(origin);
    }

    private class ExportBridge {
        // Only local pages are loaded. Never expose this bridge to external origins.
        @JavascriptInterface public void save(String name, String base64, String mime) {
            if (base64.length() > MAX_EXPORT * 4L / 3 + 8) return;
            try {
                byte[] bytes = Base64.decode(base64, Base64.DEFAULT);
                runOnUiThread(() -> chooseDestination(name, mime, bytes));
            } catch (IllegalArgumentException e) { Log.w("Domestique", "Invalid export", e); }
        }
    }

    private void download(String url, String name, String mime) {
        CompletableFuture.runAsync(() -> {
            HttpURLConnection connection = null;
            try {
                connection = (HttpURLConnection) new URL(url).openConnection();
                connection.setInstanceFollowRedirects(false);
                connection.setConnectTimeout(10000);
                connection.setReadTimeout(30000);
                if (connection.getResponseCode() != 200) throw new Exception("Download failed");
                try (InputStream in = connection.getInputStream()) {
                    byte[] bytes = readBytes(in, MAX_EXPORT + 1);
                    if (bytes.length > MAX_EXPORT) throw new Exception("Export is too large");
                    runOnUiThread(() -> chooseDestination(name, mime, bytes));
                }
            } catch (Exception e) { runOnUiThread(() -> toast("Could not download the file.")); }
            finally { if (connection != null) connection.disconnect(); }
        });
    }

    private void chooseDestination(String name, String mime, byte[] bytes) {
        if (isFinishing() || isDestroyed()) return;
        if (pendingExport != null) { toast("Finish saving the previous file first."); return; }
        pendingExport = bytes;
        Intent save = new Intent(Intent.ACTION_CREATE_DOCUMENT);
        save.addCategory(Intent.CATEGORY_OPENABLE);
        save.setType(mime == null || mime.trim().isEmpty() ? "application/octet-stream" : mime);
        save.putExtra(Intent.EXTRA_TITLE, name.replaceAll("[/\\\\]", "_"));
        try { startActivityForResult(save, SAVE_FILE); }
        catch (ActivityNotFoundException e) { pendingExport = null; toast("No document picker is available."); }
    }

    @Override protected void onActivityResult(int request, int result, Intent data) {
        super.onActivityResult(request, result, data);
        if (request == PICK_FILE && filePicker != null) {
            filePicker.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(result, data));
            filePicker = null;
        }
        if (request == SAVE_FILE) {
            byte[] bytes = pendingExport;
            pendingExport = null;
            if (result == RESULT_OK && data != null && data.getData() != null && bytes != null) {
                Uri dest = data.getData();
                CompletableFuture.runAsync(() -> {
                    try (OutputStream out = getContentResolver().openOutputStream(dest)) {
                        if (out == null) throw new Exception("Cannot open destination");
                        out.write(bytes);
                        runOnUiThread(() -> toast("File saved."));
                    } catch (Exception e) { runOnUiThread(() -> toast("Could not save the file.")); }
                });
            }
        }
    }

    private void toast(String message) { Toast.makeText(this, message, Toast.LENGTH_LONG).show(); }

    private static byte[] readBytes(InputStream in, int limit) throws java.io.IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] buffer = new byte[8192];
        int n;
        while ((n = in.read(buffer, 0, Math.min(buffer.length, limit - out.size()))) > 0) {
            out.write(buffer, 0, n);
            if (out.size() == limit) break;
        }
        return out.toByteArray();
    }

    @Override public void onBackPressed() {
        if (web != null && web.canGoBack()) web.goBack();
        else super.onBackPressed();
    }

    @Override public void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        if (web != null) { web.saveState(out); out.putString("origin", origin); }
    }

    @Override public void onDestroy() {
        if (filePicker != null) filePicker.onReceiveValue(null);
        if (web != null) { web.removeJavascriptInterface("DomestiqueAndroid"); web.destroy(); }
        super.onDestroy();
    }
}
