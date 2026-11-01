# -*- coding: utf-8 -*-
"""磁盘体检工具
双击运行：列出所有磁盘的使用情况，点击磁盘或文件夹可逐层查看空间分布。
无界面环境（设 DISK_CHECKUP_NO_GUI=1）时输出文字报告。
"""
import os
import sys
import ctypes
import string
import threading
import queue

GB = 1024 ** 3


def get_drives():
    """返回所有固定磁盘，如 [('C:\\', '本地磁盘'), ...]"""
    drives = []
    bitmask = ctypes.windll.kernel32.GetLogicalDrives()
    for i, letter in enumerate(string.ascii_uppercase):
        if not (bitmask >> i) & 1:
            continue
        root = f"{letter}:\\"
        if ctypes.windll.kernel32.GetDriveTypeW(root) == 3:  # DRIVE_FIXED
            label = ctypes.create_unicode_buffer(261)
            ctypes.windll.kernel32.GetVolumeInformationW(root, label, 261, None, None, None, None, 0)
            name = label.value or "本地磁盘"
            drives.append((root, name))
    return drives


def drive_space(root):
    """返回 (总容量, 可用空间) 字节"""
    free = ctypes.c_ulonglong(0)
    total = ctypes.c_ulonglong(0)
    ctypes.windll.kernel32.GetDiskFreeSpaceExW(root, None, ctypes.byref(total), ctypes.byref(free))
    return total.value, free.value


FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def dir_size(path):
    """计算文件夹总大小（字节），跳过无权限项和链接/联接点（避免重复统计和死循环）"""
    total = 0
    stack = [path]
    while stack:
        cur = stack.pop()
        try:
            with os.scandir(cur) as it:
                for e in it:
                    try:
                        st = e.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    if getattr(st, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT:
                        continue  # 符号链接/联接点，不跟进去
                    if e.is_dir(follow_symlinks=False):
                        stack.append(e.path)
                    else:
                        total += st.st_size
        except OSError:
            continue
    return total



def children_sizes(path):
    """返回 [(名称, 大小, 是否文件夹), ...]，按大小倒序"""
    items = []
    try:
        names = sorted(os.listdir(path))
    except OSError:
        return items
    for n in names:
        p = os.path.join(path, n)
        try:
            if os.path.isdir(p):
                items.append((n, dir_size(p), True))
            else:
                items.append((n, os.path.getsize(p), False))
        except OSError:
            pass
    items.sort(key=lambda x: -x[1])
    return items


def fmt_size(n):
    if n >= GB:
        return f"{n / GB:.2f} GB"
    if n >= 1024 ** 2:
        return f"{n / 1024 ** 2:.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n} B"


# ---------------- 无界面模式：文字报告 ----------------

def text_report():
    lines = []
    for root, name in get_drives():
        total, free = drive_space(root)
        lines.append(f"\n{'=' * 50}")
        lines.append(f"{name} ({root})  总容量 {fmt_size(total)}，剩余 {fmt_size(free)}"
                     + (f"（已用 {total - free} 字节，{(total - free) / total * 100:.0f}%）" if total else ""))
        for n, s, is_dir in children_sizes(root):
            tag = "文件夹" if is_dir else "文件"
            lines.append(f"  {fmt_size(s):>12}  [{tag}] {n}")
    return "\n".join(lines)


# ---------------- 图形界面 ----------------

class CheckupApp:
    def __init__(self, root):
        self.root = root
        root.title("磁盘体检")
        root.geometry("760x520")

        import tkinter as tk
        from tkinter import ttk

        # 顶部：磁盘选择
        top = ttk.Frame(root)
        top.pack(fill="x", padx=8, pady=6)
        ttk.Label(top, text="磁盘：").pack(side="left")
        self.drive_var = tk.StringVar()
        self.drive_box = ttk.Combobox(top, textvariable=self.drive_var, state="readonly", width=40)
        self.drive_box.pack(side="left", padx=4)
        self.drive_box.bind("<<ComboboxSelected>>", self.on_drive_selected)
        self.info_var = tk.StringVar(value="")
        ttk.Label(top, textvariable=self.info_var).pack(side="left", padx=8)

        # 容量条
        self.bar = ttk.Progressbar(root, maximum=100)
        self.bar.pack(fill="x", padx=8)

        # 目录树
        self.tree = ttk.Treeview(root, columns=("size",), displaycolumns=("size",))
        self.tree.heading("#0", text="名称", anchor="w")
        self.tree.heading("size", text="大小", anchor="e")
        self.tree.column("#0", width=440)
        self.tree.column("size", width=120, anchor="e")
        self.tree.pack(fill="both", expand=True, padx=8, pady=6)
        self.tree.bind("<<TreeviewOpen>>", self.on_expand)

        self.status = tk.StringVar(value="就绪")
        ttk.Label(root, textvariable=self.status).pack(anchor="w", padx=8, pady=(0, 6))

        self._jobs = queue.Queue()
        self._polling = False
        self._load_drives()

    def _load_drives(self):
        drives = get_drives()
        self._drive_map = {}
        labels = []
        for root_path, name in drives:
            total, free = drive_space(root_path)
            label = f"{name} ({root_path}) — 剩余 {fmt_size(free)} / {fmt_size(total)}"
            labels.append(label)
            self._drive_map[label] = (root_path, total, free)
        self.drive_box["values"] = labels
        if labels:
            self.drive_box.current(0)
            self.on_drive_selected()

    def on_drive_selected(self, event=None):
        label = self.drive_var.get()
        if label not in self._drive_map:
            return
        path, total, free = self._drive_map[label]
        used = total - free
        pct = used / total * 100 if total else 0
        self.info_var.set(f"已用 {fmt_size(used)}（{pct:.0f}%）")
        self.bar["value"] = pct
        for iid in self.tree.get_children():
            self.tree.delete(iid)
        root_node = self.tree.insert("", "end", text=path, values=(fmt_size(used),), open=True)
        self.tree.item(root_node, tags=(path,))
        self._fill_children(root_node, path)

    def on_expand(self, event):
        node = self.tree.focus()
        tags = self.tree.item(node, "tags")
        if tags and tags[0] == "done":
            return  # 已加载
        path = tags[0] if tags else None
        if path and os.path.isdir(path):
            self._fill_children(node, path)
            self.tree.item(node, tags=("done",))

    def _fill_children(self, node, path):
        """后台线程算大小，避免界面卡死"""
        self.status.set(f"正在扫描 {path} ...")
        for child in self.tree.get_children(node):
            self.tree.delete(child)

        def worker():
            try:
                items = children_sizes(path)
            except Exception:
                items = []
            self._jobs.put((node, path, items))

        threading.Thread(target=worker, daemon=True).start()
        if not self._polling:  # 只保留一条轮询链，避免多次展开叠加
            self._polling = True
            self.root.after(100, self._poll_jobs)

    def _poll_jobs(self):
        try:
            while True:
                node, path, items = self._jobs.get_nowait()
                if not self.tree.exists(node):
                    continue
                for n, s, is_dir in items:
                    full = os.path.join(path, n)
                    tag = ("done",) if not is_dir else (full,)
                    child = self.tree.insert(node, "end", text=n, values=(fmt_size(s),), tags=tag)
                    if is_dir:
                        # 预插入占位符，让文件夹可展开
                        self.tree.insert(child, "end", text="...")
                self.tree.item(node, tags=("done",))
                self.status.set("就绪（点击文件夹前的 ▸ 逐层展开）")
        except queue.Empty:
            pass
        try:
            self.root.after(100, self._poll_jobs)
        except Exception:
            pass  # 窗口已关闭


def main():
    if os.environ.get("DISK_CHECKUP_NO_GUI"):
        print(text_report())
        return
    import tkinter as tk
    root = tk.Tk()
    CheckupApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
