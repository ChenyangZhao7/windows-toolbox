# -*- coding: utf-8 -*-
"""软件管家
列出本机已安装的软件，选中后可调用 DeepSeek API 查询软件用途和卸载建议。
API Key 仅保存在本机 config.json，由用户自行填写。
"""
import os
import re
import json
import base64
import ctypes
import threading
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"

GB = 1024 ** 3


# ---------------- 读取已安装软件 ----------------

def read_uninstall_key(hive, subpath, view=0):
    """从注册表卸载列表读取软件信息。view=0 默认视图，view=1 强制64位，view=2 强制32位"""
    apps = []
    try:
        if view:
            # KEY_WOW64_64KEY / KEY_WOW64_32KEY
            flag = 0x0100 if view == 1 else 0x0200
            import winreg
            key = winreg.OpenKey(hive, subpath, 0, winreg.KEY_READ | flag)
        else:
            import winreg
            key = winreg.OpenKey(hive, subpath)
    except OSError:
        return apps
    import winreg
    i = 0
    while True:
        try:
            subname = winreg.EnumKey(key, i)
            i += 1
        except OSError:
            break
        try:
            sub = winreg.OpenKey(key, subname)
            def get(name):
                try:
                    v, _ = winreg.QueryValueEx(sub, name)
                    return str(v)
                except OSError:
                    return ""
            name = get("DisplayName").strip()
            if not name:
                continue
            size_kb = get("EstimatedSize")
            try:
                size = int(size_kb) * 1024
            except ValueError:
                size = 0
            apps.append({
                "name": name,
                "publisher": get("Publisher").strip(),
                "version": get("DisplayVersion").strip(),
                "size": size,
                "date": get("InstallDate").strip(),
                "location": get("InstallLocation").strip(),
                "uninstall": get("UninstallString").strip(),
                "source": "注册表",
            })
            sub.Close()
        except OSError:
            pass
    key.Close()
    return apps


def list_installed():
    """汇总注册表（64位+32位+当前用户）和应用商店应用"""
    import winreg
    paths = [
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall", 1),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Uninstall", 2),
        (winreg.HKEY_LOCAL_MACHINE, r"Software\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall", 0),
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Uninstall", 0),
    ]
    apps, seen = [], set()
    seen_names = set()
    for hive, path, view in paths:
        for a in read_uninstall_key(hive, path, view):
            k = (a["name"].lower(), a["version"])
            if k in seen:
                continue
            seen.add(k)
            seen_names.add(a["name"].lower())
            apps.append(a)
    # 应用商店应用（结果缓存 24 小时，避免每次打开都跑 30~60 秒的 PowerShell）
    try:
        import subprocess, time
        cache_path = os.path.join(BASE_DIR, "appx_cache.json")
        cache = None
        if os.path.exists(cache_path):
            try:
                c = json.load(open(cache_path, encoding="utf-8"))
                if time.time() - c.get("time", 0) < 86400:
                    cache = c["apps"]
            except Exception:
                pass
        if cache is not None:
            data = cache
        else:
            out = subprocess.run(
                ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command",
                 "Get-AppxPackage | Select-Object Name,Version,InstallLocation | ConvertTo-Json -Compress"],
                capture_output=True, text=True, timeout=60,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            data = json.loads(out.stdout) if out.stdout.strip() else []
            if isinstance(data, dict):
                data = [data]
            try:
                json.dump({"time": time.time(), "apps": data},
                          open(cache_path, "w", encoding="utf-8"), ensure_ascii=False)
            except Exception:
                pass
        for d in data:
            name = d.get("Name", "")
            if not name or name.lower() in seen_names:
                continue
            seen_names.add(name.lower())
            apps.append({
                "name": name, "publisher": "Microsoft Store",
                "version": d.get("Version", ""), "size": 0,
                "date": "", "location": d.get("InstallLocation", ""),
                "uninstall": "", "source": "应用商店",
            })
    except Exception:
        pass
    apps.sort(key=lambda a: -(a["size"]))
    return apps


