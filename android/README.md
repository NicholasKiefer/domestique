# Domestique for Android (early testing build)

An ARM64 APK for Google Pixel, Android 8+ (API 26). It embeds Python and runs
the shared FastAPI backend on `127.0.0.1` inside the Android process. No desktop
server, Termux, or hosted account is required. It bundles the workout and route
libraries and stores athlete data in the app's private files directory.

Version 0.1.1 bundles the generated workout index and facts so opening the
Training Plan does not rebuild 4,308 workouts on the phone. Foreground Android
views use synced local wellness/activity records; explicit sync and background
workers still contact Intervals.icu. Connecting an API key runs the initial
wellness/activity sync and refreshes the displayed metrics. Sync failures are
shown separately from successful credential verification.

## Install on your Pixel

Download the testing APK provided in the conversation. CI build artifacts are
also available for a fresh install: download `domestique-pixel-debug-apk` from
the **Android APK** GitHub Actions run and unzip it. Open the APK on the phone. Allow your browser
or Files app to “Install unknown apps” when Android asks.

With USB debugging enabled, you can instead use:

```sh
adb install -r app-debug.apk
```

Open **Domestique**, allow the first launch to unpack the library, and complete
the setup wizard. Choose **Continue without intervals.icu** to test locally.
In Settings you can connect Intervals.icu using your personal API key (available
in Intervals.icu Settings → Developer settings). The Android preview does not
include the upstream OAuth client secret. FIT imports use Android's document
picker; ZWO, FIT, CRS and other exports use Android's Save dialog.

This is a debug-signed testing APK, not a Play Store release. Reinstalling an APK
with the **same signing key** keeps data; uninstalling deletes local athlete data.
GitHub-hosted debug signing keys change between runs, so CI artifacts may require
a fresh install. The locally distributed testing APK uses a retained private
test key at `.signing/domestique-test.keystore` (excluded from Git). Keep this file
to sign subsequent updates of that APK. Without it Gradle uses the local SDK debug
key. Production distribution needs its own release-signing setup. An APK signed
with a different key cannot update an installed copy; preserve athlete data before
uninstalling. GitHub's contents permission does not grant repository-secret access.

## Build locally

Install JDK 17, Python 3.10, and Android Studio / Android SDK 35. Set `ANDROID_HOME`
or create `android/local.properties` with `sdk.dir=/path/to/Android/sdk`.

```sh
cd android
./gradlew assembleDebug lintDebug
# If Python 3.10 is not on PATH:
./gradlew assembleDebug -PbuildPython=/path/to/python3.10
```

APK: `app/build/outputs/apk/debug/app-debug.apk` (ARM64). To build for an x86_64
emulator use `-PandroidAbi=x86_64`. The Gradle wrapper downloads Gradle 8.13.
The APK build downloads Android-compatible native wheels from Chaquopy.

Verify the packaged backend on a host in a Python 3.10 virtual environment:

```sh
python -m pip install -r app/requirements.txt pytest
python -m pytest -q tests
python smoke_backend.py
```

## Current limits

- The desktop interface is reused with phone layout adjustments; some dense
  tables and calendars still need horizontal scrolling.
- The backend lives while Android keeps the app process alive. Sync resumes
  when you reopen it; there is no continuous background service.
- Android wheels currently require SciPy 1.8.1 and NumPy 1.23.3 on Python 3.10.
  SciPy's newer MILP solver is unavailable; the planner uses its existing
  fallback. Desktop dependency versions are unchanged.
- These older scientific native libraries have 4 KB ELF alignment. Devices
  configured for 16 KB pages may require Android's compatibility mode. This
  preview is not ready for Play's 16 KB requirement.
- Desktop folder selection and desktop updater installers are not Android
  features. Use the bundled library, document imports/exports, and APK updates.
- Athlete credentials are stored in the app sandbox using the shared backend's
  credential writer; Android backup is disabled.

For startup failures or a blank screen, capture:

```sh
adb logcat -c
adb shell am force-stop com.domestique.android
adb shell monkey -p com.domestique.android 1
adb logcat -d -s Domestique python.stdout python.stderr AndroidRuntime
```
