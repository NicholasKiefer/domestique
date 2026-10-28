// Copyright (c) 2026 Domestique contributors
// SPDX-License-Identifier: Apache-2.0
package com.domestique.android;

import java.net.URI;

/** Keep update decisions independent of Android and the network. */
public final class UpdatePolicy {
    private static final String RELEASES = "/NicholasKiefer/domestique/releases/";
    private UpdatePolicy() {}

    public static boolean isNewer(long installed, long available) {
        return available > installed && available <= Integer.MAX_VALUE;
    }

    public static boolean trustedReleaseUrl(String value, boolean apk) {
        try {
            URI uri = new URI(value);
            if (!"https".equals(uri.getScheme()) || !"github.com".equals(uri.getHost())
                || uri.getRawUserInfo() != null || uri.getPort() != -1
                || uri.getRawQuery() != null || uri.getRawFragment() != null) return false;
            String path = uri.getRawPath();
            return path != null && path.startsWith(RELEASES + (apk ? "download/" : "tag/"))
                && !path.contains("%") && !path.contains("..")
                && (!apk || path.endsWith(".apk"));
        } catch (Exception ignored) { return false; }
    }

    public static boolean sameSigner(String installed, String available) {
        return installed != null && available != null
            && installed.matches("[a-fA-F0-9]{64}")
            && installed.equalsIgnoreCase(available);
    }
}