# ---------------- 配置：API Key 用 Windows DPAPI 加密保存 ----------------
# 加密后的密文只有当前 Windows 账户能解开，别人复制走 config.json 也读不出明文。

class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32),
                ("pbData", ctypes.POINTER(ctypes.c_char))]


CRYPTPROTECT_UI_FORBIDDEN = 0x1


def _blob(data: bytes):
    """构造 DATA_BLOB，并返回 buffer 引用防止被回收"""
    buf = ctypes.create_string_buffer(data, len(data))
    return _DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), buf


def _dpapi_protect(text: str) -> str:
    if not text:
        return ""
    data_in, _keep = _blob(text.encode("utf-8"))
    data_out = _DATA_BLOB()
    if not ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(data_in), "soft_query api key", None, None, None,
            CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(data_out)):
        raise OSError("CryptProtectData 失败")
    try:
        raw = ctypes.string_at(data_out.pbData, data_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(data_out.pbData)
    return base64.b64encode(raw).decode("ascii")


def _dpapi_unprotect(token: str) -> str:
    raw = base64.b64decode(token.encode("ascii"))
    data_in, _keep = _blob(raw)
    data_out = _DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(data_in), None, None, None, None,
            CRYPTPROTECT_UI_FORBIDDEN, ctypes.byref(data_out)):
        raise OSError("CryptUnprotectData 失败")
    try:
        plain = ctypes.string_at(data_out.pbData, data_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(data_out.pbData)
    return plain.decode("utf-8")


def load_config():
    if os.path.exists(CONFIG_PATH):
        try:
            return json.load(open(CONFIG_PATH, encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def get_api_key(cfg=None):
    """读取 API Key；遇到旧版明文配置会自动迁移成密文。"""
    cfg = load_config() if cfg is None else cfg
    enc = cfg.get("api_key_enc")
    if enc:
        try:
            return _dpapi_unprotect(enc)
        except Exception:
            return ""
    legacy = cfg.get("api_key", "")
    if not legacy:
        return ""
    try:
        cfg.pop("api_key", None)
        cfg["api_key_enc"] = _dpapi_protect(legacy)
        save_config(cfg)
    except Exception:
        pass  # 加密失败也不影响本次使用
    return legacy


def set_api_key(key):
    """保存 API Key（DPAPI 加密）。"""
    cfg = load_config()
    cfg.pop("api_key", None)
    cfg["api_key_enc"] = _dpapi_protect(key.strip())
    save_config(cfg)


def ask_deepseek(api_key, app_info):
    """查询软件用途与卸载建议，返回答案文本"""
    prompt = (
        f"软件名称：{app_info['name']}\n"
        f"发布者：{app_info.get('publisher') or '未知'}\n"
        f"版本：{app_info.get('version') or '未知'}\n"
        f"请用中文简明回答（总共不超过5句话）：\n"
        f"1. 这个软件是做什么的；\n"
        f"2. 是否系统/驱动必需组件；\n"
        f"3. 普通用户能否安全卸载，卸载后有什么影响。"
    )
    body = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": "你是软件管家助手，回答准确、简洁、务实。"},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 400,
        "temperature": 0.3,
    }
    req = urllib.request.Request(
        DEEPSEEK_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"].strip()


def run_uninstall(app_info):
    """执行卸载。注册表软件走官方 UninstallString；应用商店应用走 Remove-AppxPackage。"""
    import subprocess
    if app_info["source"] == "应用商店":
        pkg = app_info["name"].replace("'", "''")
        out = subprocess.run(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command",
             f"Get-AppxPackage -Name '{pkg}' | Remove-AppxPackage"],
            capture_output=True, text=True, timeout=300,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if out.returncode != 0:
            raise RuntimeError(out.stderr.strip() or "Remove-AppxPackage 执行失败")
        return

    cmd = app_info["uninstall"]
    if not cmd:
        raise RuntimeError("该软件没有注册卸载程序，请手动删除其安装目录。")
    # msiexec 的卸载串有时是 /I（安装），改成 /X（卸载）；
    # 只替换独立的 /I 参数，避免误伤路径里带 "/i" 的字符串
    if "msiexec" in cmd.lower():
        cmd = re.sub(r"(?i)(?<!\S)/i(?=\s|\{|$)", "/x", cmd)
    proc = subprocess.run(cmd, shell=True, timeout=1800)
    if proc.returncode not in (0, 3010):  # 3010 = 需要重启
        raise RuntimeError(f"卸载程序返回码 {proc.returncode}（可能已取消或不支持静默卸载）")


# ---------------- 图形界面 ----------------

def fmt_size(n):
    if n >= GB:
        return f"{n / GB:.2f} GB"
    if n >= 1024 ** 2:
        return f"{n / 1024 ** 2:.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.1f} KB"
    return "" if n == 0 else f"{n} B"


class SoftQueryApp:
    def __init__(self, root):
        import tkinter as tk
        from tkinter import ttk
        self.tk = tk
        self.root = root
        root.title("软件管家")
        root.geometry("860x560")

        top = ttk.Frame(root)
        top.pack(fill="x", padx=8, pady=6)
        ttk.Button(top, text="刷新列表", command=self.refresh).pack(side="left")
        ttk.Button(top, text="设置 DeepSeek API Key", command=self.set_key).pack(side="left", padx=8)
        self.search_var = tk.StringVar()
        sv = ttk.Entry(top, textvariable=self.search_var, width=30)
        sv.pack(side="right")
        sv.bind("<KeyRelease>", lambda e: self.filter_list())
        ttk.Label(top, text="搜索：").pack(side="right")

        cols = ("publisher", "version", "size", "date", "source")
        self.tree = ttk.Treeview(root, columns=cols, displaycolumns=cols)
        self.tree.heading("#0", text="软件名称", anchor="w")
        self.tree.heading("publisher", text="发布者", anchor="w")
        self.tree.heading("version", text="版本", anchor="w")
        self.tree.heading("size", text="大小", anchor="e")
        self.tree.heading("date", text="安装日期", anchor="w")
        self.tree.heading("source", text="来源", anchor="w")
        self.tree.column("#0", width=260)
        self.tree.column("publisher", width=180)
        self.tree.column("version", width=90)
        self.tree.column("size", width=80, anchor="e")
        self.tree.column("date", width=90)
        self.tree.column("source", width=70)
        self.tree.pack(fill="both", expand=True, padx=8)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

        mid = ttk.Frame(root)
        mid.pack(fill="x", padx=8, pady=4)
        self.sel_var = tk.StringVar(value="选中一个软件，点下方按钮查询它的用途")
        ttk.Label(mid, textvariable=self.sel_var).pack(side="left")
        self.ask_btn = ttk.Button(mid, text="用 DeepSeek 查询功能", command=self.ask, state="disabled")
        self.ask_btn.pack(side="right")
        self.uninstall_btn = ttk.Button(mid, text="卸载此软件", command=self.uninstall, state="disabled")
        self.uninstall_btn.pack(side="right", padx=8)

        self.answer = tk.Text(root, height=8, wrap="word", font=("Microsoft YaHei UI", 10))
        self.answer.pack(fill="both", expand=False, padx=8, pady=(0, 6))
        self.answer.insert("end", "查询结果会显示在这里。")
        self.answer.config(state="disabled")

        self.status = tk.StringVar(value="就绪")
        ttk.Label(root, textvariable=self.status).pack(anchor="w", padx=8, pady=(0, 6))

        self.apps = []
        self.refresh()

    def refresh(self):
        self.status.set("正在扫描已安装软件（应用商店部分可能需要几十秒）...")
        self.root.update_idletasks()

        def worker():
            try:
                apps = list_installed()
                self.root.after(0, lambda: self.fill(apps))
            except Exception as e:
                self.root.after(0, lambda: self.status.set(f"扫描出错：{e}"))

        threading.Thread(target=worker, daemon=True).start()

    def fill(self, apps):
        self.apps = apps
        self.filter_list()
        self.status.set(f"共 {len(apps)} 个软件（按大小排序，可用搜索框过滤）")

    def filter_list(self):
        kw = self.search_var.get().strip().lower()
        self.tree.delete(*self.tree.get_children())
        for idx, a in enumerate(self.apps):
            if kw and kw not in a["name"].lower() and kw not in a["publisher"].lower():
                continue
            self.tree.insert("", "end", iid=str(idx), text=a["name"], values=(
                a["publisher"], a["version"], fmt_size(a["size"]), a["date"], a["source"]))

    def on_select(self, event=None):
        sel = self.tree.selection()
        if sel:
            a = self.apps[int(sel[0])]
            self.sel_var.set(f"已选中：{a['name']}  {a['version']}")
            self.ask_btn.config(state="normal")
            can_uninstall = bool(a["uninstall"]) or a["source"] == "应用商店"
            self.uninstall_btn.config(state="normal" if can_uninstall else "disabled")
            self._selected = a
        else:
            self.ask_btn.config(state="disabled")
            self.uninstall_btn.config(state="disabled")

    def uninstall(self):
        from tkinter import messagebox
        a = getattr(self, "_selected", None)
        if not a:
            return
        if not messagebox.askyesno("确认卸载",
                                   f"确定要卸载【{a['name']}】吗？\n\n"
                                   f"将调用该软件官方的卸载程序，过程中可能弹出确认窗口或权限提示。",
                                   parent=self.root):
            return
        self.uninstall_btn.config(state="disabled")
        self.status.set(f"正在卸载 {a['name']} ...")

        def worker():
            try:
                run_uninstall(a)
                self.root.after(0, lambda: self._uninstall_done(a["name"], None))
            except Exception as e:
                self.root.after(0, lambda: self._uninstall_done(a["name"], str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _uninstall_done(self, name, error):
        from tkinter import messagebox
        self.uninstall_btn.config(state="normal")
        if error:
            messagebox.showwarning("卸载未成功", f"{name}\n\n{error}", parent=self.root)
            self.status.set("就绪")
        else:
            messagebox.showinfo("卸载完成", f"{name} 的卸载程序已执行完毕。", parent=self.root)
            self.refresh()

    def set_key(self):
        from tkinter import simpledialog, messagebox
        old = get_api_key()
        key = simpledialog.askstring("DeepSeek API Key",
                                     "输入你的 DeepSeek API Key（sk- 开头）：\n"
                                     "会用 Windows 加密后保存在本机 config.json",
                                     initialvalue=old, parent=self.root)
        if key:
            try:
                set_api_key(key)
            except Exception as e:
                messagebox.showwarning("保存失败", str(e), parent=self.root)
                return
            messagebox.showinfo("已保存", "API Key 已加密保存到本机。")

    def ask(self):
        key = get_api_key()
        if not key:
            self.set_key()
            key = get_api_key()
            if not key:
                return
        a = getattr(self, "_selected", None)
        if not a:
            return
        self.answer.config(state="normal")
        self.answer.delete("1.0", "end")
        self.answer.insert("end", f"正在询问 DeepSeek：{a['name']} ...")
        self.answer.config(state="disabled")
        self.ask_btn.config(state="disabled")
        self.status.set("API 查询中...")

        def worker():
            try:
                ans = ask_deepseek(key, a)
                self.root.after(0, lambda: self.show_answer(ans))
            except Exception as e:
                self.root.after(0, lambda: self.show_answer(f"查询失败：{e}\n\n请检查 API Key 是否有效、网络是否正常。"))

        threading.Thread(target=worker, daemon=True).start()

    def show_answer(self, text):
        self.answer.config(state="normal")
        self.answer.delete("1.0", "end")
        self.answer.insert("end", text)
        self.answer.config(state="disabled")
        self.ask_btn.config(state="normal")
        self.status.set("就绪")


def main():
    if os.environ.get("SOFT_QUERY_NO_GUI"):
        apps = list_installed()
        print(f"共 {len(apps)} 个软件：")
        for a in apps[:50]:
            print(f"  {a['name']} | {a['publisher']} | {a['version']} | {fmt_size(a['size'])}")
        return
    import tkinter as tk
    root = tk.Tk()
    SoftQueryApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
