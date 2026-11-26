import re
import xml.etree.ElementTree as ET

from app.services.manifest import ANDROID, _local_name

SDK_PATTERNS = (
    ("Firebase Analytics", "analytics", re.compile(r"com\\.google\\.firebase:firebase-analytics")),
    ("Firebase Crashlytics", "crash_reporting", re.compile(r"com\\.google\\.firebase:firebase-crashlytics")),
    ("Google Mobile Ads", "advertising", re.compile(r"com\\.google\\.android\\.gms:play-services-ads")),
    ("AppsFlyer", "attribution", re.compile(r"com\\.appsflyer:af-android-sdk")),
    ("Adjust", "attribution", re.compile(r"com\\.adjust\\.sdk:adjust-android")),
    ("Meta Android SDK", "analytics", re.compile(r"com\\.facebook\\.android:facebook-android-sdk")),
    ("Sentry Android", "crash_reporting", re.compile(r"io\\.sentry:sentry-android")),
    ("Branch", "attribution", re.compile(r"com\\.branch\\.sdk\\.android:library")),
    ("Mixpanel", "analytics", re.compile(r"com\\.mixpanel\\.android:mixpanel-android")),
    ("Amplitude", "analytics", re.compile(r"com\\.amplitude:android-sdk")),
    ("AppLovin", "advertising", re.compile(r"com\\.applovin:applovin-sdk")),
    ("Unity Ads", "advertising", re.compile(r"com\\.unity3d\\.ads:unity-ads")),
    ("OneSignal", "push_notifications", re.compile(r"com\\.onesignal:OneSignal")),
    ("PostHog", "product_analytics", re.compile(r"com\\.posthog:posthog-android")),
    ("Bugsnag", "crash_reporting", re.compile(r"com\\.bugsnag:bugsnag-android")),
    ("Datadog", "observability", re.compile(r"com\\.datadoghq:dd-sdk-android")),
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


def _line_number_for_attribute(manifest: str, attribute: str, value: str) -> int:
    pattern = re.compile(
        rf"android:{re.escape(attribute)}\\s*=\\s*[\"']{re.escape(value)}[\"']"
    )
    match = pattern.search(manifest)
    return manifest.count("\\n", 0, match.start()) + 1 if match else 1


def inspect_manifest_flags(manifest: str, file_path: str = "AndroidManifest.xml") -> list[dict]:
    try:
        root = ET.fromstring(manifest)
    except ET.ParseError:
        return []

    findings = []
    application = next(
        (node for node in root if _local_name(node.tag) == "application"),
        None,
    )
    if application is None:
        return findings

    flag_rules = (
        (
            "usesCleartextTraffic",
            "true",
            "network_security",
            "high",
            "Cleartext network traffic is enabled",
            "The manifest enables cleartext traffic. Review whether this is required and restrict it with a network security configuration.",
        ),
        (
            "debuggable",
            "true",
            "build_configuration",
            "high",
            "Debuggable application build is declared",
            "The application manifest explicitly enables debugging. Ensure release variants override this setting.",
        ),
        (
            "allowBackup",
            "true",
            "data_protection",
            "review",
            "Application backup is enabled",
            "Android backup may include application data. Review backup rules and whether sensitive data is excluded.",
        ),
    )
    for attribute, expected, category, severity, title, explanation in flag_rules:
        if application.attrib.get(ANDROID + attribute, "").lower() == expected:
            findings.append({
                "category": category,
                "severity": severity,
                "title": title,
                "file_path": file_path,
                "line_number": _line_number_for_attribute(manifest, attribute, expected),
                "evidence": f"android:{attribute}=\"{expected}\"",
                "explanation": explanation,
            })

    application_permission = application.attrib.get(ANDROID + "permission")
    component_names = {"activity", "activity-alias", "service", "receiver", "provider"}
    for component in application:
        if _local_name(component.tag) not in component_names:
            continue
        if component.attrib.get(ANDROID + "exported", "").lower() != "true":
            continue
        if component.attrib.get(ANDROID + "permission") or application_permission:
            continue
        component_name = component.attrib.get(ANDROID + "name", "unnamed component")
        line_number = _line_number_for_attribute(
            manifest,
            "name",
            component_name,
        ) if component_name != "unnamed component" else 1
        findings.append({
            "category": "component_exposure",
            "severity": "review",
            "title": "Exported component has no manifest permission",
            "file_path": file_path,
            "line_number": line_number,
            "evidence": f"{_local_name(component.tag)} {component_name} android:exported=\"true\"",
            "explanation": (
                "Other apps may be able to invoke this exported component. Review its "
                "intent filters, input validation and runtime authorization."
            ),
        })
    return findings
