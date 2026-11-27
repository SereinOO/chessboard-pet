# -*- coding: utf-8 -*-
"""
大肥鱼桌宠资源导入器 —— 把透明 webm 人物动画抽帧为本项目桌宠可用的 PNG 序列

资源来源: 大肥鱼桌宠安装后解压在
    %APPDATA%/dafeiyu-desktop-pet/characters/<角色>/animations/*.webm
    (manifest.json 注明协议: CC BY-NC-SA 4.0, 立绘 lokicorvus/crosspet, 仅限非商业个人使用)

用法 (在项目目录, 用 D:/Python/python.exe):
    python import_anims.py                          # 按内置精选列表导入 claude 包
    python import_anims.py --char claude --anims 下五子棋 写代码   # 指定动作
    python import_anims.py --char glm --list        # 只列出可用动作
    python import_anims.py --char glm --anims ...   # 导入其他角色包

输出:
    pets/anims/<角色>/<动作名>/f000.png ... f119.png + preview.png
    每个动作各自裁剪人物包围盒(带余量), 原生分辨率导出(上限 400x440 不放大),
    alpha>=128 二值化(与 process_pets.py 一致, 防止 transparentcolor 抠图黑边)

为什么不再用全动作并集裁剪: 部分动作人物会移遍整个 640x360 画面,
并集≈整幅画面, 统一缩到 176x99 后人物只有 ~80px 高, 细节全丢(对比原版明显发糊);
改为逐动作裁剪后人物保持 ~300px 源细节, 桌宠端任意 pet_scale 都是缩小渲染, 清晰。
旧分辨率帧库需要 --force 重导出。
"""
import argparse
import json
import os
import subprocess
import sys

from PIL import Image

# 每动作导出上限(只缩不放大): 源画面 640x360, 人物约占 300x330
MAX_W, MAX_H = 400, 440
PAD = 8                          # 包围盒余量(px, 1/4 缩采样误差补偿)
ALPHA_TH = 128                    # alpha 二值化阈值
DEFAULT_ANIMS = [                 # 精选动作(摸鱼场景): 待机为主 + 互动彩蛋
    "待机呼吸休闲",
    "原地小憩沉眠",
    "下五子棋",
    "写代码",
    "工作状态-思考冒泡",
    "工作状态-雀跃庆祝",
    "点击回应-元气挥手",
    "点击回应-傲娇生气",
    "吃Token",
    "撸猫",
    "哈欠连天",
    "超大伸懒腰",
    "被吓一跳",
    "碎碎念-对屏碎碎念",
]

def find_ffmpeg():
    """优先用 imageio_ffmpeg 自带的静态 ffmpeg, 找不到再试 PATH"""
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        pass
    from shutil import which
    p = which("ffmpeg")
    if p:
        return p
    raise SystemExit("找不到 ffmpeg: 请先 pip install imageio-ffmpeg")


def decode_frames(ffmpeg, webm):
    """libvpx-vp9 解码(带 alpha), 管道输出 bgra 原始帧, 逐帧交给回调"""
    cmd = [ffmpeg, "-v", "error", "-c:v", "libvpx-vp9", "-i", webm,
           "-f", "rawvideo", "-pix_fmt", "bgra", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL)
    W, H, BPP = 640, 360, 4
    size = W * H * BPP
    frames = []
    while True:
        buf = proc.stdout.read(size)
        if len(buf) < size:
            break
        img = Image.frombytes("RGBA", (W, H), buf, "raw", "BGRA")
        frames.append(img)
    proc.wait()
    return frames


