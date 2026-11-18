# 系统工具箱 (Windows Toolbox)

[English](README.md) | **中文**

Windows 上自用的一个小工具箱，整合了四个小工具，用一个 Tkinter 窗口管理。

## 功能

| 页签 | 作用 | 后端脚本 |
|---|---|---|
| 🧹 整理桌面 | 按后缀归类桌面文件，删掉被抽空的文件夹 | `DesktopOrganizer/organize_desktop.py` |
| 💽 磁盘体检 | 逐层查看磁盘空间分布 | `DiskCheckup/disk_checkup.py` |
| 📦 软件管家 | 列出已安装软件，可用 DeepSeek 查询用途、调用官方卸载程序 | `SoftQuery/soft_query.py` |
| 🌀 风扇控制 | 联想 WMI 风扇接口：全速开关 + 转速读取 | `FanControl/fan_control.py` |

每个脚本也能单独双击运行，带 `--selftest` 等调试入口（见各文件头部说明）。

## 目录结构

```
Toolbox/toolbox.py            主窗口，动态加载下面四个模块
DesktopOrganizer/             桌面整理
DiskCheckup/                  磁盘体检
SoftQuery/                    软件管家（可选 DeepSeek API）
FanControl/                   联想风扇控制
```

## 运行

```
pythonw Toolbox\toolbox.py
```

要求 Windows + Python 3.10 以上（自带 tkinter）。风扇控制需要管理员权限，非管理员时页面会提示提权。

## 说明与注意事项

- **整理桌面**：只处理桌面下「普通」文件夹里的文档/图片/视频/音频/压缩包，按后缀归类。
  会跳过 `node_modules`/`venv`/`build` 等依赖目录、前两层含 exe/dll 的软件和游戏安装目录，
  以及它自己生成的 `png`/`pdf`/`docx` 之类的归类文件夹。重复运行不会把文件来回搬。
  始终不动快捷方式（.lnk）、隐藏文件和 `desktop.ini`/`Thumbs.db`。
- **磁盘体检**：首次扫描大盘（如 C:）需要几十秒，同一次运行里不会重复扫描。
- **软件管家**：API Key 用 Windows DPAPI 加密保存在本机 `SoftQuery/config.json`，不会进版本库。
- **风扇控制**：依赖联想 `root\WMI\LENOVO_FAN_METHOD` 接口，非联想机型会读取失败。

## License

MIT
