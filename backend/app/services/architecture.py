import re

SDK_PATTERNS = (
    ("Firebase Analytics", "analytics", re.compile(r"com\.google\.firebase:firebase-analytics")),
    ("AppsFlyer", "attribution", re.compile(r"com\.appsflyer:af-android-sdk")),
    ("Adjust", "attribution", re.compile(r"com\.adjust\.sdk:adjust-android")),
    ("Meta Android SDK", "analytics", re.compile(r"com\.facebook\.android:facebook-android-sdk")),
    ("Sentry Android", "crash_reporting", re.compile(r"io\.sentry:sentry-android")),
    ("Branch", "attribution", re.compile(r"com\.branch\.sdk\.android:library")),
    ("Mixpanel", "analytics", re.compile(r"com\.mixpanel\.android:mixpanel-android")),
    ("Amplitude", "analytics", re.compile(r"com\.amplitude:android-sdk")),
)


def detect_declared_sdks(files: dict[str, str]) -> list[dict]:
    detections = []
    seen = set()
    for path, content in files.items():
        if not path.lower().endswith((
            "build.gradle",
            "build.gradle.kts",
            "libs.versions.toml",
        )):
            continue
        for line_number, line in enumerate(content.splitlines(), start=1):
            for name, category, pattern in SDK_PATTERNS:
                if name in seen or not pattern.search(line):
                    continue
                seen.add(name)
                detections.append({
                    "name": name,
                    "category": category,
                    "file_path": path,
                    "line_number": line_number,
                    "evidence": line.strip()[:300],
                    "confidence": "dependency_declared",
                    "explanation": (
                        "The dependency is declared in repository build configuration. "
                        "This does not prove the SDK is initialized or transmits data at runtime."
                    ),
                })
    return detections


def inspect_manifest_flags(manifest: str, file_path: str = "AndroidManifest.xml") -> list[dict]:
    findings = []
    for line_number, line in enumerate(manifest.splitlines(), start=1):
        if re.search(r'android:usesCleartextTraffic\s*=\s*"true"', line):
            findings.append({
                "category": "network_security",
                "severity": "high",
                "title": "Cleartext network traffic is enabled",
                "file_path": file_path,
                "line_number": line_number,
                "evidence": line.strip()[:300],
                "explanation": "The manifest explicitly enables cleartext traffic. Confirm whether this is required and restrict it with a network security configuration.",
            })
        if re.search(r'android:exported\s*=\s*"true"', line) and "android:permission" not in line:
            findings.append({
                "category": "component_exposure",
                "severity": "review",
                "title": "Exported component declaration needs review",
                "file_path": file_path,
                "line_number": line_number,
                "evidence": line.strip()[:300],
                "explanation": "An exported component can be reached by other apps. Review its intent filters and access controls; this line-only check cannot determine effective component protection.",
            })
    return findings
