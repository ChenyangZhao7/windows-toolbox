# -*- coding: utf-8 -*-
"""系统工具箱
整合四个小工具：整理桌面 / 磁盘体检 / 软件管家 / 风扇控制
"""
import os
import sys
import json
import ctypes
import threading
import importlib.util

import tkinter as tk
from tkinter import ttk, messagebox, simpledialog, scrolledtext

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

MODULES = {
    "organize": r"D:\Tools\DesktopOrganizer\organize_desktop.py",
    "disk": r"D:\Tools\DiskCheckup\disk_checkup.py",
    "soft": r"D:\Tools\SoftQuery\soft_query.py",
    "fan": r"D:\Tools\FanControl\fan_control.py",
}


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


ORG = load_module("organize_desktop", MODULES["organize"])
DISK = load_module("disk_checkup", MODULES["disk"])
SOFT = load_module("soft_query", MODULES["soft"])
FAN = load_module("fan_control", MODULES["fan"])


def is_admin():
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def elevate_self():
    """以管理员身份重启工具箱"""
    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable,
                                        f'"{os.path.abspath(__file__)}"', None, 1)
    os._exit(0)


# ==================== 选项卡1：整理桌面 ====================

class OrganizeTab:
    def __init__(self, parent):
        fr = ttk.Frame(parent, padding=10)
        self.frame = fr
        ttk.Label(fr, text="把桌面散落的文件按后缀归类，抽空的文件夹自动删除",
                  wraplength=520).pack(anchor="w")
        ttk.Label(fr, text="规则：只动文档/图片/视频/音频/压缩包，代码项目和游戏不受影响",
                  wraplength=520, foreground="#666").pack(anchor="w", pady=(2, 8))
        self.btn = ttk.Button(fr, text="🧹 立即整理桌面", command=self.run)
        self.btn.pack(anchor="w")
        self.out = scrolledtext.ScrolledText(fr, height=16, wrap="word", state="disabled")
        self.out.pack(fill="both", expand=True, pady=8)

    def log(self, text):
        self.out.config(state="normal")
        self.out.delete("1.0", "end")
        self.out.insert("end", text)
        self.out.config(state="disabled")

    def run(self):
        self.btn.config(state="disabled")
        self.log("整理中，请稍候...")

        def worker():
            try:
                extracted, src_dirs, failed, touched = ORG.extract_files()
                moved, failed_top = ORG.organize_top()
                failed += failed_top
                removed = ORG.remove_empty_dirs(touched)
                total = sum(len(v) for v in moved.values())
                lines = [f"✅ 整理完成",
                         f"抽取：从 {src_dirs} 个文件夹取出 {extracted} 个文档/媒体文件",
                         f"归类：按后缀归入 {len(moved)} 个文件夹，共 {total} 个文件",
                         f"清场：删除空文件夹 {removed} 个"]
                if failed:
                    lines.append(f"跳过：{failed} 个文件被占用或无权限")
                if extracted == 0 and total == 0:
                    lines = ["✅ 桌面已经很整洁，没有需要整理的文件。"]
                self.frame.winfo_toplevel().after(0, lambda: self.log("\n".join(lines)))
            except Exception as e:
                self.frame.winfo_toplevel().after(0, lambda: self.log(f"❌ 出错：{e}"))
            finally:
                self.frame.winfo_toplevel().after(0, lambda: self.btn.config(state="normal"))

        threading.Thread(target=worker, daemon=True).start()


# ==================== 选项卡2：磁盘体检 ====================

