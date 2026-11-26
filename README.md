# VibeStore

**An AI-native open-source Android app store. Discover apps by intent, inspect how they work, and remix their source with AI.**

VibeStore combines an Android application discovery experience with repository intelligence and a prompt-first modification workflow. Its long-term product direction is an AI-first F-Droid meets GitHub: users discover open-source Android apps, inspect permissions and architecture, request source changes conversationally, and ultimately build, sign, install and update their own variants.

## Product workflows

- **Discover:** search an open-source Android catalog using app names, features or natural-language intent.
- **Inspect & X-Ray:** review Android manifest permissions, declared SDKs, manifest security indicators and repository architecture, with evidence and limitations.
- **Fork & Vibe:** create a remix session pinned to a source commit, ask for a change plan, generate reviewable unified diffs, validate them against exact source blobs, and approve or reject proposals.
- **Build and distribute (in progress):** isolated Gradle builds, signing, APK delivery and generated-app update management are planned platform capabilities. The current patch worker materializes approved changed source files into a review-only ZIP; it does not execute repository code or build APKs.

## Repository layout

- `lib/`: Flutter Android application and VibeStore discovery/remix UI.
- `backend/`: FastAPI service, PostgreSQL/pgvector persistence, Redis/Arq workers and migrations.
- `docs/`: contributor and developer documentation.
- `.github/workflows/`: backend and Flutter CI workflows.

## Website

[ VibeStore website ](https://michaelkage.github.io/VibeStore/)

## Backend development

See [backend/README.md](backend/README.md) for environment configuration, migrations, API routes, worker architecture and security boundaries.

## Flutter development

The Android client is a Flutter application. Install Flutter using the official [Flutter documentation](https://docs.flutter.dev/get-started/install), then run:

```bash
flutter pub get
flutter analyze
flutter test
```

## Project status

The repository currently includes bounded GitHub, GitLab.com and Codeberg indexing of Android manifests, build configuration and selected Kotlin/Java/XML source files; paginated catalog browsing; license/popularity-filtered lexical and semantic search; richer static X-Ray reports; selectable source context in Remix Studio; personal favorites and recent-app library; rotating refresh-token sessions; source-pinned GitHub patch proposals; exact-source diff validation; and isolated review-only source artifact generation.

It does **not** yet provide arbitrary repository Gradle execution, APK signing, APK distribution or generated-app update feeds. Those capabilities must be implemented as separate, isolated services; the API process must never execute untrusted repository code or hold user signing keys.

## License

This project is licensed under the GNU General Public License v3.0. See [LICENSE](LICENSE).
