from app.services.inspection import build_static_inspection


def test_static_inspection_preserves_evidence_and_limits_claims():
    files = {
        "app/src/main/AndroidManifest.xml": """<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="dev.demo">
          <uses-permission android:name="android.permission.CAMERA" />
          <application android:usesCleartextTraffic="true" />
        </manifest>""",
        "app/build.gradle.kts": 'dependencies { implementation("com.google.firebase:firebase-analytics:22.0.0") }',
        "app/src/main/kotlin/MainActivity.kt": "class MainActivity",
    }

    report = build_static_inspection(files)

    assert report["manifest_found"] is True
    assert report["package_name"] == "dev.demo"
    assert report["permissions"][0]["permission"] == "android.permission.CAMERA"
    assert report["sdk_detections"][0]["name"] == "Firebase Analytics"
    assert report["manifest_warnings"][0]["category"] == "network_security"
    assert "Kotlin source tree" in report["architecture_indicators"]
    assert report["ai_summary"] is None
    assert any("do not prove runtime use" in item for item in report["limitations"])


def test_static_inspection_without_manifest_is_explicit():
    report = build_static_inspection({"README.md": "# Sample app"})

    assert report["manifest_found"] is False
    assert report["permissions"] == []
    assert any("No AndroidManifest.xml" in item for item in report["limitations"])
