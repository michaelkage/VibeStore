from app.services.architecture import detect_declared_sdks, inspect_manifest_flags


def test_detects_declared_analytics_sdk_with_line_evidence():
    files = {
        "app/build.gradle.kts": """
            dependencies {
                implementation("com.google.firebase:firebase-analytics:22.0.0")
            }
        """
    }
    findings = detect_declared_sdks(files)
    assert len(findings) == 1
    assert findings[0]["name"] == "Firebase Analytics"
    assert findings[0]["line_number"] == 3
    assert findings[0]["confidence"] == "dependency_declared"


def test_ignores_sdk_mentions_outside_build_files():
    findings = detect_declared_sdks({
        "README.md": "com.google.firebase:firebase-analytics",
        "src/Main.kt": "com.google.firebase:firebase-analytics",
    })
    assert findings == []


def test_manifest_flags_include_line_level_evidence():
    manifest = """<manifest xmlns:android="http://schemas.android.com/apk/res/android">
    <application android:usesCleartextTraffic="true">
      <activity android:name=".MainActivity" android:exported="true" />
    </application>
    </manifest>"""
    findings = inspect_manifest_flags(manifest, "app/src/main/AndroidManifest.xml")
    assert [item["category"] for item in findings] == ["network_security", "component_exposure"]
    assert all(item["file_path"] == "app/src/main/AndroidManifest.xml" for item in findings)



def test_manifest_flags_detect_debug_backup_and_exported_components():
    manifest = """<manifest xmlns:android="http://schemas.android.com/apk/res/android">
      <application android:debuggable="true" android:allowBackup="true">
        <activity
          android:name=".ExposedActivity"
          android:exported="true" />
        <service android:name=".ProtectedService"
          android:exported="true"
          android:permission="dev.demo.ACCESS" />
      </application>
    </manifest>"""
    findings = inspect_manifest_flags(manifest, "app/src/main/AndroidManifest.xml")

    assert [item["category"] for item in findings] == [
        "build_configuration",
        "data_protection",
        "component_exposure",
    ]
    assert findings[-1]["evidence"].startswith("activity .ExposedActivity")
    assert findings[-1]["line_number"] == 4
