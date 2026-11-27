# -*- coding: utf-8 -*-
"""
打包给同事 —— 生成一个可直接拷走的绿色文件夹(或 zip)

用法:
    python make_dist.py                      # 默认: 仅代码, 不带桌宠包(canvas 兜底, ~100KB)
    python make_dist.py --roles kimi         # 带 kimi 一个角色
    python make_dist.py --roles kimi,glm     # 带多个角色
    python make_dist.py --roles all          # 全部 5 个角色
    python make_dist.py --roles all --embed-python   # 零依赖包: 内嵌便携 Python, 同事双击即用
    python make_dist.py --roles kimi --zip   # 顺便压成 zip(PNG 已压缩, 体积缩减有限)

产物:
    dist/chessboard_desktop_pet/            # 文件夹
    dist/chessboard_desktop_pet_v1.0.1_20261123.zip   # 压缩包(默认生成)
版本每次打包自动递增(patch 位 +1), 并写入包内 version.txt。
整个文件夹或 zip 拷给同事即可。
"""
import argparse
import glob
import os
import re
import shutil
import sys
import time
import zipfile

SRC = os.path.dirname(os.path.abspath(__file__))
ANIMS = os.path.join(SRC, "pets", "anims")

# 精简便携 Python 的保留规则(其余 site-packages 一律剔除)
SP_KEEP_DIRS = ("PIL", "pip")
SP_KEEP_GLOBS = ("pillow-*.dist-info", "pip-*.dist-info", "setuptools*",
                 "pkg_resources", "wheel*")

README = """\
桌宠五子棋 · 摸鱼版 —— 使用说明
================================

一、启动
    双击 start_gomoku.bat 即可(无黑窗, 直接出桌宠)。
    也可以自定义端口: 命令行运行  start_gomoku.bat 27184
    (同一台电脑开两个实例互测时才需要改端口, 默认 27183)

二、首次启动
    - 电脑需要装 Python 3(官网 python.org 安装包, 勾选 tcl/tk)。
      start_gomoku.bat 会自动检测, 缺 Pillow 会自动装。
    - 如果本文件夹里带了 python\\ 子目录(免装 Python 的便携版),
      会直接用它, 什么都不用装。
    - 首次对局时 Windows 防火墙弹窗, 点"允许访问"。

三、玩法
    - 平时是桌宠: 左键按住可拖动, 右键弹菜单。
    - 菜单 -> 五子棋: 输入对方 IP(或点选好友)发起对局,
      需与对方在同一局域网, 双方都要开着程序。
    - 系统随机黑白, 黑先行; 连成五子获胜, 有认输和邀新一局。
    - 菜单 -> 设置(浏览器打开): 改昵称、换桌宠形象、
      添加好友 IP、调桌宠大小、查战绩。
    - Ctrl+Q 全局隐藏/呼出; Esc 快速隐藏; 滚轮调透明度
      (0% 完全隐形但仍可落子, 摸鱼神器)。
    - 5 秒无操作自动回到桌宠待机(对局中不回)。

四、常见问题
    - 对方 IP 怎么看: 对方桌宠右键 -> 设置页顶部会显示本机 IP。
    - 连不上: 检查双方是否同一局域网、防火墙是否放行、
      IP 是否填对(设置页里加好友后以后直接点选)。
    - 想换桌宠形象: 设置 -> 形象与动作, 里面有哪些角色取决于
      发给你的包里带了几个(pets\\anims\\ 下的文件夹)。
    - 精简包没有内置形象: 设置 -> 角色包, 可在线下载
      (每个约 1.2~2GB, 下载完桌宠自动换新形象)。
"""


def dir_size_mb(path):
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total / 1e6


def available_roles():
    if not os.path.isdir(ANIMS):
        return []
    return sorted(d for d in os.listdir(ANIMS)
                  if os.path.isdir(os.path.join(ANIMS, d))
                  and os.path.isfile(os.path.join(ANIMS, d, "pack.json")))


def copy_tree(src, dst):
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))


