# -*- coding: utf-8 -*-
"""桌面整理工具（彻底重整版）

流程：
1. 抽取：遍历桌面下「普通」文件夹，把文档/图片/视频/音频/压缩包类文件
   移到桌面根目录（重名自动加编号）
2. 归类：桌面根目录的文件按后缀放入以后缀命名的文件夹（jpg/pdf/docx...）
3. 清场：删除这次抽取后被抽空的文件夹，仍有内容的文件夹原样保留

不进入：
- 代码依赖目录（node_modules / venv / build ...）
- 软件、游戏安装目录（前两层里出现 exe/dll 的目录）
- 本工具自己生成的归类文件夹（png / pdf / docx ...）
- 隐藏目录（以 . 开头）

不碰：快捷方式(.lnk)、隐藏文件、系统文件(desktop.ini/Thumbs.db)
"""
import os
import sys
import shutil
import datetime

DESKTOP = r"D:\Desktop"
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")

# 需要抽取出来的文件后缀（文档/媒体/压缩包）
DOC_EXTS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".ico", ".tiff", ".heic", ".avif",
    ".pdf", ".doc", ".docx", ".txt", ".md", ".xls", ".xlsx", ".ppt", ".pptx", ".csv", ".rtf", ".wps", ".et",
    ".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".iso",
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm",
    ".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a",
}

# 自己生成的归类文件夹名（如 png、pdf、docx、7z），抽取时整体跳过，避免每次运行来回搬
DOC_DIR_NAMES = {ext.lstrip(".") for ext in DOC_EXTS} | {"无后缀"}

# 项目和依赖目录：不进入抽取（避免拆散代码项目/游戏）
EXCLUDE_DIRS = {
    "node_modules", ".git", "__pycache__", "venv", ".venv", "env", ".env",
    "dist", "build", "out", "target", "bin", "obj", "packages",
    ".idea", ".vscode", ".vs", "coverage", ".next", ".nuxt", "vendor",
}

# 出现这些后缀就认为该目录是软件/游戏安装目录
PROGRAM_EXTS = (".exe", ".dll", ".sys", ".msi")

SYSTEM_FILES = {"desktop.ini", "thumbs.db"}


def unique_dest(dest_dir: str, name: str) -> str:
    """生成不冲突的目标路径：重名时加 _1 _2 ..."""
    dest = os.path.join(dest_dir, name)
    if not os.path.exists(dest):
        return dest
    stem, ext = os.path.splitext(name)
    for i in range(1, 1000):
        candidate = os.path.join(dest_dir, f"{stem}_{i}{ext}")
        if not os.path.exists(candidate):
            return candidate
    raise RuntimeError(f"无法为 {name} 生成不冲突的文件名")


def looks_like_program(path: str, max_depth: int = 2, max_files: int = 5000) -> bool:
    """目录前两层里出现 exe/dll/msi 就当作软件或游戏安装目录，整理时整体跳过。"""
    seen = 0
    for dirpath, dirs, files in os.walk(path):
        depth = dirpath[len(path):].count(os.sep)
        if depth >= max_depth:
            dirs[:] = []
        for f in files:
            if f.lower().endswith(PROGRAM_EXTS):
                return True
            seen += 1
            if seen > max_files:
                return False
    return False


def extract_files():
    """从普通子文件夹抽取文档/媒体文件到桌面根目录。
    返回 (抽出的文件数, 涉及的文件夹数, 失败数, 被抽过的目录集合)"""
    extracted = 0
    failed = 0
    touched = set()
    for dirpath, dirs, files in os.walk(DESKTOP, topdown=True):
        depth = dirpath[len(DESKTOP):].count(os.sep)
        if depth == 0:
            # 桌面根目录：只决定进入哪些子文件夹
            kept = []
            for d in dirs:
                low = d.lower()
                if low in EXCLUDE_DIRS or low in DOC_DIR_NAMES or d.startswith("."):
                    continue  # 依赖目录 / 本工具自己的归类文件夹 / 隐藏目录
                if looks_like_program(os.path.join(dirpath, d)):
                    continue  # 软件、游戏安装目录
                kept.append(d)
            dirs[:] = kept
            continue  # 根目录的文件交给归类步骤

        dirs[:] = [d for d in dirs if d.lower() not in EXCLUDE_DIRS and not d.startswith(".")]
        for f in files:
            if f.startswith(".") or f.lower() in SYSTEM_FILES:
                continue
            ext = os.path.splitext(f)[1].lower()
            if ext not in DOC_EXTS:
                continue  # 代码、程序组件等留在原处
            src = os.path.join(dirpath, f)
            dest = unique_dest(DESKTOP, f)
            try:
                shutil.move(src, dest)
                extracted += 1
                touched.add(dirpath)
            except OSError:
                failed += 1  # 文件被占用或无权限，留在原处
    return extracted, len(touched), failed, touched


