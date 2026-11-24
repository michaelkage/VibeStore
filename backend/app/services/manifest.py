import xml.etree.ElementTree as ET

ANDROID_NS = "{http://schemas.android.com/apk/res/android}"
RISKY = {
 "android.permission.READ_CONTACTS": ("high", "Allows access to the user's contacts."),
 "android.permission.READ_CALL_LOG": ("high", "Allows access to call history."),
 "android.permission.RECORD_AUDIO": ("medium", "Allows microphone recording when granted."),
 "android.permission.CAMERA": ("medium", "Allows camera access when granted."),
 "android.permission.ACCESS_FINE_LOCATION": ("medium", "Allows precise device location access."),
 "android.permission.READ_SMS": ("high", "Allows reading SMS messages."),
 "android.permission.SEND_SMS": ("high", "Allows sending SMS messages."),
 "android.permission.READ_EXTERNAL_STORAGE": ("medium", "Allows access to shared external storage on older Android versions."),
 "android.permission.MANAGE_EXTERNAL_STORAGE": ("high", "Allows broad access to shared storage."),
}

def inspect_manifest(xml_content: str) -> dict:
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as exc:
        raise ValueError("AndroidManifest.xml is not valid XML") from exc
    findings = []
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] not in {"uses-permission", "uses-permission-sdk-23"}:
            continue
        permission = node.attrib.get(ANDROID_NS + "name")
        if permission:
            risk, explanation = RISKY.get(permission, ("informational", "Declared Android permission; review its use in app code."))
            findings.append({"permission": permission, "risk": risk, "explanation": explanation})
    return {"package_name": root.attrib.get("package"), "permissions": findings}