def build_slim_python(python_src, cache_dir):
    """从本机安装的 Python 精简出便携运行时: 根目录 exe/dll + DLLs + tcl +
    Lib(剔除 site-packages 后只留 PIL/pip/setuptools)。
    结果缓存到 cache_dir, 已存在直接复用。"""
    exe = os.path.join(python_src, "python.exe")
    if not os.path.isfile(exe):
        sys.exit(f"[X] 找不到 Python: {exe}")
    if not os.path.isdir(os.path.join(python_src, "tcl")):
        sys.exit("[X] 该 Python 没有 tcl/ 目录(缺 tkinter 运行时), 换一个完整安装的 Python")

    if os.path.isdir(cache_dir):
        print(f"[OK] 复用精简 Python 缓存 {cache_dir}")
        return cache_dir

    os.makedirs(cache_dir)
    # 根目录: 可执行文件 + dll + 许可证
    for name in os.listdir(python_src):
        p = os.path.join(python_src, name)
        if os.path.isfile(p) and (name.endswith((".exe", ".dll", ".txt", ".ini"))
                                  or name.startswith("python")):
            shutil.copy2(p, cache_dir)
    for sub in ("DLLs", "tcl"):
        shutil.copytree(os.path.join(python_src, sub),
                        os.path.join(cache_dir, sub),
                        ignore=shutil.ignore_patterns("__pycache__"))
    # Lib: 整个拷进来再剔除 site-packages, 只留运行必需
    lib_src = os.path.join(python_src, "Lib")
    lib_dst = os.path.join(cache_dir, "Lib")
    shutil.copytree(lib_src, lib_dst,
                    ignore=shutil.ignore_patterns("__pycache__", "site-packages",
                                                  "test", "tests", "idlelib",
                                                  "turtle*demo*"))
    sp_dst = os.path.join(lib_dst, "site-packages")
    os.makedirs(sp_dst)
    sp_src = os.path.join(lib_src, "site-packages")
    keep = set()
    for name in SP_KEEP_DIRS:
        if os.path.isdir(os.path.join(sp_src, name)):
            keep.add(name)
    for pat in SP_KEEP_GLOBS:
        keep.update(os.path.basename(x) for x in glob.glob(os.path.join(sp_src, pat)))
    if not any(n.lower().startswith("pil") for n in keep):
        sys.exit("[X] 源 Python 的 site-packages 里没有 Pillow, 先装好 Pillow 再打包")
    for name in sorted(keep):
        shutil.copytree(os.path.join(sp_src, name), os.path.join(sp_dst, name),
                        ignore=shutil.ignore_patterns("__pycache__"))
    print(f"[OK] 精简 Python 就绪  {dir_size_mb(cache_dir):.0f} MB  ({cache_dir})")
    return cache_dir


def clear_dir(dest):
    """清空/删除产物目录。shutil.rmtree 可能被环境回收站策略拦截, 失败则逐文件兜底。"""
    if not os.path.isdir(dest):
        return
    try:
        shutil.rmtree(dest)
        return
    except OSError:
        pass
    bad = []
    for root, dirs, files in os.walk(dest, topdown=False):
        for f in files:
            try:
                os.remove(os.path.join(root, f))
            except OSError as e:
                bad.append(str(e))
        for d in dirs:
            try:
                os.rmdir(os.path.join(root, d))
            except OSError:
                pass
    try:
        os.rmdir(dest)
    except OSError as e:
        bad.append(str(e))
    if bad:
        sys.exit("[X] 无法清空产物目录(可能有文件被占用): "
                 f"{dest}\n    {bad[0]}\n    请关掉占用的程序(如资源管理器)后重试")


def next_version(out_dir, name):
    """扫描 out_dir 下已有的 <name>_vX.Y.Z*.zip, patch 位 +1 生成新版本号; 首个版本 1.0.0"""
    top = [1, 0, -1]
    for f in os.listdir(out_dir):
        m = re.match(rf"^{re.escape(name)}_v(\d+)\.(\d+)\.(\d+)", f)
        if m:
            v = [int(x) for x in m.groups()]
            if v > top:
                top = v
    return f"{top[0]}.{top[1]}.{top[2] + 1}"


