package com.domestique.android;

import org.junit.Test;
import static org.junit.Assert.*;

public class UpdatePolicyTest {
    @Test public void updatesRequireIncreasingAndroidVersionCodes() {
        assertTrue(UpdatePolicy.isNewer(100, 101));
        assertFalse(UpdatePolicy.isNewer(100, 100));
        assertFalse(UpdatePolicy.isNewer(100, 99));
        assertFalse(UpdatePolicy.isNewer(100, -1));
        assertFalse(UpdatePolicy.isNewer(100, Long.MAX_VALUE));
    }
    @Test public void apkLinksStayInTheForkReleaseChannel() {
        String good = "https://github.com/NicholasKiefer/domestique/releases/download/android-dev-100/app.apk";
        assertTrue(UpdatePolicy.trustedReleaseUrl(good, true));
        assertFalse(UpdatePolicy.trustedReleaseUrl(good.replace("https:", "http:"), true));
        assertFalse(UpdatePolicy.trustedReleaseUrl(good.replace("github.com", "github.com.evil.test"), true));
        assertFalse(UpdatePolicy.trustedReleaseUrl(good.replace("NicholasKiefer", "platypus45"), true));
        assertFalse(UpdatePolicy.trustedReleaseUrl(good.replace("app.apk", "app.exe"), true));
        assertFalse(UpdatePolicy.trustedReleaseUrl(good + "?redirect=evil", true));
        assertFalse(UpdatePolicy.trustedReleaseUrl(good.replace("github.com/", "evil@github.com/"), true));
        assertFalse(UpdatePolicy.trustedReleaseUrl(good.replace("app.apk", "../app.apk"), true));
        assertFalse(UpdatePolicy.trustedReleaseUrl(good.replace("app.apk", "%2e%2e/app.apk"), true));
        assertTrue(UpdatePolicy.trustedReleaseUrl("https://github.com/NicholasKiefer/domestique/releases/tag/android-dev-100", false));
    }
    @Test public void mismatchedOrMissingCertificatesCannotPromiseInPlaceUpdates() {
        String certificate = new String(new char[64]).replace('\0', 'a');
        assertTrue(UpdatePolicy.sameSigner(certificate, certificate.toUpperCase()));
        assertFalse(UpdatePolicy.sameSigner(certificate, certificate.replace('a', 'b')));
        assertFalse(UpdatePolicy.sameSigner("", ""));
        assertFalse(UpdatePolicy.sameSigner(null, certificate));
    }
}
