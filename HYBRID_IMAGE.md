# Pixoticker hybrid firmware image

How and why the working Pixoticker image (`pixoticker-tronbyt-station-only-0x0.bin`) was put together from the original Pixoticker flash dump and the Tronbyt server-built OTA image.

## Terms

This document keeps three firmware sources apart:

| Term | Meaning |
| :--- | :--- |
| **Original Pixoticker firmware** | The vendor firmware the device shipped with, taken from the flash dump `used_flash_0x0.bin`. Its parts are prefixed "Pixoticker", e.g. Pixoticker bootloader, Pixoticker NVS. |
| **Tronbyt OTA image** | The app-only image the Tronbyt server built for this device, `bitmex-ticker-firmware.bin`. Used unmodified. |
| **Upstream Tronbyt** | The `tronbyt/firmware-esp32` source code that the Tronbyt OTA image is built from, and that we patched and rebuilt. |

Source paths such as `main/wifi.c` or `boards/max_app_4mb.csv` are relative to the upstream tree, `firmware-esp32/` in this repository. The Pixoticker fixes described below are carried in `patches/pixoticker.patch`.

## Inputs

| Image | What it is | SHA-256 (prefix) |
| :--- | :--- | :--- |
| `used_flash_0x0.bin` | Original Pixoticker firmware: full 4 MiB dump with bootloader, partition table, NVS and the Pixoticker ticker app (Arduino core, ESP-IDF v5.1.4, build `d7f4a33`). | `a5ff2c06` |
| `bitmex-ticker-firmware.bin` | Tronbyt OTA image: **app-only**, built for this device by the Tronbyt server (`v1.7.2`, ESP-IDF v5.5.6), 1,311,744 bytes. | `c641486a` |
| `pixoticker-tronbyt-station-only-0x0.bin` | Final hybrid: full 4 MiB image, flashed at `0x0`. | `c8a14ae2` |

## Why the Tronbyt OTA image

The self-hosted Tronbyt server can generate either a full-flash ("merged") image or an OTA-only app image. With the Pixoticker device type selected, only the OTA-only option works. Requesting the full image produces no file, and the server logs:

```text
ERR Failed to generate firmware device_type=pixoticker version=v1.7.2 error="merged firmware not available for device type Pixoticker"
```

So the only server-built Tronbyt firmware for this board was an app-only image, with no bootloader, partition table or settings. That is why it had to be combined with a boot chain from elsewhere.

## Problem

Flashed to the device, the Tronbyt OTA image booted but never showed server content, and it looked like a Wi-Fi failure. The original Pixoticker firmware joined the same network without trouble. The Tronbyt setup portal also returned `Server error` on save.

An app-only image cannot be flashed by itself as a complete device image. You also can't splice the Pixoticker Wi-Fi driver into it: the two apps use different ESP-IDF versions and different linked layouts. The fix had to happen at the partition and settings level, and then in upstream Tronbyt source.

## Stage 1: diagnostic hybrid (byte-level merge)

| Region | Offset | Source | Why |
| :--- | :--- | :--- | :--- |
| Bootloader | `0x1000` | Pixoticker bootloader, unchanged | Boot chain already known to work on this exact board and flash chip. |
| Partition table | `0x8000` | Pixoticker partition table, unchanged | Its `app0` slot (1.9 MB) at `0x10000` holds the 1.3 MB Tronbyt app. |
| NVS | `0x9000` | **Freshly generated** (Tronbyt `wifi_config` namespace only) | Wi-Fi network, server URL and API key from the Tronbyt build configuration. `wifi_ps=0`, `ap_mode=1`. |
| otadata | `0xe000` | Erased | Forces the bootloader to run `0x10000`, so no stale OTA selection can redirect it. |
| App | `0x10000` | Tronbyt OTA image, byte-for-byte | The firmware under test. |
| Rest (`app1`, coredump) | — | Erased | No leftover Pixoticker code or crash data. |

Deliberately **not** copied from the Pixoticker NVS: `nvs.net80211` (Pixoticker Wi-Fi driver state, including its open setup-AP config), `phy` RF calibration from the older IDF, and the Pixoticker ticker app's `config` blob. Tronbyt recalibrates RF on first boot.

