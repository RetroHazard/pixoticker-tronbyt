#!/usr/bin/env python3
"""Build a personalised Pixoticker full-flash image from one config file.

Usage (after sourcing ESP-IDF's export script so IDF_PATH is set, with the
firmware-esp32 submodule checked out and patches/pixoticker.patch applied):

    python tools/build_pixoticker.py pixoticker-build.json

Copy pixoticker-build.example.json, fill in your values, and run. The script
writes secrets.json into firmware-esp32/ for the duration of the build, forces
a fresh sdkconfig so the Pixoticker defaults apply, builds, merges a 4 MB image
flashable at 0x0, and deletes secrets.json / secrets.cmake / the generated
certificate unless --keep-secrets is given. Credentials are never printed.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROJECT = ROOT / "firmware-esp32"  # upstream ESP-IDF project, patched
PATCH_MARKER = "main/buffer_memory.h"  # added by patches/pixoticker.patch
MAX_SSID_LEN = 32  # main/nvs_settings.h
MAX_PASSWORD_LEN = 64
MAX_URL_LEN = 128
COMMON_PROFILES = ["sdkconfig.defaults", "sdkconfig.defaults.pixoticker"]
PORTAL_PROFILE = "sdkconfig.defaults.pixoticker-public"
SECRET_OUTPUTS = ["secrets.json", "secrets.cmake", "main/certs/custom_ca.pem"]


def fail(message):
    print("ERROR: " + message, file=sys.stderr)
    sys.exit(1)


def load_config(path):
    try:
        config = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        fail("cannot read %s: %s" % (path, exc))
    if not isinstance(config, dict):
        fail("config must be a JSON object")

    name = str(config.get("name", "")).strip()
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,40}", name):
        fail('"name" must be 1-40 characters of letters, digits, ".", "_" or "-"')

    ssid = str(config.get("wifi_ssid", ""))
    password = str(config.get("wifi_password", ""))
    url = str(config.get("remote_url", "")).strip()
    station_only = config.get("station_only", True)
    custom_ca = config.get("custom_ca", "") or ""
    version = str(config.get("version", "")).strip() or "pixoticker-" + name

    if not isinstance(station_only, bool):
        fail('"station_only" must be true or false')
    if "Xplaceholder" in ssid or "Xplaceholder" in password or "Xplaceholder" in url:
        fail("replace the placeholder values before building")
    if not ssid.strip():
        if station_only:
            fail('"wifi_ssid" is required when "station_only" is true; a station-only '
                 "image without credentials can never join a network and has no portal")
    elif len(ssid.encode("utf-8")) > MAX_SSID_LEN:
        fail('"wifi_ssid" exceeds %d bytes' % MAX_SSID_LEN)
    if len(password.encode("utf-8")) > MAX_PASSWORD_LEN:
        fail('"wifi_password" exceeds %d bytes' % MAX_PASSWORD_LEN)
    if password and len(password.encode("utf-8")) < 8:
        fail('"wifi_password" must be empty (open network) or at least 8 characters')
    if url:
        if not re.match(r"^https?://", url):
            fail('"remote_url" must start with http:// or https://')
        if len(url.encode("utf-8")) > MAX_URL_LEN:
            fail('"remote_url" exceeds %d bytes' % MAX_URL_LEN)
    elif station_only:
        print("WARNING: no remote_url; station-only image will connect but display nothing "
              "until a URL is provided over the server/websocket.")
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,31}", version):
        fail('"version" must be 1-31 characters of letters, digits, ".", "_" or "-"')

    return {
        "name": name,
        "ssid": ssid,
        "password": password,
        "url": url,
        "station_only": station_only,
        "custom_ca": custom_ca,
        "version": version,
    }


def idf_command():
    idf_path = os.environ.get("IDF_PATH")
    if not idf_path or not (Path(idf_path) / "tools" / "idf.py").is_file():
        fail("IDF_PATH is not set to an ESP-IDF checkout; run ESP-IDF's export script first")
    env_path = os.environ.get("IDF_PYTHON_ENV_PATH")
    python = None
    if env_path:
        candidate = Path(env_path) / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if candidate.is_file():
            python = str(candidate)
    if python is None:
        python = sys.executable
    return [python, str(Path(idf_path) / "tools" / "idf.py")]


def write_secrets(cfg):
    if not (cfg["ssid"] or cfg["url"] or cfg["custom_ca"]):
        # Credential-free: let generate_secrets_cmake.py fall back to secrets_place.json,
        # whose placeholder values the firmware recognises and never saves.
        return
    secrets = {"WIFI_SSID": cfg["ssid"], "WIFI_PASSWORD": cfg["password"],
               "REMOTE_URL": cfg["url"]}
    if cfg["custom_ca"]:
        secrets["CUSTOM_CA"] = cfg["custom_ca"]
    path = PROJECT / "secrets.json"
    path.write_text(json.dumps(secrets), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def remove_secrets():
    for relative in SECRET_OUTPUTS:
        try:
            (PROJECT / relative).unlink()
        except FileNotFoundError:
            pass


def write_version_header(version):
    header = PROJECT / "main" / "version.h"
    original = header.read_text(encoding="utf-8")
    header.write_text(
        "// Auto-generated file - DO NOT EDIT\n"
        "// Generated by tools/build_pixoticker.py\n\n"
        "#pragma once\n\n"
        '#define FIRMWARE_VERSION "%s"\n' % version,
        encoding="utf-8",
    )
    return original


def merge_image(build_dir, output):
    args = json.loads((build_dir / "flasher_args.json").read_text(encoding="utf-8"))
    size_text = args["flash_settings"]["flash_size"]
    if not size_text.endswith("MB"):
        fail("unexpected flash size %r" % size_text)
    image = bytearray(b"\xff" * (int(size_text[:-2]) * 1024 * 1024))
    for offset_text, relative in args["flash_files"].items():
        offset = int(offset_text, 0)
        data = (build_dir / relative).read_bytes()
        if offset + len(data) > len(image):
            fail("%s does not fit in flash at %s" % (relative, offset_text))
        image[offset:offset + len(data)] = data
    output.write_bytes(image)
    return args["flash_settings"], hashlib.sha256(image).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("config", help="JSON config (see pixoticker-build.example.json)")
    parser.add_argument("--output-dir", default=str(ROOT / "dist"),
                        help="where the merged image is written (default: dist/)")
    parser.add_argument("--keep-secrets", action="store_true",
                        help="leave secrets.json and generated files on disk after the build")
    parser.add_argument("--keep-build", action="store_true",
                        help="keep the build directory (contains the credentials in firmware.bin)")
    options = parser.parse_args()

    cfg = load_config(options.config)
    idf = idf_command()

    if not (PROJECT / "CMakeLists.txt").is_file():
        fail("firmware-esp32/ is empty; run: git submodule update --init")
    if not (PROJECT / PATCH_MARKER).is_file():
        fail("firmware-esp32/ is not patched; run: "
             "git -C firmware-esp32 apply ../patches/pixoticker.patch")

    # secrets.cmake is regenerated from secrets.json on every configure, so only
    # a user-authored secrets.json could leak other values into this build.
    if (PROJECT / "secrets.json").exists():
        fail("secrets.json already exists; move it aside so this build uses only your config")

    profiles = list(COMMON_PROFILES)
    if not cfg["station_only"]:
        profiles.append(PORTAL_PROFILE)
    for profile in profiles:
        if not (PROJECT / profile).is_file():
            fail("missing build profile %s" % profile)

    build_dir = PROJECT / ("build_custom_" + cfg["name"])
    sdkconfig = PROJECT / ("sdkconfig.custom_" + cfg["name"])
    output_dir = Path(options.output_dir)
    output = output_dir / ("pixoticker-%s-0x0.bin" % cfg["name"])

    # Fresh configuration so profile defaults always apply (a stale sdkconfig would win).
    shutil.rmtree(build_dir, ignore_errors=True)
    for stale in [sdkconfig, Path(str(sdkconfig) + ".old")]:
        try:
            stale.unlink()
        except FileNotFoundError:
            pass

    print("Mode: %s" % ("station-only (no setup hotspot)" if cfg["station_only"]
                        else "captive portal enabled (TRON-CONFIG)"))
    print("Profiles: %s" % ";".join(profiles))
    print("Version: %s" % cfg["version"])

    write_secrets(cfg)
    original_header = write_version_header(cfg["version"])
    try:
        command = idf + [
            "-B", str(build_dir),
            "-D", "SDKCONFIG=" + str(sdkconfig),
            "-D", "SDKCONFIG_DEFAULTS=" + ";".join(profiles),
            "-D", "PROJECT_VER=" + cfg["version"],
            "build",
        ]
        result = subprocess.run(command, cwd=str(PROJECT))
        if result.returncode != 0:
            fail("idf.py build failed (exit %d)" % result.returncode)
    finally:
        (PROJECT / "main" / "version.h").write_text(original_header, encoding="utf-8")
        if not options.keep_secrets:
            remove_secrets()

    generated = (sdkconfig.read_text(encoding="utf-8") if sdkconfig.is_file() else "")
    ap_enabled = "CONFIG_ENABLE_AP_MODE=y" in generated
    if ap_enabled == cfg["station_only"]:
        fail("generated sdkconfig does not match the requested mode; build output not trusted")

    output_dir.mkdir(parents=True, exist_ok=True)
    settings, digest = merge_image(build_dir, output)
    (output_dir / (output.name + ".sha256")).write_text("%s  %s\n" % (digest, output.name),
                                                        encoding="utf-8")
    if not options.keep_build:
        shutil.rmtree(build_dir, ignore_errors=True)
        for stale in [sdkconfig, Path(str(sdkconfig) + ".old")]:
            try:
                stale.unlink()
            except FileNotFoundError:
                pass

    print()
    print("Image:   %s" % output)
    print("SHA256:  %s" % digest)
    print("Flash:   address 0x0, %s / %s / %s" % (settings["flash_mode"],
                                                 settings["flash_freq"],
                                                 settings["flash_size"]))
    print("         python -m esptool --chip esp32 --port PORT --baud 460800 write-flash "
          "--flash-mode %s --flash-freq %s --flash-size %s 0x0 %s"
          % (settings["flash_mode"], settings["flash_freq"], settings["flash_size"], output.name))
    if cfg["ssid"] or cfg["url"] or cfg["custom_ca"]:
        print("This image contains your Wi-Fi credentials/server URL: do not share it.")
    if cfg["station_only"]:
        print("Station-only: if the credentials are wrong the device cannot be reconfigured "
              "over Wi-Fi; rebuild and reflash over USB.")


if __name__ == "__main__":
    main()