def organize_top():
    """把桌面根目录的文件按后缀归入以后缀命名的文件夹。
    返回 ({后缀: [文件名]}, 失败数)"""
    moved = {}
    failed = 0
    for name in sorted(os.listdir(DESKTOP)):
        src = os.path.join(DESKTOP, name)
        if not os.path.isfile(src):
            continue  # 文件夹不动
        if name.startswith(".") or name.lower() in SYSTEM_FILES:
            continue
        ext = os.path.splitext(name)[1].lower()
        if ext == ".lnk":  # 快捷方式留在原地
            continue
        folder = ext.lstrip(".") if ext else "无后缀"
        dest_dir = os.path.join(DESKTOP, folder)
        try:
            os.makedirs(dest_dir, exist_ok=True)
            dest = unique_dest(dest_dir, name)
            shutil.move(src, dest)
        except OSError:
            failed += 1  # 被占用/无权限，留在原处，不中断整次整理
            continue
        moved.setdefault(folder, []).append(name)
    return moved, failed


def remove_empty_dirs(touched):
    """只删除这次抽取后被抽空的文件夹（含被连带抽空的上级）。
    touched 来自 extract_files() 的第四个返回值。
    返回删除数。"""
    if not touched:
        return 0
    candidates = set()
    for d in touched:
        p = d
        while p and p != DESKTOP and p.startswith(DESKTOP):
            candidates.add(p)
            p = os.path.dirname(p)
    removed = 0
    # 先删深的，上级才可能跟着变空
    for path in sorted(candidates, key=lambda p: p.count(os.sep), reverse=True):
        try:
            if os.path.isdir(path) and not os.listdir(path):
                os.rmdir(path)
                removed += 1
        except OSError:
            pass
    return removed


def notify(title: str, message: str):
    """优先弹图形窗口；无界面环境或 ORGANIZER_NO_GUI=1 时控制台输出。"""
    if os.environ.get("ORGANIZER_NO_GUI"):
        print(f"{title}\n{message}")
        return
    try:
        import tkinter as tk
        from tkinter import messagebox
        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        messagebox.showinfo(title, message, parent=root)
        root.destroy()
    except Exception:
        print(f"{title}\n{message}")


def main():
    started = datetime.datetime.now()
    try:
        extracted, src_dirs, failed, touched = extract_files()
        moved, failed_top = organize_top()
        failed += failed_top
        removed_dirs = remove_empty_dirs(touched)
    except Exception as e:
        notify("整理失败", f"发生错误：{e}\n\n详细信息已写入 logs 目录。")
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(os.path.join(LOG_DIR, "error.log"), "a", encoding="utf-8") as f:
            f.write(f"[{started}] {e}\n")
        sys.exit(1)

    total_moved = sum(len(v) for v in moved.values())
    lines = [f"抽取：从 {src_dirs} 个文件夹中取出 {extracted} 个文档/媒体文件",
             f"归类：按后缀归入 {len(moved)} 个文件夹，共 {total_moved} 个文件",
             f"清场：删除空文件夹 {removed_dirs} 个"]
    if failed:
        lines.append(f"跳过：{failed} 个文件被占用或无权限，留在原处")
    if extracted == 0 and total_moved == 0:
        lines = ["桌面已经很整洁，没有需要整理的文件。"]
    summary = "\n".join(lines)

    os.makedirs(LOG_DIR, exist_ok=True)
    stamp = started.strftime("%Y%m%d_%H%M%S")
    with open(os.path.join(LOG_DIR, f"organize_{stamp}.log"), "w", encoding="utf-8") as f:
        f.write(summary + "\n")
        for folder, items in moved.items():
            f.write(f"\n[{folder}] {len(items)} 个\n")
            for it in items:
                f.write(f"  {it}\n")

    notify("桌面整理完成", summary)


if __name__ == "__main__":
    main()
