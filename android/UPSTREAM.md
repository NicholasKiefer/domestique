# Maintaining the Android fork

Upstream's default branch is `clean-main` (not `main`). `mobile-app` is the
long-lived Android branch and the fork’s default branch. `clean-main` is a
protected upstream baseline; do not merge Android PRs into it. Keep Android-specific code under `android/` and
minimize changes in shared Python/templates to reduce update conflicts.
The original `android/pixel-apk` branch remains as a historical reference.

The **Sync upstream into mobile** workflow runs daily at 06:23 UTC and can also
be run manually. It detects upstream's default branch, fast-forwards
`clean-main` (refusing divergent history), then merges new commits into
`sync/mobile-upstream`, opens a draft PR targeting `mobile-app`, and explicitly
starts the Android APK build. If there are conflicts it fails without changing
`mobile-app`. Review the build and test the APK before merging the PR.
GitHub must allow Actions to create pull requests (repository Settings →
Actions → General → Workflow permissions). The workflow must exist on the
repository's default branch for the schedule to run.

For a manual update:

```sh
git switch mobile-app
git pull --ff-only origin mobile-app
git remote add upstream https://github.com/platypus45/domestique.git # once
git fetch upstream
git switch -c update/mobile-upstream
git merge upstream/clean-main
# Resolve conflicts, git add the files, then git merge --continue if necessary.
git push -u origin update/mobile-upstream
gh pr create --draft --base mobile-app
```

Use merges for this shared branch: they preserve commit identities and avoid
force-pushing the branch people build from. A rebase is useful on a private
feature branch; it does not reduce the work of resolving upstream conflicts.
The initial mobile-app branch was rebased onto upstream v3.13.2's latest commit.

API-key login remains supported. OAuth needs its own Android browser/redirect
flow. Sync runs while the app process is alive; reopening allows it to resume.
A reliable scheduled background sync would need Android WorkManager and testing
under battery restrictions. Keep the documented scientific-library and 16 KB
page-size limits in mind when upgrading dependencies. Passing desktop tests
alone does not establish Android compatibility.

Install updates with the same signing key to preserve app data. Fresh CI runners
currently produce disposable debug keys; keep a retained local test key for
in-place upgrades. Never commit that key. See README.md for build instructions.
