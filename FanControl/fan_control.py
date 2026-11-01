# -*- coding: utf-8 -*-
"""联想风扇控制工具
基于联想 WMI 接口（root\\WMI\\LENOVO_FAN_METHOD）：
  - 全速风扇开关（Fan_Set_FullSpeed）
  - 读取风扇实时转速（Fan_GetCurrentFanSpeed）
  - 读取传感器温度（Fan_GetCurrentSensorTemperature）
需要管理员权限：非管理员启动时自动请求 UAC 提权。
自检模式：fan_control.py --selftest  （提权后运行接口测试并写 selftest.json）
"""
import os
import sys
import json
import ctypes
import threading
import subprocess
import concurrent.futures

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SELFTEST_PATH = os.path.join(BASE_DIR, "selftest.json")


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_elevated(args=None):
    """以管理员权限重新启动自身"""
    params = " ".join(args or [])
    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable,
                                        f'"{os.path.abspath(__file__)}" {params}', None, 1)


def ps(script):
    """执行 PowerShell 脚本（完全隐藏窗口），返回 (stdout, stderr)"""
    out = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
         "-Command", script],
        capture_output=True, text=True, timeout=60,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return out.stdout.strip(), out.stderr.strip()


# ---------------- WMI 接口封装 ----------------

def invoke_fan_method(method, args=""):
    """通过实例对象调用 LENOVO_FAN_METHOD 的方法。
    args 形如 "@{FanID=[byte]0}"。返回方法返回值的 JSON 文本。"""
    script = (
        "$o = Get-CimInstance -Namespace root\\WMI -ClassName LENOVO_FAN_METHOD; "
        "if (-not $o) { 'NO_INSTANCE'; exit }; "
        f"$m = Invoke-CimMethod -InputObject $o -MethodName {method}"
        + (f" -Arguments {args}" if args else "")
        + "; if ($m) { $m | ConvertTo-Json -Compress } else { 'NULL' }"
    )
    out, err = ps(script)
    if out == "NO_INSTANCE":
        raise RuntimeError("未找到 LENOVO_FAN_METHOD 实例")
    if out == "NULL" or not out:
        raise RuntimeError(err or f"调用 {method} 无返回")
    return out


def fan_set_fullspeed(on):
    invoke_fan_method("Fan_Set_FullSpeed", "@{Status=$%s}" % str(on).lower())


def fan_get_fullspeed():
    out = invoke_fan_method("Fan_Get_FullSpeed")
    return ":true" in out.replace(" ", "").lower()


def fan_get_speed(fan_id):
    out = invoke_fan_method("Fan_GetCurrentFanSpeed", "@{FanID=[byte]%d}" % fan_id)
    return int(json.loads(out).get("CurrentFanSpeed"))


def fan_get_temp(sensor_id):
    """返回摄氏温度。联想接口通常返回开尔文×10，做转换；明显异常时返回原始值。"""
    out = invoke_fan_method("Fan_GetCurrentSensorTemperature", "@{SensorID=[byte]%d}" % sensor_id)
    raw = int(json.loads(out).get("CurrentSensorTemperature"))
    celsius = raw / 10 - 273.15
    if -20 <= celsius <= 120:
        return round(celsius, 1)
    return raw  # 单位不明时返回原始值


def read_status():
    """读取全速状态、风扇1/2转速、传感器0温度。任何一项失败记入 errors。
    四路 WMI 查询各起一个 PowerShell，并发执行（串行约 1.7s，并发约 0.5s）。"""
    status = {"fullspeed": None, "fan1": None, "fan2": None, "temp": None, "errors": []}
    jobs = [
        ("fullspeed", "全速状态", fan_get_fullspeed),
        ("fan1", "风扇0", lambda: fan_get_speed(0)),
        ("fan2", "风扇1", lambda: fan_get_speed(1)),
        ("temp", "温度", lambda: fan_get_temp(0)),
    ]
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=len(jobs))
    try:
        futures = [(key, label, pool.submit(fn)) for key, label, fn in jobs]
        for key, label, fut in futures:
            try:
                status[key] = fut.result(timeout=60)
            except Exception as e:
                status["errors"].append(f"{label}: {e}")
    finally:
        pool.shutdown(wait=False)
    return status


# ---------------- 自检模式 ----------------