def alpha_bbox(img):
    """alpha 缩到 1/4 算包围盒(提速), 返回 (l, t, r, b) 或 None"""
    small = img.resize((img.width // 4, img.height // 4), Image.BILINEAR)
    return small.getchannel("A").getbbox()


def union_bbox(frames):
    box = None
    for f in frames[::2]:                      # 隔帧采样足够
        b = alpha_bbox(f)
        if b is None:
            continue
        box = b if box is None else (
            min(box[0], b[0]), min(box[1], b[1]),
            max(box[2], b[2]), max(box[3], b[3]))
    if box is None:
        return (0, 0, frames[0].width, frames[0].height)
    return tuple(v * 4 for v in box)           # 还原到全分辨率


def fit_size(w, h):
    s = min(MAX_W / w, MAX_H / h, 1.0)         # 只缩不放大
    return max(1, int(w * s)), max(1, int(h * s))


def import_pack(char, anim_names, src_root, out_root, ffmpeg, force=False):
    pack_src = os.path.join(src_root, char)
    manifest = os.path.join(pack_src, "manifest.json")
    with open(manifest, encoding="utf-8") as f:
        mf = json.load(f)
    by_id = {a["id"]: a for a in mf["actions"]}

    if anim_names == "--list":
        for a in mf["actions"]:
            print(f"{a['category']:6s} {a['id']}  ({a['frames']}帧)")
        return
    if anim_names is None:                    # --all: 全量导入
        anim_names = [a["id"] for a in mf["actions"]]
    missing = [n for n in anim_names if n not in by_id]
    if missing:
        print(f"!! 包里没有这些动作, 已跳过: {missing}")
        anim_names = [n for n in anim_names if n in by_id]
    if not anim_names:
        raise SystemExit("没有可导入的动作")

    out_pack = os.path.join(out_root, char)
    os.makedirs(out_pack, exist_ok=True)
    with open(os.path.join(out_pack, "pack.json"), "w", encoding="utf-8") as f:
        json.dump({"name": mf.get("name", char).replace("动作包", "").strip() or char,
                   "fps": 12}, f, ensure_ascii=False)

    # 增量: 已完整导出的动作(f末帧存在)跳过抽帧; --force 强制重导
    def done(name):
        adir = os.path.join(out_pack, name)
        return os.path.exists(os.path.join(adir, f"f{by_id[name]['frames'] - 1:03d}.png"))

    todo = [n for n in anim_names if force or not done(n)]
    skipped = len(anim_names) - len(todo)
    if skipped:
        print(f"增量模式: 跳过已完成 {skipped} 个, 待导入 {len(todo)} 个")
    if not todo:
        print("全部已导入, 无需操作 (旧分辨率重导请加 --force)")
        return

    # 逐动作导出: 每个动作各自裁剪人物包围盒, 原生分辨率导出(只缩不放大)
    total = 0
    for name in todo:
        frames = decode_frames(ffmpeg, os.path.join(pack_src, by_id[name]["file"]))
        adir = os.path.join(out_pack, name)
        os.makedirs(adir, exist_ok=True)
        FW, FH = frames[0].size
        box = union_bbox(frames)
        box = (max(0, box[0] - PAD), max(0, box[1] - PAD),
               min(FW, box[2] + PAD), min(FH, box[3] + PAD))
        cw, ch = box[2] - box[0], box[3] - box[1]
        dw, dh = fit_size(cw, ch)
        shrink = (dw, dh) != (cw, ch)
        for i, f in enumerate(frames):
            fr = f.crop(box)
            if shrink:
                fr = fr.resize((dw, dh), Image.LANCZOS)
            a = fr.getchannel("A").point(lambda v: 255 if v >= ALPHA_TH else 0)
            fr.putalpha(a)
            fr.save(os.path.join(adir, f"f{i:03d}.png"))
        pv = frames[0].crop(box)
        if shrink:
            pv = pv.resize((dw, dh), Image.LANCZOS)
        pv.save(os.path.join(adir, "preview.png"))
        meta = {"name": name, "fps": by_id[name].get("fps", 12),
                "frames": len(frames), "size": [dw, dh]}
        with open(os.path.join(adir, "anims.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)
        total += len(frames)
        print(f"  [ok] {name}: {len(frames)}帧 裁剪{box} -> {dw}x{dh}")
        del frames
    print(f"完成: {len(todo)} 个动作, 共 {total} 帧 -> {out_pack}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--char", default="claude", help="角色目录名: claude/glm/gpt/grok/kimi")
    ap.add_argument("--anims", nargs="*", default=DEFAULT_ANIMS,
                    help="动作名列表; 用 --anims --list 查看全部")
    ap.add_argument("--all", action="store_true", help="导入该角色全部动作")
    ap.add_argument("--force", action="store_true",
                    help="已完成的动作也重导(旧 176x99 分辨率帧库升级用)")
    ap.add_argument("--src", default=os.path.expandvars(
        r"%APPDATA%/dafeiyu-desktop-pet/characters"))
    ap.add_argument("--out", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "pets", "anims"))
    args = ap.parse_args()
    ffmpeg = find_ffmpeg()
    import_pack(args.char, "--list" if args.anims == ["--list"] else
                (None if args.all else args.anims),
                args.src, args.out, ffmpeg, args.force)


if __name__ == "__main__":
    main()
