#!/usr/bin/env python3
"""Build the credential-free Pixoticker release from this repo.

Usage (ESP-IDF export script sourced, so IDF_PATH is set):

    python tools/make_release.py OUTPUT_DIR [--deny-strings FILE] [--force]

Steps:
  1. Stage an allow-listed copy of the source: this repo's tools and docs plus
     the patched firmware-esp32/ submodule (only what a Pixoticker build needs;
     nothing else is shipped, so new upstream files stay out by default).
  2. Pack it as source.tar.gz (deterministic: sorted, no owners, zero mtimes).
  3. Build the firmware *from the staged copy* with tools/build_pixoticker.py
     in hotspot mode with no credentials, so the image matches the source.
  4. Add licences, release README (release/README.md template), provenance,
     SHA256SUMS, then OUTPUT_DIR.zip.
  5. Refuse to finish if any --deny-strings entry, or any value from a local
     firmware-esp32/secrets.json, appears in any output file or inside the
     source archive.

This script is not part of its own output.
"""

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECT = ROOT / "firmware-esp32"  # upstream ESP-IDF project, patched
PATCH_MARKER = "main/buffer_memory.h"  # added by patches/pixoticker.patch
ARCHIVE_ROOT = "pixoticker-public-source"
IMAGE_NAME = "pixoticker-tronbyt-public-0x0.bin"
PROFILES = ["sdkconfig.defaults", "sdkconfig.defaults.pixoticker",
            "sdkconfig.defaults.pixoticker-public"]

# Everything shipped in source.tar.gz. Paths are files or directories.
# From this repo, staged at the archive root:
ROOT_ALLOW = [
    ".gitignore",
    "HYBRID_IMAGE.md",
    "LICENSE",
    "README.md",
    "patches",
    "pixoticker-build.example.json",
    "tools/build_pixoticker.py",
]
# From the patched submodule, staged under firmware-esp32/:
PROJECT_ALLOW = [
    ".gitignore",
    "CMakeLists.txt",
    "LICENSE",
    "boards",
    "components",
    "dependencies.lock",
    "generate_secrets_cmake.py",
    "main",
    "managed_components",
    *PROFILES,
    "secrets.json.example",
    "secrets_place.json",
    "tools/patch_i2s_divider.py",  # run by CMakeLists.txt at configure time
]
# Never shipped, even inside allowed directories.
NEVER_NAMES = {"__pycache__", "secrets.json", "secrets.cmake", "custom_ca.pem",
               "pixoticker-build.json", ".DS_Store"}


def fail(message):
    print("ERROR: " + message, file=sys.stderr)
    sys.exit(1)


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def ignore(directory, names):
    def is_build_dir(name):
        return (name == "build" or name.startswith("build_")) and \
            os.path.isdir(os.path.join(directory, name))
    return [n for n in names if n in NEVER_NAMES or n.endswith(".pyc") or is_build_dir(n)]


def stage_tree(base, allow, dest):
    for relative in allow:
        src = base / relative
        if not src.exists():
            hint = ("; run tools/build_pixoticker.py once so ESP-IDF downloads them"
                    if relative in ("managed_components", "dependencies.lock") else "")
            fail("missing %s%s" % (src.relative_to(ROOT), hint))
        target = dest / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, target, ignore=ignore)
        else:
            shutil.copy2(src, target)


def stage_source(dest, version):
    if not (PROJECT / PATCH_MARKER).is_file():
        fail("firmware-esp32/ is not patched; run: "
             "git -C firmware-esp32 apply ../patches/pixoticker.patch")
    stage_tree(ROOT, ROOT_ALLOW, dest)
    stage_tree(PROJECT, PROJECT_ALLOW, dest / "firmware-esp32")
    (dest / "firmware-esp32" / "main" / "version.h").write_text(
        "// Release version label, set by tools/make_release.py\n\n"
        "#pragma once\n\n"
        "#ifndef FIRMWARE_VERSION\n"
        '#define FIRMWARE_VERSION "%s"\n'
        "#endif\n" % version, encoding="utf-8")


