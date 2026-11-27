# -*- coding: utf-8 -*-
"""
增量更新包(累计式补丁) —— 只打代码改动, 几 MB 几秒钟, 不重发 7GB 桌宠包

原理(累计式, 可跳版本):
    基线 = dist 里【最新的全量产物】(make_dist 的 zip 或 make_installer 的
    setup.exe, 补丁不算全量)。每次补丁都对比 "最新全量版内容 <-> 当前代码",
    打出来的是从基线直通最新的累计补丁:
      - 从基线版本起的任何版本(哪怕中间隔了好几个补丁)直接打最新补丁即到最新;
      - 只有版本【低于最新全量版】的用户才需要重装全量包。

用法:
    python make_patch.py                          # 生成 dist/<name>_vX.Y.Z_update_YYYYMMDD.zip
    python make_patch.py --baseline <zip 路径>    # 手动指定基线 zip(一般不用)

产物结构(zip 根目录, 解压覆盖到安装目录即可):
    gomoku.py / start_gomoku.bat / 使用说明.txt ...  # 有改动的代码文件(按实际差异)
    version.txt                                      # 新版本号
    del_list.txt + update.bat                        # 有文件被删除时才有
    更新说明.txt

注意: 补丁不携带 pets\\(桌宠视频包)、python\\(便携运行时)和 config.json,
     同事的昵称/好友/战绩/形象原样保留。桌宠包有变动时会提示改发全量包。
"""
import argparse
import os
import re
import sys
import time
import zipfile

SRC = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SRC)
from make_dist import README, next_version, parse_ver, folder_version, sync_latest  # noqa: E402

# 补丁负责分发的代码文件(与 make_dist 的代码载荷一致; version.txt 恒附带)
SHIP = ("gomoku.py", "start_gomoku.bat", "使用说明.txt")
# 基线里不参与差异比较的文件
BASE_EXCLUDE = ("version.txt", "config.json")
# 基线里跳过的大目录前缀
PREFIX_EXCLUDE = ("pets/", "python/")
ANIMS_REL = "pets/anims"

# 纯 ASCII, 避免中文 Windows 代码页乱码
UPDATE_BAT = """\
@echo off
rem Cumulative update script for chessboard desktop pet
cd /d "%~dp0"
if exist del_list.txt (
  for /f "delims=" %%f in (del_list.txt) do (
    if exist "%%f" del /f /q "%%f"
  )
  del /f /q del_list.txt
)
echo Update OK - files are now up to date.
echo You can delete update.bat and del_list.txt afterwards.
if /i "%~1"=="--quiet" exit /b 0
pause
"""


def load_zip_baseline(zip_path, pkg):
    """读全量 zip 基线: 返回 (代码文件 {relpath: bytes}, 桌宠包 {rel: size})"""
    base, pets = {}, {}
    prefix = pkg + "/"
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            rel = info.filename.replace("\\", "/")
            if not rel.startswith(prefix):
                continue
            rel = rel[len(prefix):]
            if rel.startswith(PREFIX_EXCLUDE):
                if rel.startswith(ANIMS_REL + "/"):
                    pets[rel[len(ANIMS_REL) + 1:]] = info.file_size
                continue
            if rel in BASE_EXCLUDE:
                continue
            base[rel] = zf.read(info)
    return base, pets


def load_dir_baseline(folder, pkg):
    """读 dist/<pkg>/ 文件夹基线(make_installer 的打包源)"""
    base, pets = {}, {}
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if d != "__pycache__"]
        for f in files:
            p = os.path.join(root, f)
            rel = os.path.relpath(p, folder).replace("\\", "/")
            if rel.startswith(PREFIX_EXCLUDE):
                if rel.startswith(ANIMS_REL + "/"):
                    pets[rel[len(ANIMS_REL) + 1:]] = os.path.getsize(p)
                continue
            if rel in BASE_EXCLUDE:
                continue
            with open(p, "rb") as fh:
                base[rel] = fh.read()
    return base, pets


