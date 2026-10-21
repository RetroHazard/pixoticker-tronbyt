# Pixoticker Tronbyt Firmware

Tronbyt client firmware for the Pixoticker: an original ESP32 (no PSRAM, 4 MB flash) driving a 64x32 HUB75 panel. It fetches WebP images from a [Tronbyt server][server] over HTTP or WebSocket and displays them. Built from unmodified [tronbyt/firmware-esp32][upstream] (a git submodule) plus a small patch with Pixoticker-specific memory, Wi-Fi and provisioning fixes. [HYBRID_IMAGE.md](HYBRID_IMAGE.md) explains how and why.

⚠️ Flashing this firmware replaces the original Pixoticker firmware and voids any warranty. No support is implied.

## Ready-made image

If you just want to run it, flash the credential-free release (`pixoticker-tronbyt-public-0x0.bin`, from this repository's Releases) and configure Wi-Fi through the setup hotspot. See [Flashing](#flashing) and [Setup hotspot](#setup-hotspot).

## Repository layout

| Path | Contents |
| :--- | :--- |
| `firmware-esp32/` | Upstream Tronbyt firmware, git submodule pinned to a tested commit. Not modified in git. |
| `patches/pixoticker.patch` | All Pixoticker changes to upstream: internal-RAM buffers on boards without PSRAM, Pixoticker Wi-Fi security policy, station-only default, portal colour-swap preservation, credential-free portal profile. |
| `tools/build_pixoticker.py` | Builds a personalised full-flash image from one config file. |
| `tools/make_release.py` | Builds the credential-free release bundle. |
| `release/README.md` | Template for the release bundle's README. |
| `pixoticker-build.example.json` | Example config for `tools/build_pixoticker.py`. |
| `HYBRID_IMAGE.md` | How the Pixoticker image was derived, and why it works where the server-built Tronbyt image did not. |

## Building

Prerequisites: [ESP-IDF v5.5.x][idf] installed, with its export script sourced so `IDF_PATH` is set.

```bash
git clone --recurse-submodules <this repository> pixoticker-tronbyt
cd pixoticker-tronbyt
git -C firmware-esp32 apply ../patches/pixoticker.patch
```

Already cloned without submodules: `git submodule update --init` first. Apply the patch once; the build tools refuse to run on an unpatched tree. The submodule is configured with `ignore = dirty`, so the patched files and build output inside it do not show up in this repository's `git status`. To return it to pristine upstream: `git -C firmware-esp32 checkout . && git -C firmware-esp32 clean -fdx`.

### Personalised image (recommended)

One config file produces a full-flash image with your network and server compiled in:

```bash
cp pixoticker-build.example.json pixoticker-build.json   # edit the values
python tools/build_pixoticker.py pixoticker-build.json
# -> dist/pixoticker-<name>-0x0.bin (+ .sha256)
```

| Key | Meaning |
| :--- | :--- |
| `name` | Label for the build and output file (`[A-Za-z0-9._-]`). |
| `wifi_ssid` / `wifi_password` | 2.4 GHz network, ≤32 / ≤64 bytes. Empty password = open network. |
| `remote_url` | Your server's image URL for this device (`http(s)://…`, ≤128 bytes). |
| `station_only` | `true`: never start the setup hotspot. `false`: start it at every boot (see [Setup hotspot](#setup-hotspot)). |
| `custom_ca` | Optional PEM for a private HTTPS CA. |
| `version` | Optional boot-screen label; defaults to `pixoticker-<name>`. |

The script writes `secrets.json` into `firmware-esp32/` only for the duration of the build, uses a fresh `sdkconfig.custom_<name>` and `build_custom_<name>` there so the Pixoticker defaults always apply, verifies the generated config matches the requested mode, merges bootloader + partition table + otadata + app into a 4 MB image, then deletes `secrets.json`, `secrets.cmake`, the generated CA file and the build directory (`--keep-secrets` / `--keep-build` retain them).

`station_only: true` requires an SSID. With wrong credentials such a device can only be fixed by reflashing over USB. The output image contains your credentials; do not share it.

### Credential-free release (for sharing)

```bash
python tools/make_release.py ../pixoticker-tronbyt-public [--deny-strings my-private-strings.txt]
# -> ../pixoticker-tronbyt-public/ and ../pixoticker-tronbyt-public.zip
```

Run it after at least one `tools/build_pixoticker.py` build, which makes ESP-IDF download `managed_components/` and write `dependencies.lock` (both are shipped). The script stages an allow-listed copy of the source (this repository's docs, patch and build tool plus the patched `firmware-esp32/` files a Pixoticker build needs, listed in `ROOT_ALLOW` and `PROJECT_ALLOW`), packs it as `source.tar.gz` with the patch already applied, builds the firmware from that staged copy with the setup hotspot enabled and no credentials (the placeholders in `secrets_place.json` are never saved), and writes the image, licences, `release/README.md` (filled in with the image hash), `build-provenance.json`, `SHA256SUMS` and a zip. It aborts if any string from `--deny-strings` (one per line), or any value from a `firmware-esp32/secrets.json`, appears in any output or inside the source archive. The release README states how many private strings were checked, or that none were supplied; pass `--deny-strings` with your Wi-Fi, server and device identifiers for any release you publish. To ship a new file, add it to an allow list.

Never distribute a device flash dump or a personalised `firmware.bin`: credentials live in the app binary as well as in NVS.

### Plain build

```bash
cd firmware-esp32
rm -f sdkconfig   # an existing sdkconfig overrides the defaults below
idf.py -D SDKCONFIG_DEFAULTS="sdkconfig.defaults;sdkconfig.defaults.pixoticker" build
idf.py flash monitor
```

With a `firmware-esp32/secrets.json` present (see `secrets.json.example` there) its values are compiled in as defaults, exactly as the personalised build does.

### Updating upstream

```bash
git -C firmware-esp32 checkout . && git -C firmware-esp32 clean -fdx
git -C firmware-esp32 fetch && git -C firmware-esp32 checkout <new commit>
git -C firmware-esp32 apply ../patches/pixoticker.patch   # resolve and regenerate the patch if this fails
git add firmware-esp32 patches
```

## Flashing

Always flash the merged image at address **0x0** (DIO, 40 MHz, 4 MB). It replaces everything, including saved Wi-Fi/server settings.

**USB-serial driver** (either method). The Pixoticker's USB bridge is a CH340:

- **Windows**: install the [WCH CH341SER driver](https://www.wch-ic.com/downloads/CH341SER_EXE.html) if no COM port appears.
- **macOS 10.14+**: Apple's built-in driver; do not install WCH's on top (conflicting, non-working ports). Stay at ≤460800 baud.
- **Linux**: in-kernel `ch341`. Remove `brltty` if the port disappears on plug-in; join `dialout`/`uucp` if access is denied.

**Browser (recommended): [ESPConnect](https://thelastoutpostworkshop.github.io/ESPConnect/)** — Chromium-based browser.

1. Connect the Pixoticker over USB (macOS: set the baud selector to 460800 first; default is 921600) and click **Connect**. If it does not enter the bootloader on its own: hold BOOT, tap RESET, keep holding BOOT while clicking Connect.
2. Optional but worthwhile: **Flash Tools → Backup** the whole flash first so the previous firmware can be restored.
3. **Flash Tools → Flash Firmware**: choose the `.bin`, set the offset to `0x0` (not the "app"/0x10000 preset; the full image needs no chip erase), and flash.
4. Reset the board. The **Serial Monitor** tab shows boot and Wi-Fi progress.

**CLI:** esptool v5

```bash
python -m esptool --chip esp32 --port PORT --baud 460800 write-flash \
  --flash-mode dio --flash-freq 40m --flash-size 4MB 0x0 pixoticker-<name>-0x0.bin
```

Use `--baud 115200` if the transfer fails. Do not flash a full image at `0x10000` or push it to an OTA endpoint.

## Setup hotspot

When the hotspot is enabled (credential-free image, or `station_only: false`) the device starts the open **TRON-CONFIG** network at every boot. Join it, open **http://10.10.0.1/** (the captive portal usually opens on its own), enter the 2.4 GHz SSID/password and the server's image URL, and save. The device reboots and joins your network. The portal stays up while the device cannot connect (it reboots every 10 minutes in that state, restarting the AP) and shuts down about two minutes after a successful connection; it is not re-enabled afterwards until the next power-cycle.

The portal is plain HTTP on an open network: configure it nearby and never expose it beyond the device. Saves from the portal keep the Pixoticker's stored colour-swap setting, which the form does not show for this board.

Station-only builds (`CONFIG_ENABLE_AP_MODE=n`, the Pixoticker default) never start the hotspot or a DHCP server. The saved `wifi_config/ap_mode` NVS value overrides the build default, so keep it `0` on those devices.

## Pixoticker notes

- **Memory.** PSRAM is disabled; HTTP receive, WebSocket assembly and portal/upload buffers live in internal byte-addressable RAM. The image buffer starts at 10,000 bytes and is capped at 60,000. `couldn't allocate HTTP receive buffer` is an allocation failure, not a Wi-Fi failure; check for the preceding `Got IP address`.
- **Wi-Fi.** Power saving is off. WPA2 minimum, PMF capable but not required, both WPA3-SAE derivation methods allowed; this does not force WPA2 on a WPA3 network.
- **Brightness.** 20 % → PWM 46/255, 100 % → 230/255. Start low on USB-powered units. The value received from the server is persisted and applied from the next boot, including the boot animation; server night/dim settings override it.
- **Flash layout.** `firmware-esp32/boards/max_app_4mb.csv`: nvs 0x9000, otadata 0xe000, single factory app at 0x10000 (3968 KB), coredump 0x3f0000. There is no OTA slot, so server-pushed updates and the portal's firmware upload cannot install anything; update by reflashing over USB.

## Runtime settings (NVS, namespace `wifi_config`)

Set from the server over WebSocket, or as build defaults via `idf.py menuconfig`.

| Key | Meaning |
| :--- | :--- |
| `hostname` | Network hostname. Defaults to `tronbyt-<mac>`. |
| `syslog_addr` | RFC 5424 syslog target as `host:port`. |
| `sntp_server` | NTP server; defaults to DHCP-provided or `pool.ntp.org`. |
| `swap_colors` | 0/1 red/blue swap. Pixoticker default: 1. |
| `color_order` | Channel remap applied after the swap. Default `RGB`. |
| `ap_mode` | 0/1 setup hotspot. |
| `wifi_ps` | Wi-Fi power save: 0 none, 1 min, 2 max. |
| `prefer_ipv6` | 0/1. |
| `brightness` | Last value received from the server. |

## Troubleshooting

- **`ESP_ERR_OTA_VALIDATE_FAILED` / checksum errors**: the partition table on the device does not match this firmware (usually from flashing only `firmware.bin`). Reflash the merged image at 0x0; erase the whole chip first if in doubt.
- **Device never joins Wi-Fi on a station-only image**: credentials are compiled in; rebuild with the correct values and reflash. There is no portal to fall back to.
- **Colours wrong**: set `color_order` from the server or the portal; leave `swap_colors` at 1 for the Pixoticker panel.

[upstream]: https://github.com/tronbyt/firmware-esp32
[server]: https://github.com/tronbyt/server
[idf]: https://docs.espressif.com/projects/esp-idf/en/v5.5/esp32/get-started/index.html
