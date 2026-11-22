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