def find_baseline(dist, pkg, explicit):
    """定位基线。返回 (基线版本字符串, 来源描述, 代码 {rel: bytes}, 桌宠 {rel: size})

    优先级: 手动指定 zip > 与最新全量版同版本的 zip > dist/<pkg> 文件夹
    (文件夹是 make_installer 的打包源, 内容即 setup.exe 用户拿到的东西,
     但要求文件夹 version.txt 不高于最新全量版, 防止被更新的 make_dist 刷过)"""
    if explicit:
        if not os.path.isfile(explicit) or not explicit.lower().endswith(".zip"):
            sys.exit(f"[X] --baseline 必须指向一个全量 zip: {explicit}")
        v = parse_ver(os.path.basename(explicit), pkg)
        if v is None:
            sys.exit("[X] 基线文件名里解析不到版本号(应为 <name>_vX.Y.Z_....zip)")
        base, pets = load_zip_baseline(explicit, pkg)
        return ".".join(map(str, v)), f"手动指定 {explicit}", base, pets

    if not os.path.isdir(dist):
        sys.exit(f"[X] 找不到产物目录 {dist}, 先跑 make_dist.py")
    zips, setups = {}, {}
    for f in os.listdir(dist):
        v = parse_ver(f, pkg)
        if v is None or "_update_" in f:  # 补丁不算全量基线
            continue
        if f.endswith(".zip"):
            zips[v] = os.path.join(dist, f)
        elif f.endswith("_setup.exe"):
            setups[v] = os.path.join(dist, f)
    if not zips and not setups:
        sys.exit("[X] dist 里没有任何全量产物(zip/setup.exe), 先跑 make_dist.py --roles all")
    top = max(setups | zips.keys())
    top_s = ".".join(map(str, top))

    if top in zips:  # 最新全量版正好有 zip, 内容最精确
        base, pets = load_zip_baseline(zips[top], pkg)
        return top_s, f"全量 zip {os.path.basename(zips[top])}", base, pets

    folder = os.path.join(dist, pkg)
    fv = folder_version(dist, pkg)
    if os.path.isdir(folder) and (fv is None or fv <= top):
        base, pets = load_dir_baseline(folder, pkg)
        note = "" if fv == top else f"(文件夹 version.txt 是 v{'.'.join(map(str, fv)) if fv else '?'}, 内容即 setup 打包源)"
        return top_s, f"setup.exe v{top_s} 的打包源文件夹 {note}", base, pets

    sys.exit(f"[X] 最新全量版 v{top_s} 没有 zip 也没有可用的打包源文件夹, "
             "先跑 make_dist.py 重新出全量包再打补丁")


def collect_local_pets():
    root = os.path.join(SRC, "pets", "anims")
    m = {}
    if os.path.isdir(root):
        for r, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for f in files:
                p = os.path.join(r, f)
                rel = os.path.relpath(p, root).replace("\\", "/")
                m[rel] = os.path.getsize(p)
    return m