class DiskTab:
    def __init__(self, parent):
        fr = ttk.Frame(parent, padding=10)
        self.frame = fr
        top = ttk.Frame(fr)
        top.pack(fill="x")
        ttk.Label(top, text="磁盘：").pack(side="left")
        self.drive_var = tk.StringVar()
        self.drive_box = ttk.Combobox(top, textvariable=self.drive_var, state="readonly", width=42)
        self.drive_box.pack(side="left", padx=4)
        ttk.Button(top, text="加载分布", command=self.show_drive).pack(side="left", padx=4)
        self.info = tk.StringVar()
        ttk.Label(top, textvariable=self.info).pack(side="left", padx=8)

        self.tree = ttk.Treeview(fr, columns=("size",), displaycolumns=("size",))
        self.tree.heading("#0", text="名称", anchor="w")
        self.tree.heading("size", text="大小", anchor="e")
        self.tree.column("#0", width=380)
        self.tree.column("size", width=110, anchor="e")
        self.tree.pack(fill="both", expand=True, pady=6)
        self.tree.bind("<<TreeviewOpen>>", self.on_expand)
        self.status = tk.StringVar(value="选好磁盘后点「加载分布」开始扫描")
        ttk.Label(fr, textvariable=self.status).pack(anchor="w")
        self._jobs = []
        self._cache = {}      # 路径 -> 子项大小列表，展开/切回时复用
        self._scanning = set()  # 正在扫描的路径，避免重复排队
        self.load_drives()

    def load_drives(self):
        self._drives = {}
        labels = []
        for root_path, name in DISK.get_drives():
            total, free = DISK.drive_space(root_path)
            label = f"{name} ({root_path})  剩余 {DISK.fmt_size(free)} / {DISK.fmt_size(total)}"
            labels.append(label)
            self._drives[label] = (root_path, total, free)
        self.drive_box["values"] = labels
        if labels:
            self.drive_box.current(0)

    def on_show(self):
        pass  # 不自动加载，等用户点「加载分布」

    def show_drive(self):
        label = self.drive_var.get()
        if label not in self._drives:
            self.status.set("没有可用的磁盘")
            return
        path, total, free = self._drives[label]
        used = total - free
        pct = used / total * 100 if total else 0
        self.info.set(f"已用 {DISK.fmt_size(used)}（{pct:.0f}%）")
        self._cache.clear()  # 「加载分布」= 重新扫描，丢掉旧缓存
        self.tree.delete(*self.tree.get_children())
        node = self.tree.insert("", "end", text=path, values=(DISK.fmt_size(used),), open=True)
        self.tree.item(node, tags=(path, "pending"))
        self.fill(node, path)

    def on_expand(self, event):
        node = self.tree.focus()
        tags = self.tree.item(node, "tags")
        if len(tags) == 2 and tags[1] == "pending":
            self.tree.item(node, tags=(tags[0], "done"))
            self.fill(node, tags[0])

    def fill(self, node, path):
        if path in self._cache:  # 以前扫过，直接复用
            self._fill_done(node, path, self._cache[path])
            return
        if path in self._scanning:  # 同一目录只排一次队
            return
        self._scanning.add(path)
        self.status.set(f"正在扫描 {path} ...")
        self.tree.delete(*self.tree.get_children(node))

        def worker():
            try:
                items = DISK.children_sizes(path)
            except Exception:
                items = []
            top = self.frame.winfo_toplevel()
            top.after(0, lambda: self._fill_done(node, path, items))

        threading.Thread(target=worker, daemon=True).start()

    def _fill_done(self, node, path, items):
        self._scanning.discard(path)
        self._cache[path] = items
        if not self.tree.exists(node):
            return  # 期间已切换磁盘/清空
        self.tree.delete(*self.tree.get_children(node))
        for n, s, is_dir in items:
            full = os.path.join(path, n)
            if is_dir:
                child = self.tree.insert(node, "end", text=n, values=(DISK.fmt_size(s),),
                                         tags=(full, "pending"))
                self.tree.insert(child, "end", text="...")
            else:
                self.tree.insert(node, "end", text=n, values=(DISK.fmt_size(s),))
        self.tree.item(node, tags=(path, "done"))  # 标成已加载，折叠后再展开不会重扫
        self.status.set("就绪（点 ▸ 逐层展开，已扫过的目录不会重复扫描）")


# ==================== 选项卡3：软件管家 ====================

