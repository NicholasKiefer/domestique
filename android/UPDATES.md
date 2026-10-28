# Android app updates

The app checks the Android fork's `android-latest/update.json` GitHub Release
asset on launch/resume (at most once an hour while it stays open). A newer
Android version code shows an **Update now** dialog. The button opens the APK
download in your browser; open the downloaded file and confirm **Update** in
Android. You may need to allow installs from your browser once. Installation
is never silent. Offline/missing channels do not block startup.

**Settings → Android app updates → Check for updates** retries immediately,
even for a skipped version. **Later** postpones the dialog; **Skip this version**
suppresses that particular version. The desktop update banner is hidden on
Android so it cannot offer a Windows/macOS installer or confuse upstream's
version with the Android build version.

The app validates release URLs and compares the release's signing certificate
with the installed certificate before promising a data-preserving update. A
mismatch shows migration guidance and release notes instead. Android itself
verifies the APK signature during installation.

## One-time signing setup

GitHub-hosted runners' temporary debug keys cannot support in-place updates.
The update channel requires a permanently retained development key in the
repository secret `ANDROID_KEYSTORE_BASE64`. No release is published without it.

If you have the original testing key, put it at
`.signing/domestique-test.keystore` **before** running setup. Otherwise setup
creates a new one; migration from an old APK then needs special care because
Android rejects an in-place update signed by a different key. Do not uninstall
until you have saved any local data you need. Keeping the same package ID/key
on later updates preserves app data.

Run from a local checkout with JDK/keytool and gh authenticated with permission
to manage repository Actions secrets:

```sh
git switch mobile-app
git pull --ff-only
bash android/configure-updates.sh
```

The expected test-key alias is `androiddebugkey`, with the existing test-key
store/key password `android`. This is a development channel, not a production
signing configuration. Keep a private backup of the keystore; never commit it,
attach it to an issue, or publish it as an artifact. Do not paste it into chat.
The setup sends it directly into GitHub's encrypted repository secret.

## Ongoing development

Each push touching Android/backend files on `mobile-app` builds, lints, runs
update-policy unit tests and Android backend tests, then exercises the packaged
backend. Successful builds with the configured signer publish an immutable
prerelease `android-dev-<versionCode>` and advance `android-latest/update.json`.
PR builds and sync candidate branches never publish or restore the signing key.
You can also run **Android APK → Run workflow → mobile-app** manually.
Version codes are `1000 + GITHUB_RUN_NUMBER`; use a new workflow run rather
than rerunning a published build. Publishing refuses version rollback or signer
changes. The app checks the public manifest without a GitHub login/token.

Install the update-aware version once manually. Older APKs do not contain this
checker and cannot receive their first update through it. CI testing artifacts
built without the secret are disposable and are not the update channel.