def pack_source(stage):
    def normalise(info):
        info.uid = info.gid = 0
        info.uname = info.gname = ""
        info.mtime = 0
        info.pax_headers = {}
        return info

    raw = io.BytesIO()
    with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as gz:
        with tarfile.open(fileobj=gz, mode="w", format=tarfile.PAX_FORMAT) as tar:
            for path in sorted(p for p in stage.rglob("*") if p.is_file()):
                if path.is_symlink():
                    fail("symlink in source: %s" % path.relative_to(stage))
                tar.add(path, arcname="%s/%s" % (ARCHIVE_ROOT, path.relative_to(stage).as_posix()),
                        recursive=False, filter=normalise)
    return raw.getvalue()


def build_image(stage, version, work):
    config = work / "release-build.json"
    config.write_text(json.dumps({"name": "release", "station_only": False,
                                  "wifi_ssid": "", "wifi_password": "",
                                  "remote_url": "", "version": version}))
    out = work / "dist"
    python = sys.executable
    result = subprocess.run([python, "tools/build_pixoticker.py", str(config),
                             "--output-dir", str(out)], cwd=str(stage))
    if result.returncode != 0:
        fail("firmware build failed")
    return (out / "pixoticker-release-0x0.bin").read_bytes()


def check_image(image):
    if len(image) != 4 * 1024 * 1024:
        fail("image is not 4 MB")
    for start, end, what in [(0x9000, 0xE000, "NVS"), (0x3F0000, 0x400000, "coredump")]:
        if image[start:end].count(b"\xff") != end - start:
            fail("%s region is not erased" % what)
    if image[0x1000] != 0xE9 or image[0x10000] != 0xE9:
        fail("bootloader/app image header missing")
    if image[0x8000:0x8002] != b"\xaa\x50":
        fail("partition table missing")


def idf_version():
    """Release version of the ESP-IDF checkout, e.g. 'ESP-IDF v5.5.6'."""
    cmake = Path(os.environ["IDF_PATH"]) / "tools" / "cmake" / "version.cmake"
    parts = dict(re.findall(r"set\(IDF_VERSION_(MAJOR|MINOR|PATCH) (\d+)\)",
                            cmake.read_text(encoding="utf-8")))
    if len(parts) != 3:
        fail("cannot read ESP-IDF version from %s" % cmake)
    return "ESP-IDF v%s.%s.%s" % (parts["MAJOR"], parts["MINOR"], parts["PATCH"])


def image_idf_ver(image):
    """idf_ver recorded in the app's esp_app_desc_t (the toolchain actually used)."""
    desc = image[0x10020:0x10020 + 256]
    if desc[:4] != b"\x32\x54\xcd\xab":
        fail("app descriptor not found in image")
    return desc[112:144].split(b"\0")[0].decode("ascii", "replace")


def deny_list(path):
    needles = []
    if path:
        needles += [line.strip() for line in Path(path).read_text(encoding="utf-8").splitlines()
                    if line.strip()]
    local = PROJECT / "secrets.json"
    if local.is_file():
        try:
            values = json.loads(local.read_text(encoding="utf-8")).values()
        except ValueError:
            values = []
        needles += [v for v in values if isinstance(v, str) and len(v) >= 4
                    and "Xplaceholder" not in v]
    return [n.encode("utf-8") for n in needles]


def scan(name, data, needles):
    for needle in needles:
        if needle in data:
            fail("a denied string appears in %s; release not written" % name)


