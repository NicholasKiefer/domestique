# Domestique for Android (early testing build)

An ARM64 APK for Google Pixel, Android 8+ (API 26). It embeds Python and runs
the shared FastAPI backend on `127.0.0.1` inside the Android process. No desktop
server, Termux, or hosted account is required. It bundles the workout and route
libraries and stores athlete data in the app's private files directory.

## Install on your Pixel

Download the `domestique-pixel-debug-apk` artifact from the **Android APK** GitHub
Actions run, unzip it, and open `app-debug.apk` on the phone. Allow your browser
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
GitHub-hosted debug signing keys can change between runs: export any data you need
before switching signing keys. Local Gradle builds reuse your local debug key.

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
