---
description: Update backlog + changelog, bump version, commit, tag, and push a new release of the GammaSeries addon
---

Perform a full release of the addon in `addon/service.gammaseries/`:

1. Review the changes since the last release (`git log` since the last tag, and the working diff) to know what to document.
2. Update `addon/service.gammaseries/backlog.txt`: mark completed items with a leading `x`, remove items that are no longer relevant, keep the rest untouched.
3. Update `addon/service.gammaseries/changelog.txt`: add a new entry at the top describing the changes, following the existing style (version number, short bullet points, French).
4. Bump the `version` attribute in `addon/service.gammaseries/addon.xml` (semantic-ish patch/minor bump matching the changelog entry).
5. Stage the relevant files and commit with a concise message describing the release.
6. Create an annotated git tag `vX.Y.Z` matching the new version.
7. Push the commit and tag to `origin` (`git push origin main --follow-tags`), confirming with the user first per standard git-safety practice if anything about the repo state looks unusual.

If arguments are given ($ARGUMENTS), treat them as extra context on what to highlight in the changelog entry.