def license_files():
    found = {"LICENSE": ROOT / "LICENSE"}
    for component in sorted((PROJECT / "managed_components").iterdir()):
        for candidate in sorted(component.glob("*")):
            if candidate.is_file() and candidate.name.upper().startswith(("LICENSE", "COPYING")):
                found["LICENSES/%s-%s" % (component.name, candidate.name)] = candidate
                break
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("output", help="release directory; OUTPUT.zip is written next to it")
    parser.add_argument("--version", default="pixoticker-public", help="boot-screen version label")
    parser.add_argument("--deny-strings", help="file of strings (one per line) that must not ship")
    parser.add_argument("--force", action="store_true", help="replace an existing OUTPUT dir/zip")
    options = parser.parse_args()

    if not os.environ.get("IDF_PATH"):
        fail("IDF_PATH is not set; run ESP-IDF's export script first")
    output = Path(options.output).resolve()
    archive_zip = output.with_name(output.name + ".zip")
    if (output.exists() and any(output.iterdir())) or archive_zip.exists():
        if not options.force:
            fail("%s exists; use --force to replace it" % output)
    needles = deny_list(options.deny_strings)

    with tempfile.TemporaryDirectory(prefix="pixoticker-release-") as tmp:
        work = Path(tmp)
        stage = work / ARCHIVE_ROOT
        stage_source(stage, options.version)
        source_tgz = pack_source(stage)
        scan("source.tar.gz", gzip.decompress(source_tgz), needles)
        image = build_image(stage, options.version, work)
        check_image(image)
        scan(IMAGE_NAME, image, needles)

    files = {IMAGE_NAME: image, "source.tar.gz": source_tgz}
    for name, path in license_files().items():
        files[name] = path.read_bytes()
    idf = idf_version()
    template = (ROOT / "release" / "README.md").read_text(encoding="utf-8")
    if needles:
        private_scan = ("Every output file and the source archive were scanned for %d "
                        "maintainer-supplied private strings; none were found."
                        % len(needles))
    else:
        private_scan = ("No private-string list was supplied, so the outputs were not "
                        "scanned for private values.")
    files["README.md"] = (template.replace("{{SHA256}}", sha256(image))
                          .replace("{{SIZE}}", "{:,}".format(len(image)))
                          .replace("{{VERSION}}", options.version)
                          .replace("{{IDF_VERSION}}", idf)
                          .replace("{{PRIVATE_SCAN}}", private_scan)).encode("utf-8")
    files["build-provenance.json"] = (json.dumps({
        "release": options.version,
        "target": "Pixoticker: ESP32, 4 MB flash, no PSRAM, 64x32 HUB75",
        "firmware": IMAGE_NAME,
        "firmware_sha256": sha256(image),
        "firmware_bytes": len(image),
        "flash": {"offset": "0x0", "mode": "dio", "frequency": "40m", "size": "4MB"},
        "toolchain": idf,
        "app_descriptor_idf_ver": image_idf_ver(image),
        "profiles": PROFILES,
        "provisioning": "TRON-CONFIG hotspot at http://10.10.0.1/; no credentials compiled in",
        "erased_regions": {"nvs": "0x9000-0xdfff", "coredump": "0x3f0000-0x3fffff"},
        "source_sha256": sha256(source_tgz),
        "built_from": "source.tar.gz contents (staged allow-list copy)",
    }, indent=2) + "\n").encode("utf-8")
    files["SHA256SUMS"] = "".join("%s  %s\n" % (sha256(data), name)
                                  for name, data in sorted(files.items())).encode("utf-8")
    for name, data in files.items():
        scan(name, data, needles)

    if output.exists():
        shutil.rmtree(output)
    for name, data in files.items():
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    with zipfile.ZipFile(archive_zip, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name in sorted(files):
            info = zipfile.ZipInfo("%s/%s" % (output.name, name), date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(info, files[name])

    print()
    print("Release: %s" % output)
    print("Zip:     %s" % archive_zip)
    print("Image:   %s  %s" % (sha256(image), IMAGE_NAME))
    print("Denied-string scan: %d strings checked" % len(needles))


if __name__ == "__main__":
    main()
