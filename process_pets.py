# -*- coding: utf-8 -*-
"""宠物贴纸处理: 白底抠图 -> 最大连通域(去水印/杂点) -> alpha二值化 -> 裁剪缩放"""
import os
import numpy as np
from PIL import Image

RAW_DIR = "pets_raw"
OUT_DIR = "pets"
TARGET_H = 170          # 桌宠显示高度(px)
NEAR_WHITE = 236        # 背景判定阈值

JOBS = [
    ("Q版二头身动漫小男孩贴纸_头部极大身体极小_黑色竖起的刺猬头_2026-11-23T02-52-02.png", "wukong.png"),
    ("Q版二头身动漫小男孩贴纸_头部极大身体极小_深蓝黑色蓬松刺猬_2026-11-23T02-52-18.png", "sasuke.png"),
    ("Q版动漫小女孩贴纸_粉色短发_两个锥形小发髻配白色球形发饰__2026-11-23T02-29-43.png", "anya.png"),
    ("ref_jiangshi.png", "jiangshi.png"),
]


def dilate(mask):
    m = mask.copy()
    m[1:, :] |= mask[:-1, :]
    m[:-1, :] |= mask[1:, :]
    m[:, 1:] |= mask[:, :-1]
    m[:, :-1] |= mask[:, 1:]
    return m


def propagate(seed, allowed, max_iter=4000):
    """从 seed 出发在 allowed 区域内扩散, 返回到达的区域"""
    cur = seed & allowed
    for _ in range(max_iter):
        nxt = dilate(cur) & allowed
        if (nxt == cur).all():
            return cur
        cur = nxt
    return cur


def process(src, dst):
    img = Image.open(src).convert("RGB")
    arr = np.asarray(img)
    h, w = arr.shape[:2]

    # 1. 近白区域(候选背景)
    near_white = (arr >= NEAR_WHITE).all(axis=2)

    # 2. 从图像边缘泛洪: 与边缘连通的近白区域 = 背景
    border = np.zeros((h, w), bool)
    border[0, :] = border[-1, :] = True
    border[:, 0] = border[:, -1] = True
    bg = propagate(border, near_white)

    # 3. 前景 = 非背景; 用中心区域作种子保留最大连通域(去水印/杂点)
    opaque = ~bg
    cy, cx = h // 2, w // 2
    seed = np.zeros((h, w), bool)
    if opaque[cy - 40:cy + 40, cx - 40:cx + 40].any():
        seed[cy - 40:cy + 40, cx - 40:cx + 40] = True
    else:
        ys, xs = np.where(opaque)
        seed[ys[len(ys) // 2], xs[len(xs) // 2]] = True
    main = propagate(seed, opaque)

    # 4. alpha 二值化(防颜色键控黑边), 边缘收 1px 防 Magic 色彩锯齿
    alpha = np.where(main, 255, 0).astype(np.uint8)
    er = main.copy()
    er[1:, :] &= main[:-1, :]
    er[:-1, :] &= main[1:, :]
    er[:, 1:] &= main[:, :-1]
    er[:, :-1] &= main[:, 1:]
    alpha[~er] = 0

    # 5. 裁剪 + 缩放
    ys, xs = np.where(alpha > 0)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    rgba = np.dstack([arr, alpha])[y0:y1, x0:x1]
    out = Image.fromarray(rgba, "RGBA")
    ratio = TARGET_H / out.height
    out = out.resize((max(1, round(out.width * ratio)), TARGET_H), Image.LANCZOS)
    out.save(dst)
    kept = main.sum() / max(1, opaque.sum())
    print(f"{os.path.basename(dst)}: {out.size}, 主体保留率 {kept:.1%}")


os.makedirs(OUT_DIR, exist_ok=True)
for src_name, dst_name in JOBS:
    process(os.path.join(RAW_DIR, src_name), os.path.join(OUT_DIR, dst_name))
print("PROCESS_OK")
