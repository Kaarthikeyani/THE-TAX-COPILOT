"""Build the phone forwarder with the bare Android SDK tools (no Gradle, no downloads):  python build.py
Output: android/build/tax-copilot-sms.apk  (signed with a local debug key, for installing on your own phone).

Needs: the Android SDK (platform + build-tools; found via ANDROID_HOME or %LOCALAPPDATA%\\Android\\Sdk) and a JDK on PATH.
"""
import glob
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
IS_WIN = os.name == "nt"


def sdk() -> Path:
    for c in (os.environ.get("ANDROID_HOME"), os.environ.get("ANDROID_SDK_ROOT"),
              os.path.join(os.environ.get("LOCALAPPDATA", ""), "Android", "Sdk"), str(Path.home() / "Android" / "Sdk"),
              str(Path.home() / "Library" / "Android" / "sdk")):
        if c and Path(c).is_dir():
            return Path(c)
    sys.exit("Android SDK not found. Set ANDROID_HOME.")


def newest(parent: Path) -> Path:
    items = sorted([p for p in parent.iterdir() if p.is_dir()], key=lambda p: [int(x) if x.isdigit() else 0 for x in p.name.replace("android-", "").split(".")])
    if not items:
        sys.exit(f"Nothing installed in {parent}")
    return items[-1]


def tool(bt: Path, name: str) -> str:
    for ext in ((".exe", ".bat", "") if IS_WIN else ("", )):
        p = bt / (name + ext)
        if p.exists():
            return str(p)
    sys.exit(f"{name} not found in {bt}")


def jdk_tool(name: str) -> str:
    """keytool/javac may be missing from PATH even when java works (Windows shims): ask java where its home is."""
    found = shutil.which(name)
    if found:
        return found
    out = subprocess.run(["java", "-XshowSettings:properties", "-version"], capture_output=True, text=True).stderr
    for line in out.splitlines():
        if line.strip().startswith("java.home"):
            p = Path(line.split("=", 1)[1].strip()) / "bin" / (name + (".exe" if IS_WIN else ""))
            if p.exists():
                return str(p)
    sys.exit(f"{name} not found. Install a JDK or set PATH.")


def run(*cmd):
    r = subprocess.run([str(c) for c in cmd], capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"FAILED: {' '.join(map(str, cmd[:2]))}\n{r.stdout}\n{r.stderr}")
    return r.stdout


def main():
    s = sdk()
    bt = newest(s / "build-tools")
    plat = newest(s / "platforms")
    jar = plat / "android.jar"
    print(f"SDK {s}\n build-tools {bt.name}, platform {plat.name}")
    shutil.rmtree(BUILD, ignore_errors=True)
    (BUILD / "classes").mkdir(parents=True)
    (BUILD / "dex").mkdir()

    run(tool(bt, "aapt2"), "link", "-o", BUILD / "base.apk", "-I", jar, "--manifest", HERE / "AndroidManifest.xml",
        "--min-sdk-version", "26", "--target-sdk-version", "34")
    srcs = glob.glob(str(HERE / "src" / "**" / "*.java"), recursive=True)
    run(jdk_tool("javac"), "--release", "8", "-Xlint:-options", "-cp", jar, "-d", BUILD / "classes", *srcs)
    classes = glob.glob(str(BUILD / "classes" / "**" / "*.class"), recursive=True)
    run(tool(bt, "d8"), "--lib", jar, "--min-api", "26", "--output", BUILD / "dex", *classes)

    unsigned = BUILD / "unsigned.apk"
    with zipfile.ZipFile(BUILD / "base.apk") as zin, zipfile.ZipFile(unsigned, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            zout.writestr(item, zin.read(item.filename))
        zout.write(BUILD / "dex" / "classes.dex", "classes.dex")
    aligned = BUILD / "aligned.apk"
    run(tool(bt, "zipalign"), "-f", "4", unsigned, aligned)

    ks = HERE / "debug.keystore"  # git-ignored; makes updates install over the previous build
    if not ks.exists():
        run(jdk_tool("keytool"), "-genkeypair", "-keystore", ks, "-storepass", "android", "-keypass", "android", "-alias", "tcp",
            "-keyalg", "RSA", "-keysize", "2048", "-validity", "10000", "-dname", "CN=Tax Co-Pilot SMS")
    out = BUILD / "tax-copilot-sms.apk"
    run(tool(bt, "apksigner"), "sign", "--ks", ks, "--ks-pass", "pass:android", "--key-pass", "pass:android", "--out", out, aligned)
    run(tool(bt, "apksigner"), "verify", out)
    print(f"Built {out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