def main():
    ap = argparse.ArgumentParser(description="生成累计式增量更新包")
    ap.add_argument("--out", default=os.path.join(SRC, "dist"))
    ap.add_argument("--name", default="chessboard_desktop_pet")
    ap.add_argument("--baseline", default=None,
                    help="手动指定基线 zip(默认自动取 dist 最新全量产物)")
    args = ap.parse_args()

    # 1. 代码体检: gomoku.py 必须能编译, 不给同事发坏补丁
    import py_compile
    gpy = os.path.join(SRC, "gomoku.py")
    py_compile.compile(gpy, doraise=True)
    print("[OK] gomoku.py 语法检查通过")

    bat = os.path.join(SRC, "start_gomoku.bat")
    if not os.path.isfile(bat):
        sys.exit(f"[X] 找不到 {bat}")

    # 2. 基线(最新全量版内容)
    base_ver, src_desc, base_map, base_pets = find_baseline(
        args.out, args.name, args.baseline)
    print(f"[OK] 基线: 全量版 v{base_ver}  ({src_desc})")

    # 3. 当前代码快照(使用说明.txt 直接复用 make_dist 的 README, 永远同步)
    snap = {
        "gomoku.py": open(gpy, "rb").read(),
        "start_gomoku.bat": open(bat, "rb").read(),
        "使用说明.txt": README.encode("utf-8"),
    }

    # 4. 桌宠包一致性检查(补丁不携带 7GB 视频包)
    local_pets = collect_local_pets()
    pet_new = sorted(set(local_pets) - set(base_pets))
    pet_del = sorted(set(base_pets) - set(local_pets))
    pet_chg = sorted(r for r in set(local_pets) & set(base_pets)
                     if local_pets[r] != base_pets[r])
    if pet_new or pet_del or pet_chg:
        print("[!] 警告: 桌宠包与基线不一致, 补丁带不动视频包, 相关同事需重装全量包!")
        for tag, lst in (("新增", pet_new), ("删除", pet_del), ("改动", pet_chg)):
            if lst:
                print(f"      {tag}: {lst[:3]}{' ...' if len(lst) > 3 else ''}")

    # 5. 累计差异
    changed = [r for r in SHIP if r not in base_map or base_map[r] != snap[r]]
    deleted = sorted(r for r in base_map if r not in snap)
    if not changed and not deleted:
        print(f"[OK] 代码与基线 v{base_ver} 完全一致, 无需补丁")
        sync_latest(args.out, args.name)
        return

    ver = next_version(args.out, args.name)
    os.makedirs(args.out, exist_ok=True)
    now = time.strftime("%Y-%m-%d %H:%M:%S")
    zip_path = os.path.join(
        args.out, f"{args.name}_v{ver}_update_{time.strftime('%Y%m%d')}.zip")

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel in changed:
            zf.writestr(rel, snap[rel])
        zf.writestr(
            "version.txt",
            f"版本: v{ver}\n打包时间: {now}\n基线: 自 v{base_ver} 全量版起的累计更新\n")
        if deleted:
            # cmd 的 for /f 按 ANSI(GBK) 读, 中文文件名要用 GBK 编码
            zf.writestr("del_list.txt",
                        "\n".join(deleted).encode("gbk", "replace") + b"\n")
        zf.writestr("update.bat", UPDATE_BAT)
        zf.writestr("更新说明.txt",
                    f"桌宠五子棋 增量更新包 v{ver}\n"
                    f"{'=' * 32}\n\n"
                    f"适用: 已安装 v{base_ver} 全量版及其后任何版本的用户\n"
                    f"(版本低于 v{base_ver} 的老包请改用最新全量安装包)\n\n"
                    f"更新方法:\n"
                    f"1. 先退出桌宠(右键菜单 -> 退出)\n"
                    f"2. 把压缩包内【所有文件】解压到安装目录, 覆盖同名文件\n"
                    f"   (安装目录 = gomoku.py 所在的那一层,\n"
                    f"    默认 %LOCALAPPDATA%\\Programs\\{args.name})\n"
                    f"3. 双击 update.bat, 看到 Update OK 即完成\n"
                    f"4. update.bat / del_list.txt / 更新说明.txt 用完可删\n"
                    f"5. 双击 start_gomoku.bat 或桌面快捷方式重新启动\n\n"
                    f"本包不含桌宠视频包(pets)和你的配置(config.json),\n"
                    f"昵称/好友/战绩/形象都会原样保留。\n")

    size_mb = os.path.getsize(zip_path) / 1e6
    print(f"[OK] 变更: {'、'.join(changed) or '无'}")
    if deleted:
        print(f"[OK] 删除: {'、'.join(deleted)}")
    print(f"[OK] 更新包: {zip_path}  {size_mb:.2f} MB")
    print(f"[OK] 同事只需把压缩包内容解压覆盖到安装目录, 双击 update.bat 即可")
    # 顺手刷新 dist/latest/, 保证"整夹发同事"的最新全量版也在
    sync_latest(args.out, args.name)


if __name__ == "__main__":
    main()
