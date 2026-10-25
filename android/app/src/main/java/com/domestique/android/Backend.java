// Copyright (c) 2026 Domestique contributors
// SPDX-License-Identifier: Apache-2.0
package com.domestique.android;

import android.content.Context;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;
import java.io.File;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.StandardCopyOption;
import java.util.concurrent.CompletableFuture;

/** One backend per application process, including Activity recreation. */
final class Backend {
    private static CompletableFuture<String> startup;

    static synchronized CompletableFuture<String> start(Context context) {
        if (startup == null || startup.isCompletedExceptionally()) {
            Context app = context.getApplicationContext();
            startup = CompletableFuture.supplyAsync(() -> {
                try {
                    File archive = new File(app.getCacheDir(), "backend.zip");
                    try (InputStream in = app.getAssets().open("backend.zip")) {
                        Files.copy(in, archive.toPath(), StandardCopyOption.REPLACE_EXISTING);
                    }
                    if (!Python.isStarted()) Python.start(new AndroidPlatform(app));
                    return Python.getInstance().getModule("android_backend")
                        .callAttr("start", archive.getAbsolutePath(), app.getFilesDir().getAbsolutePath())
                        .toString();
                } catch (Exception e) {
                    throw new RuntimeException("Could not start Domestique", e);
                }
            });
        }
        return startup;
    }
}