class SoftTab:
    def __init__(self, parent):
        fr = ttk.Frame(parent, padding=10)
        self.frame = fr
        top = ttk.Frame(fr)
        top.pack(fill="x")
        ttk.Button(top, text="刷新", command=self.refresh).pack(side="left")
        ttk.Button(top, text="设置 API Key", command=self.set_key).pack(side="left", padx=6)
        self.search_var = tk.StringVar()
        sv = ttk.Entry(top, textvariable=self.search_var, width=26)
        sv.pack(side="right")
        sv.bind("<KeyRelease>", lambda e: self.filter_list())
        ttk.Label(top, text="搜索：").pack(side="right")

        cols = ("publisher", "version", "size")
        self.tree = ttk.Treeview(fr, columns=cols, displaycolumns=cols)
        self.tree.heading("#0", text="软件名称", anchor="w")
        self.tree.heading("publisher", text="发布者", anchor="w")
        self.tree.heading("version", text="版本", anchor="w")
        self.tree.heading("size", text="大小", anchor="e")
        self.tree.column("#0", width=240)
        self.tree.column("publisher", width=170)
        self.tree.column("version", width=80)
        self.tree.column("size", width=80, anchor="e")
        self.tree.pack(fill="both", expand=True, pady=4)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)

        mid = ttk.Frame(fr)
        mid.pack(fill="x")
        self.ask_btn = ttk.Button(mid, text="用 DeepSeek 查询功能", command=self.ask, state="disabled")
        self.ask_btn.pack(side="right")
        self.un_btn = ttk.Button(mid, text="卸载此软件", command=self.uninstall, state="disabled")
        self.un_btn.pack(side="right", padx=6)

        self.answer = scrolledtext.ScrolledText(fr, height=6, wrap="word", state="disabled")
        self.answer.pack(fill="x", pady=4)
        self.status = tk.StringVar(value="点击「刷新」扫描已安装软件")
        ttk.Label(fr, textvariable=self.status).pack(anchor="w")
        self.apps = []

    def on_show(self):
        pass  # 不自动扫描，等用户点「刷新」

    def refresh(self):
        self.status.set("扫描中（应用商店部分可能需几十秒）...")
        top = self.frame.winfo_toplevel()
        top.update_idletasks()

        def worker():
            try:
                apps = SOFT.list_installed()
                top.after(0, lambda: self._loaded(apps))
            except Exception as e:
                top.after(0, lambda: self.status.set(f"扫描出错：{e}"))

        threading.Thread(target=worker, daemon=True).start()

    def _loaded(self, apps):
        self.apps = apps
        self.filter_list()
        self.status.set(f"共 {len(apps)} 个软件（按大小排序）")

    def filter_list(self):
        kw = self.search_var.get().strip().lower()
        self.tree.delete(*self.tree.get_children())
        for idx, a in enumerate(self.apps):
            if kw and kw not in a["name"].lower() and kw not in a["publisher"].lower():
                continue
            self.tree.insert("", "end", iid=str(idx), text=a["name"], values=(
                a["publisher"], a["version"], SOFT.fmt_size(a["size"])))

    def on_select(self, event=None):
        sel = self.tree.selection()
        top = self.frame.winfo_toplevel()
        if sel:
            a = self.apps[int(sel[0])]
            self._sel = a
            self.ask_btn.config(state="normal")
            can = bool(a["uninstall"]) or a["source"] == "应用商店"
            self.un_btn.config(state="normal" if can else "disabled")
            self.status.set(f"已选中：{a['name']} {a['version']}")
        else:
            self.ask_btn.config(state="disabled")
            self.un_btn.config(state="disabled")

    def set_key(self):
        key = simpledialog.askstring("DeepSeek API Key",
                                     "输入你的 DeepSeek API Key（sk- 开头）：\n"
                                     "会用 Windows 加密后保存在本机 config.json",
                                     initialvalue=SOFT.get_api_key(),
                                     parent=self.frame.winfo_toplevel())
        if key:
            try:
                SOFT.set_api_key(key)
            except Exception as e:
                messagebox.showwarning("保存失败", str(e))
                return
            messagebox.showinfo("已保存", "API Key 已加密保存到本机。")

    def ask(self):
        a = getattr(self, "_sel", None)
        if not a:
            return
        key = SOFT.get_api_key()
        if not key:
            self.set_key()
            key = SOFT.get_api_key()
            if not key:
                return
        self.answer.config(state="normal")
        self.answer.delete("1.0", "end")
        self.answer.insert("end", f"正在询问 DeepSeek：{a['name']} ...")
        self.answer.config(state="disabled")
        self.ask_btn.config(state="disabled")
        top = self.frame.winfo_toplevel()

        def worker():
            try:
                ans = SOFT.ask_deepseek(key, a)
                top.after(0, lambda: self._answered(ans))
            except Exception as e:
                top.after(0, lambda: self._answered(f"查询失败：{e}"))

        threading.Thread(target=worker, daemon=True).start()

    def _answered(self, text):
        self.answer.config(state="normal")
        self.answer.delete("1.0", "end")
        self.answer.insert("end", text)
        self.answer.config(state="disabled")
        self.ask_btn.config(state="normal")

    def uninstall(self):
        a = getattr(self, "_sel", None)
        if not a:
            return
        top = self.frame.winfo_toplevel()
        if not messagebox.askyesno("确认卸载", f"确定要卸载【{a['name']}】吗？", parent=top):
            return
        self.un_btn.config(state="disabled")
        self.status.set(f"正在卸载 {a['name']} ...")

        def worker():
            try:
                SOFT.run_uninstall(a)
                top.after(0, lambda: self._uninstalled(a["name"], None))
            except Exception as e:
                top.after(0, lambda: self._uninstalled(a["name"], str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _uninstalled(self, name, error):
        top = self.frame.winfo_toplevel()
        self.un_btn.config(state="normal")
        if error:
            messagebox.showwarning("卸载未成功", f"{name}\n\n{error}", parent=top)
            self.status.set("就绪")
        else:
            messagebox.showinfo("卸载完成", f"{name} 的卸载程序已执行完毕。", parent=top)
            self.refresh()


# ==================== 选项卡4：风扇控制 ====================

class FanTab:
    def __init__(self, parent):
        fr = ttk.Frame(parent, padding=10)
        self.frame = fr
        ttk.Label(fr, text="联想风扇控制", font=("Microsoft YaHei UI", 11)).pack(anchor="w")
        self.admin_var = tk.StringVar()
        ttk.Label(fr, textvariable=self.admin_var, foreground="#a00").pack(anchor="w", pady=2)
        self.status_var = tk.StringVar(value="读取中...")
        ttk.Label(fr, textvariable=self.status_var, justify="left",
                  font=("Consolas", 11)).pack(pady=8)
        btns = ttk.Frame(fr)
        btns.pack()
        ttk.Button(btns, text="🔥 全速风扇：开", width=18,
                   command=lambda: self.set_full(True)).pack(side="left", padx=6)
        ttk.Button(btns, text="🌿 全速风扇：关", width=18,
                   command=lambda: self.set_full(False)).pack(side="left", padx=6)
        self.msg = tk.StringVar(value="全速模式适合打游戏/渲染；日常使用建议关闭。")
        ttk.Label(fr, textvariable=self.msg, wraplength=500, foreground="#555").pack(pady=8)
        self.elevate_btn = ttk.Button(fr, text="以管理员身份重启工具箱",
                                      command=elevate_self)
        self._busy = False
        self.loop()

    def _call(self, fn):
        """把结果交回 Tk 主线程（窗口已关闭时忽略）"""
        try:
            self.frame.winfo_toplevel().after(0, fn)
        except Exception:
            pass

    def set_full(self, on):
        if self._busy:
            return
        self._busy = True
        self.msg.set("正在设置...")

        def worker():
            try:
                FAN.fan_set_fullspeed(on)
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
        self.read_once()

    def read_once(self):
        if not is_admin():
            self.admin_var.set("当前无管理员权限，无法读写风扇状态")
            self.status_var.set("（点下方按钮以管理员身份重启工具箱）")
            self.elevate_btn.pack(anchor="w", pady=4)
            return
        self.elevate_btn.pack_forget()
        self.admin_var.set("")
        if self._busy:
            return  # 上一次还没回来，别叠加
        self._busy = True

        def worker():
            try:
                st, err = FAN.read_status(), None
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
        if st.get("temp") is not None:
            unit = "°C" if isinstance(st["temp"], float) else " (原始值)"
            lines.append(f"传感器温度：{st['temp']}{unit}")
        for e in st["errors"]:
            lines.append(f"⚠ {e}")
        self.status_var.set("\n".join(lines) if lines else "无法读取状态")

    def loop(self):
        try:
            nb = self.frame.master
            visible = nb.select() == str(self.frame)
        except Exception:
            visible = True
        if visible:
            try:
                self.read_once()
            except Exception:
                pass
        try:
            self.frame.winfo_toplevel().after(3000, self.loop)
        except Exception:
            pass


# ==================== 主窗口 ====================

def main():
    root = tk.Tk()
    root.title("系统工具箱")
    root.geometry("820x600")
    nb = ttk.Notebook(root)
    nb.pack(fill="both", expand=True, padx=6, pady=6)
    tab_disk = DiskTab(nb)
    tab_soft = SoftTab(nb)
    tab_org = OrganizeTab(nb)
    tab_fan = FanTab(nb)
    tabs = {tab_org.frame: tab_org, tab_disk.frame: tab_disk,
            tab_soft.frame: tab_soft, tab_fan.frame: tab_fan}
    for tab, text in [(tab_org, "🧹 整理桌面"), (tab_disk, "💽 磁盘体检"),
                      (tab_soft, "📦 软件管家"), (tab_fan, "🌀 风扇控制")]:
        nb.add(tab.frame, text=text)

    def on_tab_changed(event):
        w = nb.nametowidget(nb.select())
        t = tabs.get(w)
        if t and hasattr(t, "on_show"):
            t.on_show()

    nb.bind("<<NotebookTabChanged>>", on_tab_changed)
    root.mainloop()


if __name__ == "__main__":
    main()
