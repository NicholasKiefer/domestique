#!/usr/bin/env python3
"""Publish a verified, signed APK and advance the fork's Android update channel.

Run only after build/lint/backend checks. Requires gh, Android build-tools, and
GH_TOKEN with release permissions. Never handles the signing key itself.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

REPO = 'NicholasKiefer/domestique'


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def main():
    apk = Path('android/app/build/outputs/apk/debug/app-debug.apk').resolve()
    build_tools = Path(os.environ['ANDROID_HOME']) / 'build-tools/35.0.0'
    badging = run(str(build_tools / 'aapt'), 'dump', 'badging', str(apk))
    package = re.search(r"package: name='([^']+)' versionCode='(\d+)' versionName='([^']+)'", badging)
    if not package or package[1] != 'com.domestique.android':
        raise SystemExit('Unexpected APK package/version')
    code, version = int(package[2]), package[3]
    certificates = run(str(build_tools / 'apksigner'), 'verify', '--print-certs', str(apk))
    certificate = re.search(r'Signer #1 certificate SHA-256 digest: ([0-9a-fA-F]{64})', certificates)
    if not certificate or 'Signer #2 certificate' in certificates:
        raise SystemExit('Expected one verified APK signer')
    digest = certificate[1].lower()
    # Refuse accidental channel key rotation or version rollback.
    with tempfile.TemporaryDirectory() as old_dir:
        exists = subprocess.run(['gh', 'release', 'view', 'android-latest', '--repo', REPO],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
        if exists:
            subprocess.run(['gh', 'release', 'download', 'android-latest', '--repo', REPO,
                            '--pattern', 'update.json', '--dir', old_dir], check=True)
            previous = json.loads((Path(old_dir) / 'update.json').read_text())
            if previous['certificate_sha256'] != digest:
                raise SystemExit('Signing key changed: refusing to break installed updates')
            if previous['version_code'] >= code:
                raise SystemExit('Version code must increase; start a new workflow run instead of rerunning')
    tag = f'android-dev-{code}'
    filename = f'domestique-{version}.apk'
    manifest = {
        'application_id': package[1], 'version_code': code, 'version_name': version,
        'certificate_sha256': digest, 'sha256': hashlib.sha256(apk.read_bytes()).hexdigest(),
        'apk_url': f'https://github.com/{REPO}/releases/download/{tag}/{filename}',
        'release_url': f'https://github.com/{REPO}/releases/tag/{tag}',
    }
    commit = os.environ['GITHUB_SHA']
    notes = (f'Android development build {version}, source commit {commit}.\n\n'
             'Download the APK, open it, and confirm Update in Android. Same-key updates preserve app data.\n\n'
             'First migration: earlier test APKs used different signing keys. If Android rejects an update, '
             'do not uninstall until you have saved your data. Alternatively rebuild this version with '
             'your original retained test key. Never send anyone your API key or signing key.\n\n'
             'Install this update-aware build once; future development builds are offered inside the app. '
             'This preview is for ARM64 Android 8+ and retains the native-library limitations in android/README.md.')
    with tempfile.TemporaryDirectory() as work:
        directory = Path(work)
        published_apk = directory / filename
        published_apk.write_bytes(apk.read_bytes())
        notes_file = directory / 'notes.md'
        notes_file.write_text(notes)
        manifest_file = directory / 'update.json'
        manifest_file.write_text(json.dumps(manifest, indent=2) + '\n')
        subprocess.run(['gh', 'release', 'create', tag, str(published_apk), '--repo', REPO,
                        '--target', commit, '--prerelease', '--title', f'Android {version}',
                        '--notes-file', str(notes_file)], check=True)
        if not exists:
            subprocess.run(['gh', 'release', 'create', 'android-latest', '--repo', REPO,
                            '--target', commit, '--prerelease', '--title', 'Latest Android development build',
                            '--notes', 'Update channel metadata. Download the APK linked by update.json.'], check=True)
        # Advance only after the immutable APK release is available.
        subprocess.run(['gh', 'release', 'upload', 'android-latest', str(manifest_file),
                        '--repo', REPO, '--clobber'], check=True)
    print(f'Published Android update {code}: {manifest["release_url"]}')


if __name__ == '__main__':
    main()
