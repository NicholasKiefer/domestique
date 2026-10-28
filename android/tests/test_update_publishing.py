"""Release publication must never rotate the installed app's signer or roll back."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

SPEC = importlib.util.spec_from_file_location('publish_update', Path(__file__).parents[1] / 'publish_update.py')
publisher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(publisher)
CERT = 'a' * 64


def setup_release(monkeypatch, tmp_path, previous=None):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('ANDROID_HOME', '/fake-sdk')
    monkeypatch.setenv('GITHUB_SHA', 'test-source-commit')
    apk = tmp_path / 'android/app/build/outputs/apk/debug/app-debug.apk'
    apk.parent.mkdir(parents=True)
    apk.write_bytes(b'verified-apk-fixture')
    calls = []
    metadata = {
        'aapt': "package: name='com.domestique.android' versionCode='1020' versionName='0.1.3-dev.20'",
        'apksigner': f'Signer #1 certificate SHA-256 digest: {CERT}',
    }
    monkeypatch.setattr(publisher, 'run', lambda tool, *args: metadata[Path(tool).name])

    def command(args, **kwargs):
        calls.append(args)
        if args[:3] == ['gh', 'release', 'view']:
            return SimpleNamespace(returncode=0 if previous else 1)
        if args[:3] == ['gh', 'release', 'download']:
            (Path(args[args.index('--dir') + 1]) / 'update.json').write_text(json.dumps(previous))
        if args[:3] == ['gh', 'release', 'upload']:
            calls.append(json.loads(Path(args[4]).read_text()))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(publisher.subprocess, 'run', command)
    return calls, metadata


def test_channel_advances_only_after_immutable_apk_release(monkeypatch, tmp_path):
    calls, _ = setup_release(monkeypatch, tmp_path)
    publisher.main()
    release = next(i for i, call in enumerate(calls) if call[:3] == ['gh', 'release', 'create'])
    channel = next(i for i, call in enumerate(calls) if call[:3] == ['gh', 'release', 'upload'])
    assert release < channel
    manifest = calls[-1]
    assert manifest['version_code'] == 1020
    assert '/android-dev-1020/' in manifest['apk_url']
    assert manifest['certificate_sha256'] == CERT


@pytest.mark.parametrize('previous,reason', [
    ({'certificate_sha256': 'b' * 64, 'version_code': 1019}, 'Signing key changed'),
    ({'certificate_sha256': CERT, 'version_code': 1020}, 'Version code must increase'),
    ({'certificate_sha256': CERT, 'version_code': 1021}, 'Version code must increase'),
])
def test_unsafe_release_cannot_modify_update_channel(monkeypatch, tmp_path, previous, reason):
    calls, _ = setup_release(monkeypatch, tmp_path, previous)
    with pytest.raises(SystemExit, match=reason):
        publisher.main()
    assert not any(call[:3] in (['gh', 'release', 'create'], ['gh', 'release', 'upload']) for call in calls)


def test_different_application_is_never_published(monkeypatch, tmp_path):
    calls, metadata = setup_release(monkeypatch, tmp_path)
    metadata['aapt'] = metadata['aapt'].replace('com.domestique.android', 'other.application')
    with pytest.raises(SystemExit, match='Unexpected APK'):
        publisher.main()
    assert not calls
