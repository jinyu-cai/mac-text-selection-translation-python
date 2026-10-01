"""Display the running bundle's version, with a source checkout fallback."""

from Foundation import NSBundle

from mactranslator import BUNDLE_ID, VERSION


def version_label():
    bundle = NSBundle.mainBundle()
    if bundle.bundleIdentifier() == BUNDLE_ID:
        version = bundle.objectForInfoDictionaryKey_("CFBundleShortVersionString") or VERSION
        build = bundle.objectForInfoDictionaryKey_("CFBundleVersion")
        return f"Version {version}" + (f" (Build {build})" if build else "")
    return f"Version {VERSION} (Development)"
