#!/usr/bin/env bash
# Run locally, signed into gh with permission to manage this repository's secrets.
set -euo pipefail
cd "$(dirname "$0")/.."
keyfile=.signing/domestique-test.keystore
if [ ! -f "$keyfile" ]; then
  echo 'No retained test key found. Creating a new key; older APKs cannot update in place with it.'
  mkdir -p .signing
  chmod 700 .signing
  keytool -genkeypair -keystore "$keyfile" -storepass android -keypass android \
    -alias androiddebugkey -keyalg RSA -keysize 3072 -validity 10000 \
    -dname 'CN=Domestique Android Development' -storetype JKS
fi
chmod 600 "$keyfile"
# Validate the expected alias/password without printing key material.
keytool -list -keystore "$keyfile" -storepass android -alias androiddebugkey >/dev/null
base64 < "$keyfile" | gh secret set ANDROID_KEYSTORE_BASE64 --repo NicholasKiefer/domestique
printf '%s\n' 'Signing secret configured. Keep a private backup of the keystore.'
gh workflow run android.yml --repo NicholasKiefer/domestique --ref mobile-app
