// Copyright (c) 2026 Domestique contributors
// SPDX-License-Identifier: Apache-2.0
package com.domestique.android;

import android.app.Activity;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.content.pm.Signature;
import android.net.Uri;
import android.os.Build;
import android.util.Log;
import android.widget.Toast;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Locale;
import java.util.concurrent.CompletableFuture;

/** Fork-only Android channel; never offers a desktop installer or upstream release. */
final class AndroidUpdates {
    private static final String MANIFEST = "https://github.com/NicholasKiefer/domestique/"
        + "releases/download/android-latest/update.json";
    private final Activity activity;
    private final SharedPreferences prefs;
    private boolean checking;
    private long lastCheck;

    AndroidUpdates(Activity activity) {
        this.activity = activity;
        prefs = activity.getSharedPreferences("android-updates", Activity.MODE_PRIVATE);
    }

    void check(boolean manual) {
        // UI thread only. Avoid checks on every document picker/browser return.
        if (checking || (!manual && System.currentTimeMillis() - lastCheck < 60 * 60 * 1000)) return;
        checking = true;
        lastCheck = System.currentTimeMillis();
        CompletableFuture.supplyAsync(() -> {
            try { return readManifest(); }
            catch (Exception e) { Log.i("Domestique", "Android update check unavailable", e); return null; }
        }).thenAccept(release -> activity.runOnUiThread(() -> {
            checking = false;
            if (activity.isFinishing() || activity.isDestroyed()) return;
            if (release == null) {
                if (manual) toast("Could not check Android updates. The development channel may not be published yet.");
                return;
            }
            long code = release.optLong("version_code", -1);
            if (!UpdatePolicy.isNewer(BuildConfig.VERSION_CODE, code)) {
                if (manual) toast("You have the latest Android development build.");
                return;
            }
            String apk = release.optString("apk_url");
            String notes = release.optString("release_url");
            if (!"com.domestique.android".equals(release.optString("application_id"))
                || !UpdatePolicy.trustedReleaseUrl(apk, true)
                || !UpdatePolicy.trustedReleaseUrl(notes, false)) {
                if (manual) toast("The Android update information is invalid.");
                return;
            }
            if (!manual && prefs.getLong("dismissed-version", -1) == code) return;
            boolean compatible = UpdatePolicy.sameSigner(installedSigner(), release.optString("certificate_sha256"));
            String version = release.optString("version_name", Long.toString(code));
            String message = compatible
                ? "Android " + version + " is available. Download the APK, open it, then confirm Update in Android. "
                    + "Your local data stays in place. Android may ask you to allow installs from your browser."
                : "Android " + version + " is available, but your installed app uses a different signing key. "
                    + "This build cannot update it in place. Do not uninstall without saving your data. "
                    + "See the release notes for the one-time migration.";
            new AlertDialog.Builder(activity)
                .setTitle("Android update available")
                .setMessage(message)
                .setPositiveButton(compatible ? "Update now" : "Release notes",
                    (dialog, which) -> open(compatible ? apk : notes))
                .setNeutralButton("Later", (dialog, which) -> {})
                .setNegativeButton("Skip this version", (dialog, which) ->
                    prefs.edit().putLong("dismissed-version", code).apply())
                .show();
        }));
    }

    private JSONObject readManifest() throws Exception {
        URL url = new URL(MANIFEST);
        // Follow GitHub's HTTPS asset redirects, with bounded size/time.
        for (int redirects = 0; redirects < 6; redirects++) {
            if (!"https".equals(url.getProtocol())) throw new Exception("Insecure update redirect");
            HttpURLConnection connection = (HttpURLConnection) url.openConnection();
            connection.setInstanceFollowRedirects(false);
            connection.setConnectTimeout(10000);
            connection.setReadTimeout(10000);
            connection.setRequestProperty("User-Agent", "Domestique-Android/" + BuildConfig.VERSION_NAME);
            try {
                int status = connection.getResponseCode();
                if (status >= 300 && status <= 399) {
                    String location = connection.getHeaderField("Location");
                    if (location == null) throw new Exception("Missing redirect");
                    url = new URL(url, location);
                    continue;
                }
                if (status != 200) throw new Exception("Update HTTP " + status);
                try (InputStream input = connection.getInputStream();
                     ByteArrayOutputStream bytes = new ByteArrayOutputStream()) {
                    byte[] buffer = new byte[4096];
                    int n;
                    while ((n = input.read(buffer)) != -1) {
                        if (bytes.size() + n > 65536) throw new Exception("Update metadata too large");
                        bytes.write(buffer, 0, n);
                    }
                    return new JSONObject(new String(bytes.toByteArray(), StandardCharsets.UTF_8));
                }
            } finally { connection.disconnect(); }
        }
        throw new Exception("Too many update redirects");
    }

    @SuppressWarnings("deprecation")
    private String installedSigner() {
        try {
            PackageInfo info = activity.getPackageManager().getPackageInfo(activity.getPackageName(),
                Build.VERSION.SDK_INT >= 28 ? PackageManager.GET_SIGNING_CERTIFICATES : PackageManager.GET_SIGNATURES);
            Signature[] signatures = Build.VERSION.SDK_INT >= 28
                ? info.signingInfo.getApkContentsSigners() : info.signatures;
            if (signatures == null || signatures.length != 1) return "";
            byte[] digest = MessageDigest.getInstance("SHA-256").digest(signatures[0].toByteArray());
            StringBuilder hex = new StringBuilder();
            for (byte b : digest) hex.append(String.format(Locale.ROOT, "%02x", b & 255));
            return hex.toString();
        } catch (Exception e) { return ""; }
    }

    private void open(String url) {
        try { activity.startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url))); }
        catch (Exception e) { toast("No browser is available to open the update."); }
    }

    private void toast(String message) { Toast.makeText(activity, message, Toast.LENGTH_LONG).show(); }
}