What it showed: the device got an IP about 11 s after reset, so **Wi-Fi was never the actual fault**. The real failure came right after:

```text
main: Free PSRAM: 0
remote: couldn't allocate HTTP receive buffer
main: No WiFi or Failed to get webp with code 0
```

## Stage 2: final image (patched upstream Tronbyt + Pixoticker-derived settings)

Upstream Tronbyt was patched and rebuilt for this board with the same ESP-IDF commit as the Tronbyt OTA image (`3ea97e75`), then merged into a full image. No Pixoticker binaries remain in it:

| Region | Source |
| :--- | :--- |
| Bootloader | Built with the patched upstream Tronbyt app (IDF v5.5.6). |
| Partition table | Upstream Tronbyt `boards/max_app_4mb.csv`: same `nvs`/`otadata`/`coredump` offsets as the Pixoticker table, with its `app0`+`app1` merged into one 3,968 KB factory app. |
| NVS | Tronbyt `wifi_config` only: Wi-Fi network, `image_url`/`api_key`, `wifi_ps=0`, `ap_mode=0`, `brightness=20`. |
| App | Patched upstream Tronbyt app with the Pixoticker fixes below. |

### Taken from the original Pixoticker firmware

- **Wi-Fi security policy** from the Pixoticker NVS: `sta.minauth=3` (WPA2 minimum), `sta.pmf_e=1` / `sta.pmf_r=0` (PMF capable, not required), `sta.sae_h2e=2` (both SAE PWE methods). The Tronbyt OTA image left these zeroed and showed hunting-and-pecking SAE and SA-query disconnects. Now set explicitly in `main/wifi.c` under `CONFIG_BOARD_PIXOTICKER`.
- **Station-only operation**: once configured, the Pixoticker firmware runs as `opmode=1` (STA only). Mirrored with `CONFIG_ENABLE_AP_MODE=n` plus `ap_mode=0` in the Tronbyt NVS.
- **Flash geometry**: 4 MB, DIO, and the Pixoticker offsets for NVS (`0x9000`, 20 KB), otadata and coredump.
- **Brightness hint**: the Pixoticker firmware ran at 50 on its 20–200 scale. Tronbyt was booting at a saved 100 %, so the image ships with a 20 % startup value. The Tronbyt server overrides it after the first fetch.

### Taken from the Tronbyt OTA image

- **The firmware itself**: Tronbyt client logic, WebP decode, HUB75 driver, WebSocket/HTTP fetch, and the IDF baseline. Stage 1 used the Tronbyt OTA image byte-for-byte; Stage 2 rebuilt from upstream Tronbyt source (`828619b`) with the same IDF commit.
- **Device identity on the server**: the `/next` image URL and API key for this device.
- **Settings schema**: the `wifi_config` NVS namespace and keys that Tronbyt reads ahead of its compiled-in defaults.

## Why this works where the Tronbyt OTA image does not

1. **No PSRAM on this board.** Upstream Tronbyt allocated these buffers with `MALLOC_CAP_SPIRAM` only: the HTTP receive buffer and its growth (`remote.c`), WebSocket image assembly (`main.c`), and the portal save and upload buffers (`ap.c`). On a board with no PSRAM every fetch failed, and the log said "No WiFi". The portal save failed with HTTP 500, which is the `Server error` page. `main/buffer_memory.h` (added by the patch) now selects internal 8-bit RAM when `CONFIG_SPIRAM` is off. The image buffer starts at 10,000 bytes and is capped at 60,000.
2. **A clean, consistent flash.** Settings are fresh and only in Tronbyt's namespace, otadata is erased, and one full `0x0` image means no mismatch between the partition table and the app. This avoids failures caused by settings left over from earlier flashes, because Tronbyt's NVS values override its compiled-in defaults.
3. **Pixoticker-equivalent Wi-Fi negotiation** without changing the router's security settings. This is a candidate fix, not a proven one: later boots showed no SA-query disconnects.