def selftest():
    result = {"admin": is_admin(), "steps": {}}
    probes = [
        ("get_fullspeed", lambda: fan_get_fullspeed()),
        ("fan1_rpm", lambda: fan_get_speed(0)),
        ("fan2_rpm", lambda: fan_get_speed(1)),
        ("sensor0_temp", lambda: fan_get_temp(0)),
        ("sensor1_temp", lambda: fan_get_temp(1)),
    ]
    for name, fn in probes:
        try:
            result["steps"][name] = fn()
        except Exception as e:
            result["steps"][name] = f"FAIL: {e}"
    with open(SELFTEST_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


def probe_toggle():
    """深度验证：扫描传感器 0-9；关闭全速观察转速下降；再恢复。"""
    import time
    result = {"sensors": {}, "toggle": {}}
    for sid in range(10):
        try:
            result["sensors"][str(sid)] = fan_get_temp(sid)
        except Exception as e:
            result["sensors"][str(sid)] = f"ERR"
    result["toggle"]["before"] = {"fullspeed": fan_get_fullspeed(),
                                  "fan1": fan_get_speed(0), "fan2": fan_get_speed(1)}
    fan_set_fullspeed(False)
    time.sleep(4)
    result["toggle"]["after_off"] = {"fullspeed": fan_get_fullspeed(),
                                     "fan1": fan_get_speed(0), "fan2": fan_get_speed(1)}
    fan_set_fullspeed(True)
    time.sleep(4)
    result["toggle"]["restored"] = {"fullspeed": fan_get_fullspeed(),
                                    "fan1": fan_get_speed(0), "fan2": fan_get_speed(1)}
    with open(os.path.join(BASE_DIR, "probetoggle.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


# ---------------- 图形界面 ----------------

class FanApp:
    def __init__(self, root):
        import tkinter as tk
        from tkinter import ttk
        self.tk = tk
        self.root = root
        root.title("风扇控制")
        root.geometry("420x300")

        ttk.Label(root, text="联想 WMI 风扇接口", font=("Microsoft YaHei UI", 11)).pack(pady=(14, 4))

        self.status_var = tk.StringVar(value="读取中...")
        ttk.Label(root, textvariable=self.status_var, justify="left",
                  font=("Consolas", 11)).pack(pady=6)

        btns = ttk.Frame(root)
        btns.pack(pady=8)
        ttk.Button(btns, text="🔥 全速风扇：开", width=18,
                   command=lambda: self.set_full(True)).pack(side="left", padx=6)
        ttk.Button(btns, text="🌿 全速风扇：关", width=18,
                   command=lambda: self.set_full(False)).pack(side="left", padx=6)

        self.msg = tk.StringVar(value="全速模式适合打游戏/渲染；日常使用建议关闭，噪音更小。")
        ttk.Label(root, textvariable=self.msg, wraplength=380,
                  foreground="#555").pack(pady=6)

        self._busy = False
        self.refresh_loop()

    def _call(self, fn):
        """把结果交回 Tk 主线程（窗口已关闭时忽略）"""
        try:
            self.root.after(0, fn)
        except Exception:
            pass

    def set_full(self, on):
        if self._busy:
            return
        self._busy = True
        self.msg.set("正在设置...")

        def worker():
            try:
                fan_set_fullspeed(on)
                err = None
            except Exception as e:
                err = str(e)
            self._call(lambda: self._set_done(on, err))

        threading.Thread(target=worker, daemon=True).start()

    def _set_done(self, on, err):
        self._busy = False
        if err:
            self.msg.set(f"设置失败：{err}")
        else:
            self.msg.set("已开启全速风扇。" if on else "已关闭全速风扇，恢复自动调速。")
        self.refresh_once()

    def refresh_once(self):
        """后台读状态，界面不再卡顿"""
        if self._busy:
            return
        self._busy = True

        def worker():
            try:
                st, err = read_status(), None
            except Exception as e:
                st, err = None, str(e)
            self._call(lambda: self._apply(st, err))

        threading.Thread(target=worker, daemon=True).start()

    def _apply(self, st, err):
        self._busy = False
        if err:
            self.status_var.set(f"读取失败：{err}")
            return
        lines = []
        if st["fullspeed"] is not None:
            lines.append(f"全速模式：{'开启 🔥' if st['fullspeed'] else '关闭 🌿'}")
        if st["fan1"] is not None:
            lines.append(f"风扇1转速：{st['fan1']} RPM")
        if st["fan2"] is not None:
            lines.append(f"风扇2转速：{st['fan2']} RPM")
        if st["temp"] is not None:
            unit = "°C" if isinstance(st["temp"], float) else " (原始值)"
            lines.append(f"传感器温度：{st['temp']}{unit}")
        for e in st["errors"]:
            lines.append(f"⚠ {e}")
        self.status_var.set("\n".join(lines) if lines else "无法读取状态")

    def refresh_loop(self):
        self.refresh_once()
        try:
            self.root.after(3000, self.refresh_loop)
        except Exception:
            pass


def main():
    if "--probetoggle" in sys.argv:
        if not is_admin():
            relaunch_elevated(["--probetoggle"])
            return
        probe_toggle()
        return
    if "--selftest" in sys.argv:
        if not is_admin():
            relaunch_elevated(["--selftest"])
            return
        selftest()
        return
    if os.environ.get("FAN_NO_GUI"):
        print(json.dumps(read_status(), ensure_ascii=False, indent=2))
        return
    if not is_admin():
        relaunch_elevated()
        return
    import tkinter as tk
    root = tk.Tk()
    FanApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
