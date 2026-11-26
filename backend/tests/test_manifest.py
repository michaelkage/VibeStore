from app.services.manifest import inspect_manifest

def test_manifest_extracts_package_and_permission_risk():
    xml = """<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="dev.example">
      <uses-permission android:name="android.permission.CAMERA" />
      <uses-permission android:name="android.permission.READ_CONTACTS" />
    </manifest>"""
    result = inspect_manifest(xml)
    assert result["package_name"] == "dev.example"
    assert [p["risk"] for p in result["permissions"]] == ["medium", "high"]

def test_manifest_with_no_permissions_is_valid():
    assert inspect_manifest('<manifest package="dev.empty" />') == {
        "package_name": "dev.empty", "permissions": []
}



def test_manifest_extracts_sdk_configuration_features_and_application_flags():
    xml = """<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="dev.demo">
      <uses-sdk android:minSdkVersion="23" android:targetSdkVersion="35" />
      <uses-feature android:name="android.hardware.camera" android:required="false" />
      <application android:allowBackup="false" android:debuggable="true"
          android:networkSecurityConfig="@xml/network_security_config" />
    </manifest>"""
    report = inspect_manifest(xml)

    assert report["sdk_configuration"]["min_sdk_version"] == "23"
    assert report["sdk_configuration"]["target_sdk_version"] == "35"
    assert report["declared_features"] == [
        {"name": "android.hardware.camera", "required": False, "version": None}
    ]
    assert {"name": "debuggable", "value": "true"} in report["application_flags"]
    assert {"name": "allow_backup", "value": "false"} in report["application_flags"]
