# Domestique for Android

An independent Android fork of [Domestique](https://github.com/platypus45/domestique), the cycling training planner. This repository focuses on the Android app.

For the original app, desktop downloads, features, training science, and general documentation, visit **[the original Domestique repository](https://github.com/platypus45/domestique)**.

## Android

- [Install and build](android/README.md)
- [APK updates and signing](android/UPDATES.md)
- [Upstream integration](android/UPSTREAM.md)
- [Android APK builds](https://github.com/NicholasKiefer/domestique/actions/workflows/android.yml)

This is an early testing build. See the Android documentation for supported devices and current limitations.

## Branches

- **`mobile-app`**: default branch for Android development and builds.
- **`clean-main`**: protected upstream baseline; Android changes belong on `mobile-app`.

Daily checks fast-forward `clean-main` from upstream and prepare draft integration PRs for `mobile-app`. Review and test the Android APK before merging those PRs.

## Attribution and license

Domestique is developed by the [upstream contributors](https://github.com/platypus45/domestique/graphs/contributors). This independent fork adds Android packaging and adaptations.

Apache-2.0 — see [LICENSE](LICENSE) and [NOTICE](NOTICE). Existing attribution and third-party notices are retained.
