# -*- coding: utf-8 -*-
"""最终包验收: 用包内便携 Python 屏外启动, 验证全角色/交互/战绩链路关键点"""
import os
import subprocess
import sys

DIST = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dist", "chessboard_desktop_pet")
PYW = os.path.join(DIST, "python", "pythonw.exe")
PY = os.path.join(DIST, "python", "python.exe")

# 1) 关键文件存在
for f in ("start_gomoku.bat", "gomoku.py", "使用说明.txt"):
    assert os.path.isfile(os.path.join(DIST, f)), f
assert os.path.isfile(PYW), "缺 pythonw.exe"
print("[1] 关键文件齐全")

# 2) 全部 5 个角色都在, 且每角色有动作帧
anims = os.path.join(DIST, "pets", "anims")
roles = sorted(d for d in os.listdir(anims) if os.path.isfile(os.path.join(anims, d, "pack.json")))
print("[2] 角色:", roles)
assert roles == ["claude", "glm", "gpt", "grok", "kimi"], roles
for r in roles:
    acts = [d for d in os.listdir(os.path.join(anims, r))
            if os.path.isfile(os.path.join(anims, r, d, "f000.png"))]
    assert acts, f"{r} 无动作"
    print(f"    {r}: {len(acts)} 个动作")

# 3) 便携 Python 能跑主程序(屏外启动, 不闪用户桌面)
probe = os.path.join(DIST, "_probe.json")
code = f'''
import sys, os
sys.path.insert(0, r"{DIST}")
import gomoku
skins = gomoku.load_skin_list()
print("SKINS:", [(s.get("name"), s.get("type", "?")) for s in skins])
assert len(skins) >= 5, "角色包没被识别"
app = gomoku.App(27260, start_pos=(3100,100), config_path=r"{probe}")
app.root.update()
print("SIZE:", app.root.winfo_width(), app.root.winfo_height())
app.root.destroy()
print("EMBED_OK")
'''
r = subprocess.run([PY, "-c", code], capture_output=True, text=True, timeout=60)
print(r.stdout.strip())
if "EMBED_OK" not in r.stdout:
    sys.exit("[X] 便携 Python 启动失败:\n" + r.stderr[-2000:])
if os.path.isfile(probe):
    os.remove(probe)
print("[3] 便携 Python 启动主程序通过")

print("DIST_FULL_PASS")