def parse_ver(filename, pkg):
    """从 <pkg>_vX.Y.Z... 文件名解析 (major, minor, patch), 解析不到返回 None"""
    m = re.match(rf"^{re.escape(pkg)}_v(\d+)\.(\d+)\.(\d+)", filename)
    return tuple(int(x) for x in m.groups()) if m else None


def folder_version(out_dir, name):
    """dist/<name>/version.txt 里的版本号, 读不到返回 None"""
    p = os.path.join(out_dir, name, "version.txt")
    if os.path.isfile(p):
        try:
            with open(p, encoding="utf-8") as f:
                m = re.search(r"v(\d+)\.(\d+)\.(\d+)", f.read())
            if m:
                return tuple(int(x) for x in m.groups())
        except OSError:
            pass
    return None


def sync_latest(out_dir, name):
    """把 dist 里最新全量版产物镜像到 dist/latest/, 这个文件夹直接整包发给同事:
    没装过的直接安装, 装过的覆盖安装也行(想省流量可另发 make_patch 的补丁 zip)。
    同盘优先硬链接(秒完成、不占双倍空间, 拷走/发送时自动变成正常文件), 失败退回复制。
    返回 latest 文件夹路径。"""
    latest = os.path.join(out_dir, "latest")
    zips, setups = {}, {}
    if os.path.isdir(out_dir):
        for f in os.listdir(out_dir):
            v = parse_ver(f, name)
            if v is None or "_update_" in f:  # 补丁不算全量
                continue
            if f.endswith(".zip"):
                zips[v] = f
            elif f.endswith("_setup.exe"):
                setups[v] = f
    if not zips and not setups:
        print("[!] latest 未同步: dist 里还没有全量产物")
        return None
    top = max(setups | zips.keys())
    top_s = ".".join(map(str, top))
    files, kind, has_pets = [], None, None
    if top in setups:  # 优先安装包: setup.exe + 同版本所有 setup-*.bin
        kind = "安装包(setup.exe)"
        exe = setups[top]
        files.append(exe)
        base = exe[:-len(".exe")]
        files += sorted(f for f in os.listdir(out_dir)
                        if f.startswith(base + "-") and f.endswith(".bin"))
        # setup 由 dist/<name> 文件夹打出, 该文件夹有桌宠包即视为带了
        anims = os.path.join(out_dir, name, "pets", "anims")
        has_pets = os.path.isdir(anims) and any(os.scandir(anims))
    else:
        kind = "绿色 zip"
        files.append(zips[top])
        with zipfile.ZipFile(os.path.join(out_dir, zips[top])) as zf:
            has_pets = any(n.startswith(f"{name}/pets/anims/") for n in zf.namelist())

    clear_dir(latest)
    os.makedirs(latest)
    for f in files:
        src, dst = os.path.join(out_dir, f), os.path.join(latest, f)
        try:
            os.link(src, dst)
        except OSError:
            shutil.copy2(src, dst)
    tip = (f"棋盘桌宠五子棋 v{top_s} 安装说明\n"
           f"{'=' * 32}\n\n"
           f"双击 setup.exe 安装; setup.exe 和所有 setup-*.bin 必须放在\n"
           f"同一个文件夹里, 发送/下载时别把它们拆开。\n"
           f"不管有没有装过都用这个: 没装过的走全新安装, 装过的安装器会\n"
           f"自动识别并升级(昵称/好友/战绩保留)。安装前先退出桌宠,\n"
           f"若忘退出安装器也会自动关闭它。\n"
           if top in setups else
           f"棋盘桌宠五子棋 v{top_s} 使用说明\n"
           f"{'=' * 32}\n\n"
           f"解压到任意文件夹, 双击 start_gomoku.bat 启动。\n")
    with open(os.path.join(latest, "安装说明.txt"), "w", encoding="utf-8") as f:
        f.write(tip)
    total = sum(os.path.getsize(os.path.join(latest, f))
                for f in os.listdir(latest)) / 1e9
    if has_pets is False:
        print("[!] 警告: latest 里的全量版不含桌宠视频包, 同事装完只有兜底形象")
    print(f"[OK] latest 已同步: v{top_s} {kind}  共 {total:.2f} GB  ({latest})")
    return latest


