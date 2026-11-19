# Photobox Regenbogenhausen

- [Abstract](#abstract)
- [What you need](#what-you-need)
- [How to use](#how-to-use)
- [Details](#details)
- [License](#license)

## Abstract

A DIY photo booth for parties, built from a Raspberry Pi, a camera and a
touchscreen. Guests tap the screen, smile through a countdown and see their
photo right away. They can browse a gallery and get their photo onto their
phone by scanning two QR codes: the booth opens its own small Wi-Fi for this,
no internet or app needed. Otherwise photos never leave the booth.

It works at home in your own Wi-Fi and stand-alone anywhere else; a settings
screen shows its status and switches between the two.

## What you need

| Part | Notes |
|---|---|
| Raspberry Pi 4 (2 GB is enough) | with a cooler, it runs warm |
| Raspberry Pi camera | Camera Module 3 recommended (autofocus) |
| HDMI touchscreen | touch via USB; tested at 1920×1200 |
| USB Wi-Fi stick with access-point mode | for guests' phones; tested: Realtek RTL8822BU |
| microSD card or USB SSD | Raspberry Pi OS Lite 64-bit (Debian 13) |
| A laptop | to install and update the booth over SSH |

## How to use

**Set up once:** install Raspberry Pi OS Lite, copy this repository to the
Pi, run `sudo bash deploy/setup-pi.sh` and reboot. From then on the Pi starts
straight into the booth.

**At the party:**

- **Take a photo:** tap the live picture.
- **Photo to a phone:** tap *To phone* on the photo, scan code ① to join the
  Wi-Fi, then save the photo from the page that opens (or scan code ②). Links
  work for 5 minutes.
- **Gallery:** browse and swipe through all photos.
- **Settings (gear):** status of network, connected devices, SSH and
  temperature; switch between *home Wi-Fi* and *standalone* (own Wi-Fi, with a
  QR code for your laptop); restart; turn off. Always turn the booth off here
  before unplugging it.
- **Language:** English or German, one tap.

**Updates:** from the laptop, run `deploy/deploy.sh`.

## Details

Everything else (architecture, every file and folder, configuration, API,
services, development and testing) is described in [CLAUDE.md](CLAUDE.md).
It is written so that an AI assistant, or a curious human, can pick up the
project without reading the code first.

## License

[MIT](LICENSE)
