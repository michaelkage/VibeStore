import xml.etree.ElementTree as ET

ANDROID_NS = "http://schemas.android.com/apk/res/android"
ANDROID = f"{{{ANDROID_NS}}}"
RISKY = {
    "android.permission.READ_CONTACTS": ("high", "Allows access to the user's contacts."),
    "android.permission.READ_CALL_LOG": ("high", "Allows access to call history."),
    "android.permission.RECORD_AUDIO": ("medium", "Allows microphone recording when granted."),
    "android.permission.CAMERA": ("medium", "Allows camera access when granted."),
    "android.permission.ACCESS_FINE_LOCATION": ("medium", "Allows precise device location access."),
    "android.permission.READ_SMS": ("high", "Allows reading SMS messages."),
    "android.permission.SEND_SMS": ("high", "Allows sending SMS messages."),
    "android.permission.READ_EXTERNAL_STORAGE": (
        "medium",
        "Allows access to shared external storage on older Android versions.",
    ),
    "android.permission.MANAGE_EXTERNAL_STORAGE": (
        "high",
        "Allows broad access to shared storage.",
    ),
}


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def inspect_manifest(xml_content: str) -> dict:
    try:
        root = ET.fromstring(xml_content)
    except ET.ParseError as exc:
        raise ValueError("AndroidManifest.xml is not valid XML") from exc

    permissions = []
    for node in root.iter():
        if _local_name(node.tag) not in {
            "uses-permission",
            "uses-permission-sdk-23",
        }:
            continue
        permission = node.attrib.get(ANDROID + "name")
        if permission:
            risk, explanation = RISKY.get(
                permission,
                ("informational", "Declared Android permission; review its use in app code."),
            )
            permissions.append(
                {
                    "permission": permission,
                    "risk": risk,
                    "explanation": explanation,
                }
            )

    uses_sdk = next(
        (node for node in root if _local_name(node.tag) == "uses-sdk"),
        None,
    )
    sdk_configuration = {
        key: uses_sdk.attrib.get(ANDROID + attribute) if uses_sdk is not None else None
        for key, attribute in (
            ("min_sdk_version", "minSdkVersion"),
            ("target_sdk_version", "targetSdkVersion"),
            ("max_sdk_version", "maxSdkVersion"),
        )
    }
    features = [
        {
            "name": node.attrib.get(ANDROID + "name"),
            "required": node.attrib.get(ANDROID + "required", "true").lower() == "true",
            "version": node.attrib.get(ANDROID + "version"),
        }
        for node in root
        if _local_name(node.tag) == "uses-feature"
    ]
    application = next(
        (node for node in root if _local_name(node.tag) == "application"),
        None,
    )
    application_flags = []
    if application is not None:
        for key, attribute in (
            ("debuggable", "debuggable"),
            ("allow_backup", "allowBackup"),
            ("uses_cleartext_traffic", "usesCleartextTraffic"),
            ("network_security_config", "networkSecurityConfig"),
            ("full_backup_content", "fullBackupContent"),
            ("data_extraction_rules", "dataExtractionRules"),
        ):
            value = application.attrib.get(ANDROID + attribute)
            if value is not None:
                application_flags.append({"name": key, "value": value})

    return {
        "package_name": root.attrib.get("package"),
        "permissions": permissions,
        "sdk_configuration": sdk_configuration,
        "declared_features": features,
        "application_flags": application_flags,
    }
