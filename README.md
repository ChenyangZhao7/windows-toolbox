# Windows Toolbox

**English** | [中文](README.zh-CN.md)

A small Windows toolbox for personal use: four utilities behind one Tkinter window.

## What it does

| Tab | Purpose | Backing script |
|---|---|---|
| 🧹 Tidy desktop | Sort desktop files by extension, remove folders left empty | `DesktopOrganizer/organize_desktop.py` |
| 💽 Disk checkup | Walk the disk and show where space goes | `DiskCheckup/disk_checkup.py` |
| 📦 Software manager | List installed software, ask DeepSeek what a program is for, launch the official uninstaller | `SoftQuery/soft_query.py` |
| 🌀 Fan control | Lenovo WMI fan interface: full-speed switch and RPM readout | `FanControl/fan_control.py` |

Each script also runs on its own by double-clicking, with `--selftest` and other debug entry points (described at the top of each file).

## Layout

```
Toolbox/toolbox.py            main window; loads the four modules below
DesktopOrganizer/             desktop tidying
DiskCheckup/                  disk space checkup
SoftQuery/                    software manager (optional DeepSeek API)
FanControl/                   Lenovo fan control
```

## Running it

```
pythonw Toolbox\toolbox.py
```

Windows and Python 3.10+ (tkinter is included). Fan control needs administrator rights; without them the tab explains how to elevate.

## Notes and caveats

- **Tidy desktop**: only touches documents, images, video, audio and archives in plain folders on the desktop, sorted by extension.
  It skips dependency folders such as `node_modules`/`venv`/`build`, software and game installs whose first two levels contain exe/dll files,
  and the `png`/`pdf`/`docx`-style folders it creates itself. Running it twice does not shuffle files back and forth.
  Shortcuts (.lnk), hidden files, `desktop.ini` and `Thumbs.db` are never touched.
- **Disk checkup**: the first scan of a large drive (C:, say) takes tens of seconds; the same run does not scan twice.
- **Software manager**: the API key is encrypted with Windows DPAPI in `SoftQuery/config.json` on this machine and never enters the repository.
- **Fan control**: depends on Lenovo's `root\WMI\LENOVO_FAN_METHOD` interface; on other machines the read fails.

## License

MIT
