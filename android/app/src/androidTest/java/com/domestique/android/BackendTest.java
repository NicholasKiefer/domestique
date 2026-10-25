// Copyright (c) 2026 Domestique contributors
// SPDX-License-Identifier: Apache-2.0
package com.domestique.android;

import androidx.test.platform.app.InstrumentationRegistry;
import androidx.test.ext.junit.runners.AndroidJUnit4;
import org.junit.Test;
import org.junit.runner.RunWith;
import static org.junit.Assert.*;
import com.chaquo.python.Python;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.concurrent.TimeUnit;

/** Runs the real embedded Python/native wheels on Android, without network accounts. */
@RunWith(AndroidJUnit4.class)
public class BackendTest {
    @Test public void embeddedBackendAndScientificLibraries() throws Exception {
        android.content.Context context = InstrumentationRegistry.getInstrumentation().getTargetContext();
        String origin = Backend.start(context).get(180, TimeUnit.SECONDS);
        HttpURLConnection request = (HttpURLConnection) new URL(origin + "/api/version").openConnection();
        try { assertEquals(200, request.getResponseCode()); }
        finally { request.disconnect(); }
        assertEquals(origin, Backend.start(context).get());
        Python py = Python.getInstance();
        assertNotNull(py.getModule("numpy"));
        assertNotNull(py.getModule("scipy.optimize").get("curve_fit"));
        assertNotNull(py.getModule("fit_tool.fit_file"));
        request = (HttpURLConnection) new URL(origin + "/setup").openConnection();
        try { assertEquals(200, request.getResponseCode()); }
        finally { request.disconnect(); }
    }
}