def make_zip(dest, zip_path):
    """STORED 封装(PNG 已压缩, 不做二次压缩, 速度快), 目录结构带包名一层"""
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as zf:
        for root, _dirs, files in os.walk(dest):
            for f in files:
                p = os.path.join(root, f)
                zf.write(p, os.path.relpath(p, os.path.dirname(dest)))
    return zip_path


def main():
    ap = argparse.ArgumentParser(description="打包桌宠五子棋给同事")
    ap.add_argument("--roles", default="none",
                    help="角色名, 逗号分隔; all=全部; none=不带桌宠包")
    ap.add_argument("--out", default=os.path.join(SRC, "dist"))
    ap.add_argument("--name", default="chessboard_desktop_pet")
    ap.add_argument("--zip", dest="zip", action="store_true", default=True,
                    help="打包后生成 zip 压缩包(默认开启, STORED 不二次压缩, 速度快)")
    ap.add_argument("--no-zip", dest="zip", action="store_false",
                    help="只生成文件夹, 不压 zip")
    ap.add_argument("--embed-python", action="store_true",
                    help="内嵌精简便携 Python(包内 python\\), 同事无需安装 Python")
    ap.add_argument("--python-src", default="D:\\Python",
                    help="精简用的本机 Python 源(默认 D:\\Python)")
    args = ap.parse_args()

    roles_all = available_roles()
    if args.roles.strip().lower() == "all":
        roles = roles_all
    elif args.roles.strip().lower() in ("", "none"):
        roles = []
    else:
        roles = [r.strip() for r in args.roles.split(",") if r.strip()]
        bad = [r for r in roles if r not in roles_all]
        if bad:
            sys.exit(f"[X] 不存在的角色: {bad}  可选: {roles_all}")

    dest = os.path.join(args.out, args.name)
    clear_dir(dest)
    os.makedirs(dest)

    # 代码与启动器
    shutil.copy2(os.path.join(SRC, "gomoku.py"), dest)
    shutil.copy2(os.path.join(SRC, "start_gomoku.bat"), dest)
    with open(os.path.join(dest, "使用说明.txt"), "w", encoding="utf-8") as f:
        f.write(README)

    # 不带用户自己的战绩/好友/棋子位置, 同事拿到的是全新配置
    print(f"[OK] 代码 + 启动器 + 使用说明  ->  {dest}")

    # 桌宠包
    for r in roles:
        src_r = os.path.join(ANIMS, r)
        dst_r = os.path.join(dest, "pets", "anims", r)
        print(f"[..] 复制桌宠包 {r} ...")
        copy_tree(src_r, dst_r)
        print(f"[OK] {r}  {dir_size_mb(dst_r):.0f} MB")

    # 零依赖: 内嵌精简便携 Python -> 包内 python\ , start_gomoku.bat 会最优先用它
    if args.embed_python:
        cache = build_slim_python(args.python_src, os.path.join(SRC, "_pyembed", "python_slim"))
        print("[..] 内嵌便携 Python ...")
        copy_tree(cache, os.path.join(dest, "python"))
        print("[OK] python\\  便携运行时已嵌入")

    total = dir_size_mb(dest)
    print(f"[OK] 总体积 {total:.0f} MB  ({dest})")

    # 版本号 + 包内版本文件
    os.makedirs(args.out, exist_ok=True)
    ver = next_version(args.out, args.name)
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    with open(os.path.join(dest, "version.txt"), "w", encoding="utf-8") as f:
        f.write(f"版本: v{ver}\n打包时间: {now}\n")
    print(f"[OK] 版本 v{ver}  ({dest})")

    if args.zip:
        zip_path = os.path.join(args.out,
                                f"{args.name}_v{ver}_{time.strftime('%Y%m%d')}.zip")
        if os.path.isfile(zip_path):
            os.remove(zip_path)
        print("[..] 生成 zip 压缩包(STORED 不二次压缩, 只封装) ...")
        make_zip(dest, zip_path)
        print(f"[OK] {zip_path}  {os.path.getsize(zip_path)/1e6:.0f} MB")

    # 同步 dist/latest/ (整夹发给同事的最新全量版)
    sync_latest(args.out, args.name)


if __name__ == "__main__":
    main()
