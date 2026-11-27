# -*- coding: utf-8 -*-
"""
角色包发布工具 —— 把 pets/anims 下的角色打包上传 GitHub Release, 供精简安装包在线下载

用法:
    python make_pet_release.py                       # 只打包到 _petrelease/, 不上传
    python make_pet_release.py --upload              # 打包 + 上传到 GitHub Release(需 gh 登录)
    python make_pet_release.py --repo 用户名/仓库名   # 指定 GitHub 仓库(默认读 _petrepo.txt 或询问)
    python make_pet_release.py --roles claude,kimi   # 只发指定角色
    python make_pet_release.py --bump-major          # tag 升一位(pets-v1 -> pets-v2)

流程:
    1. 逐角色打 zip(STORED, zip 内路径 pets/anims/<角色>/..., 解压即到位),
       每个都 < 2GiB(GitHub Release 单文件上限, 本项目最大 claude 1.93GiB)
    2. 生成 catalog.json(base 下载地址 + 每角色 file/bytes/sha256)
    3. gh release create pets-vN 上传 catalog.json + 各角色 zip
    4. 打印需要填回 gomoku.py 的 PET_CATALOG_URL, 并尝试自动写回 gomoku.py

旧版本跟进机制: 发布 pets-v2 后, 若要通知还在 pets-v1 的用户, 用 --move-old
把旧 catalog.json 改成 {"moved_to": 新地址} 重新上传到旧 Release(覆盖旧资产)。
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import zipfile

SRC = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SRC)
from make_dist import available_roles, clear_dir  # noqa: E402

ANIMS = os.path.join(SRC, "pets", "anims")
OUT_DIR = os.path.join(SRC, "_petrelease")
REPO_FILE = os.path.join(SRC, "_petrepo.txt")     # 记住仓库, 下次不用再输
GHFAST = "https://ghfast.top/https://github.com"  # 国内加速镜像


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def dir_size(path):
    t = 0
    for rt, _d, fs in os.walk(path):
        for f in fs:
            t += os.path.getsize(os.path.join(rt, f))
    return t


def pack_display_name(role_dir):
    """设置页显示名: pack.json 里的 name 优先"""
    try:
        with open(os.path.join(ANIMS, role_dir, "pack.json"), encoding="utf-8") as f:
            meta = json.load(f)
        if meta.get("name"):
            return str(meta["name"])
    except Exception:
        pass
    return role_dir


def latest_pets_tag(repo):
    """现有最大的 pets-vN tag, 没有则从 v1 开始"""
    r = subprocess.run(["gh", "release", "list", "--repo", repo,
                        "--limit", "100", "--json", "tagName"],
                       capture_output=True, text=True)
    tags = re.findall(r"pets-v(\d+)", r.stdout or "")
    return f"pets-v{max(int(x) for x in tags) + 1}" if tags else "pets-v1"


def build_packages(roles, tag):
    """逐角色 zip + catalog.json -> _petrelease/; 返回 catalog dict"""
    clear_dir(OUT_DIR)
    os.makedirs(OUT_DIR)
    roles_meta = []
    for r in roles:
        src = os.path.join(ANIMS, r)
        print(f"[..] 打包角色 {r} ...")
        zip_path = os.path.join(OUT_DIR,
                                f"pets_{r}_v{tag.rsplit('v', 1)[-1]}.zip")
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED) as zf:
            for rt, _d, fs in os.walk(src):
                for f in fs:
                    p = os.path.join(rt, f)
                    zf.write(p, os.path.relpath(p, SRC).replace("\\", "/"))
        size = os.path.getsize(zip_path)
        if size > 2 * 1024**3:
            sys.exit(f"[X] {r} 的 zip 超过 GitHub 2GiB 单文件上限: {size} 字节")
        sha = sha256_file(zip_path)
        print(f"[OK] {zip_path}  {size/1e9:.2f} GB  sha256={sha[:12]}…")
        roles_meta.append({"dir": r, "name": pack_display_name(r),
                           "file": os.path.basename(zip_path),
                           "bytes": size, "sha256": sha})
    catalog = {"catalog_ver": 1, "moved_to": "",
               "base": "",                 # 上传后按真实 repo 回填
               "roles": roles_meta}
    cat_path = os.path.join(OUT_DIR, "catalog.json")
    with open(cat_path, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=1)
    return catalog, cat_path


def main():
    ap = argparse.ArgumentParser(description="发布角色包到 GitHub Release")
    ap.add_argument("--roles", default="all", help="all 或逗号分隔角色名")
    ap.add_argument("--upload", action="store_true", help="上传(需 gh auth login 过)")
    ap.add_argument("--repo", default=None, help="GitHub 仓库, 如 yourname/chessboard-pets")
    ap.add_argument("--tag", default=None, help="Release tag, 默认自动 pets-vN+1")
    ap.add_argument("--move-old", dest="move_old", metavar="OLDTAG",
                    help="把旧 tag 的 catalog.json 改为跳到本次新地址(通知老用户)")
    args = ap.parse_args()

    roles_all = available_roles()
    if args.roles.strip().lower() == "all":
        roles = roles_all
    else:
        roles = [r.strip() for r in args.roles.split(",") if r.strip()]
        bad = [r for r in roles if r not in roles_all]
        if bad:
            sys.exit(f"[X] 不存在的角色: {bad}  可选: {roles_all}")
    if not roles:
        sys.exit("[X] pets/anims 下没有任何角色包(python import_anims.py 先导入)")

    repo = args.repo
    if args.upload:
        if not repo and os.path.isfile(REPO_FILE):
            repo = open(REPO_FILE, encoding="utf-8").read().strip()
        if not repo:
            repo = input("GitHub 仓库(如 yourname/chessboard-pets): ").strip()
            with open(REPO_FILE, "w", encoding="utf-8") as f:
                f.write(repo)
        chk = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True)
        if chk.returncode != 0:
            sys.exit("[X] gh 未登录, 先在终端运行: gh auth login")

    tag = args.tag or (latest_pets_tag(repo) if args.upload else "pets-v1")
    catalog, cat_path = build_packages(roles, tag)

    if not args.upload:
        print(f"\n[OK] 已打包到 {OUT_DIR} (未上传)")
        print("[i] 确认无误后加 --upload 上传")
        return

    print(f"[..] 上传到 {repo} @{tag} ...")
    notes = (f"角色包 {tag}\n\n角色: {', '.join(r['dir'] for r in catalog['roles'])}\n"
             "供精简安装包在设置页在线下载; 手动下载单个 zip 解压到安装目录也可。")
    cmd = ["gh", "release", "create", tag, "--repo", repo,
           "--title", f"角色包 {tag}", "--notes", notes]
    # 先传 catalog 前要回填 base, 否则下载端拿不到地址; 但 base 含 tag, tag 已定, 直接回填
    base = f"{GHFAST}/{repo}/releases/download/{tag}"
    catalog["base"] = base
    with open(cat_path, "w", encoding="utf-8") as f:
        json.dump(catalog, f, ensure_ascii=False, indent=1)
    cmd += [os.path.join(OUT_DIR, r["file"]) for r in catalog["roles"]] + [cat_path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"[X] 上传失败:\n{r.stdout[-800:]}\n{r.stderr[-800:]}")
    rel_url = r.stdout.strip() or f"https://github.com/{repo}/releases/tag/{tag}"
    print(f"[OK] 发布完成: {rel_url}")

    catalog_url = f"{base}/catalog.json"
    print(f"\n>>> 把这一行填进 gomoku.py:")
    print(f'    PET_CATALOG_URL = "{catalog_url}"')
    # 自动写回 gomoku.py(已填过别的地址则替换; 没填过则提醒)
    gpath = os.path.join(SRC, "gomoku.py")
    src_code = open(gpath, encoding="utf-8").read()
    if 'PET_CATALOG_URL = "' in src_code:
        new_code = re.sub(r'PET_CATALOG_URL = "[^"]*"',
                          f'PET_CATALOG_URL = "{catalog_url}"', src_code, count=1)
        if new_code != src_code:
            open(gpath, "w", encoding="utf-8").write(new_code)
            print("[OK] 已自动写回 gomoku.py 的 PET_CATALOG_URL")
    # 通知老版本: 旧 tag 的 catalog.json 替换为 moved_to 跳转(覆盖上传, 资产名必须仍叫 catalog.json)
    if args.move_old:
        mv_dir = os.path.join(OUT_DIR, "_old")
        os.makedirs(mv_dir, exist_ok=True)
        old_cat = os.path.join(mv_dir, "catalog.json")
        with open(old_cat, "w", encoding="utf-8") as f:
            json.dump({"moved_to": catalog_url}, f, ensure_ascii=False)
        rr = subprocess.run(["gh", "release", "upload", args.move_old, "--repo",
                             repo, "--clobber", old_cat],
                            capture_output=True, text=True)
        if rr.returncode == 0:
            print(f"[OK] 旧目录 {args.move_old} 的 catalog 已指向新地址")
        else:
            print(f"[!] 旧目录跳转写入失败: {rr.stderr[-300:]}")


if __name__ == "__main__":
    main()
