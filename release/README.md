# Pixoticker Tronbyt firmware

Turns a Pixoticker (original ESP32, 64x32 panel, 4 MB flash) into a [Tronbyt](https://github.com/tronbyt/server) client. Requires your own Tronbyt server on the local network.

## Files

| File | |
| :--- | :--- |
| `pixoticker-tronbyt-public-0x0.bin` | Ready-to-flash image, no credentials baked in. Flash at **0x0**. |
| `source.tar.gz` | Matching source: `tools/build_pixoticker.py` for a personalised build, and the upstream firmware files in `firmware-esp32/` with `patches/pixoticker.patch` already applied. |
| `SHA256SUMS`, `build-provenance.json` | Checksums and build details. |
| `LICENSE`, `LICENSES/` | Apache-2.0 firmware; third-party component licences. |

Image SHA-256: `{{SHA256}}` ({{SIZE}} bytes, version `{{VERSION}}`).

The image is a fresh build, not a cleaned device dump. NVS, coredump and unused flash are erased; it contains no Wi-Fi credentials, server URL, API key or device identity.

## Flash it

Flashing replaces the original Pixoticker firmware and clears any saved settings. Back up first; the tool below can do that.

**USB-serial driver** (needed for either method below). The Pixoticker's USB chip is a CH340:

- **Windows**: if no COM port appears after plugging in, install the [WCH CH341SER driver](https://www.wch-ic.com/downloads/CH341SER_EXE.html) and reconnect.
- **macOS 10.14+**: Apple's built-in driver handles it; do not install WCH's (the two conflict and produce non-working ports). Keep the baud rate at **460800** or lower — Apple's driver is unreliable above that.
- **Linux**: in-kernel (`ch341`), nothing to install. If the port vanishes right after plugging in, remove `brltty`; if access is denied, add your user to the `dialout` (or `uucp`) group and log in again.

**[ESPConnect](https://thelastoutpostworkshop.github.io/ESPConnect/)** (Chrome/Edge/Brave; runs in the browser):

1. Connect the Pixoticker over USB. On macOS, set the baud-rate selector to 460800 first (the default is 921600). Click **Connect** and pick its serial port. If it does not enter the bootloader by itself: hold BOOT, tap RESET, keep holding BOOT while clicking Connect.
2. **Flash Tools → Backup** the full flash and keep the file. This is your way back to the original Pixoticker firmware.
3. **Flash Tools → Flash Firmware**: select `pixoticker-tronbyt-public-0x0.bin` and set the offset to **`0x0`** (not the "app"/0x10000 preset). The image covers the whole chip, so "erase entire flash" is not needed.
4. Reset the board. The **Serial Monitor** tab shows it booting and starting the setup hotspot.

Command-line alternative (esptool v5):

```sh
python -m esptool --chip esp32 --port PORT --baud 460800 write-flash --flash-mode dio --flash-freq 40m --flash-size 4MB 0x0 pixoticker-tronbyt-public-0x0.bin
```

Use `--baud 115200` if the transfer fails. Never flash this file at `0x10000` or push it through an OTA update.

## Set it up

1. Join the open Wi-Fi network **TRON-CONFIG** (it has no internet; stay connected if your phone complains).
2. Open **http://10.10.0.1/** if the setup page does not appear by itself.
3. Enter your **2.4 GHz** Wi-Fi name and password and the image URL from your Tronbyt server (Device → copy the `…/next` URL). Save.
4. The Pixoticker reboots, joins your network and starts showing your apps.

The hotspot is plain HTTP on an open network: do the setup near the device and never forward that page to the internet. It is started at every boot and stays up while the device cannot connect (the device reboots every 10 minutes in that state, which restarts it). About two minutes after a successful Wi-Fi connection it switches off for good; to reach it again later, power-cycle the device.

Brightness is set from the server. Start around 20 % on USB-powered units.

## Build your own image instead (optional)

To compile your Wi-Fi and server URL in, or to disable the setup hotspot entirely (station-only), build from `source.tar.gz`:

1. Install [ESP-IDF v5.5.x](https://docs.espressif.com/projects/esp-idf/en/v5.5/esp32/get-started/) and run its export script.
2. Extract the archive, then in `pixoticker-public-source/`:

```sh
cp pixoticker-build.example.json pixoticker-build.json   # edit the values
python tools/build_pixoticker.py pixoticker-build.json
```

3. Flash `dist/pixoticker-<name>-0x0.bin` at `0x0` as above.

`station_only: true` means no hotspot ever: if the credentials are wrong, the only fix is rebuilding and reflashing over USB. The resulting image contains your credentials, so do not share it. The source README documents every config key.

## What was verified

Built with {{IDF_VERSION}} from the staged copy packed in `source.tar.gz`. `tools/make_release.py` checked the image size, that NVS and coredump are erased, and that the bootloader, partition table and app are present. {{PRIVATE_SCAN}}

**Not verified on hardware:** this exact public image has not been flashed to a Pixoticker. Report problems with the serial-monitor output.

Upstream project: https://github.com/tronbyt/firmware-esp32