Verified on the device: settings survived a controlled reboot, the first server image appeared about 66 s after reset, and 9 of 10 queued images loaded in 3½ minutes. One initial HTTP timeout recovered by itself. The signal was about −80 dBm.

## Usability and security gains

- **Zero-touch boot**: the device joins home Wi-Fi straight away and everything else is managed from the Tronbyt server. No portal step, and no confusing second `10.10.0.x` network or DHCP server.
- **No open Tronbyt setup AP.** The Tronbyt portal is plain HTTP on an open network. Its `/save` lets anyone in radio range change the Wi-Fi settings and repoint the server URL, and its `/update` handler has no authentication. Station-only builds never start it.
- **WPA3/PMF preserved**: no WPA2 downgrade on the router was needed.
- **Less on the device**: the Pixoticker ticker app and its external data endpoints are gone, and the Pixoticker driver, AP and calibration records were not carried over. The device only talks to the local Tronbyt server, plus NTP.
- **USB-friendly startup** at low brightness.

## Original Pixoticker firmware: security notes

Review depth: the Pixoticker parts were checked for **integrity**, not security. That covered partition table MD5, bootloader and app image checksums and SHA-256 (`esptool image-info`), and NVS page and entry CRCs. The Pixoticker app was also scanned for text strings. Nothing was disassembled or reviewed at code level.

Pixoticker code exposure: the Stage 1 diagnostic image ran the Pixoticker bootloader and partition table. The final image runs no Pixoticker code; from the Pixoticker firmware it uses only setting values, offsets and the brightness reference.

### Confirmed from the dump

- **Open Pixoticker setup hotspot**: stored `ap.authmode=0` (no password) on this configured device.
- **Readable flash**: the Pixoticker NVS and app read as plain data; on this configured device, `nvs.net80211` holds the Wi-Fi password in clear. This shows flash encryption was not in effect for these regions. A dump cannot show the chip's eFuse state.

### Unverified: review targets, not findings

Strings only show that this code or text is present, not how it behaves.

- **Pixoticker portal firmware upload**: WiFiManager strings for `http://192.168.4.1` and an "Upload new firmware" form posting to `/update`. Whether that handler is enabled and what authentication it uses is unknown.
- **Pixoticker self-update from GitHub**: strings reference `api.github.com/repos/…/releases/latest`, `raw.githubusercontent.com`, a "rollout manifest" and "bin URL found". Which repository and asset it selects, which TLS validation is enforced, and whether images are signature-checked are all unknown. One embedded PEM certificate was found; what it is used for was not established.
- **Pixoticker bootloader trust**: valid checksums show the bootloader is intact, not that it is safe. No secure-boot strings were found, which is not conclusive.
- **Pixoticker build provenance**: the `-dirty` suffix on build `d7f4a33` and IDF `v5.1.4-497-gdc859c1e67` means the tree had uncommitted changes. Whether matching public source exists was not checked.

### Effect on the hybrid

None of the items above carry into the final image: no Pixoticker app, Pixoticker self-update, Pixoticker portal or Pixoticker NVS records. One limitation remains: upstream Tronbyt does not enable flash encryption or secure boot either (`CONFIG_SECURE_BOOT` and `CONFIG_SECURE_FLASH_ENC_ENABLED` are unset), so the Wi-Fi password and API key are readable over USB. Flash encryption would fix that, but it burns eFuses permanently and complicates reflashing.

## Trade-offs

- **Wrong credentials = USB reflash.** Station-only builds such as this image have no portal to fall back on.
- **No over-the-air updates.** With a single factory app there is no OTA slot, so `esp_ota_get_next_update_partition()` returns NULL. Tronbyt server-pushed `ota_url` updates and the Tronbyt portal `/update` cannot install anything; updates mean reflashing over USB.
- **Contains secrets.** Both the NVS and the app hold the Wi-Fi password and server API key. Never share this image or a dump of the device; use the credential-free release build (`tools/make_release.py`) instead.
- **Unproven causes**: the Wi-Fi policy and brightness/power changes coincided with stable operation but were not isolated as causes. Startup is still about a minute at weak signal.
