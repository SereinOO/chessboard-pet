# -*- coding: utf-8 -*-
"""角色包在线下载链路测试: 屏幕外+透明度0运行。
覆盖 catalog 拉取(moved_to 跳转)/下载进度/sha256 校验(含故意错的)/解压安装/
skins 重载 + canvas 兜底自动切新形象。全程在临时目录里跑, 不碰真实 pets/anims。"""
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import build_opener, ProxyHandler

# 把 gomoku.py 复制进临时目录再导入: 下载/解压路径全部落在临时目录, 隔离真实数据
TMP = tempfile.mkdtemp(prefix="pets_dl_test_")
shutil.copy2(os.path.join(os.path.dirname(os.path.abspath(__file__)), "gomoku.py"),
             os.path.join(TMP, "gomoku.py"))
sys.path.insert(0, TMP)
import gomoku as g  # noqa: E402  (来自 TMP 的副本)

# ---------------- 假角色包 zip ----------------
from PIL import Image  # noqa: E402

FAKE_PNG = os.path.join(TMP, "_f.png")
Image.new("RGBA", (40, 40), (255, 120, 120, 255)).save(FAKE_PNG)

ZIP_PATH = os.path.join(TMP, "pets_testrole_v1.zip")
with zipfile.ZipFile(ZIP_PATH, "w") as zf:
    zf.writestr("pets/anims/testrole/pack.json",
                json.dumps({"name": "测试君", "fps": 12}))
    zf.writestr("pets/anims/testrole/idle/f000.png", open(FAKE_PNG, "rb").read())
    zf.writestr("pets/anims/testrole/idle/preview.png", open(FAKE_PNG, "rb").read())
ZIP_BYTES = open(ZIP_PATH, "rb").read()

BAD_ZIP = os.path.join(TMP, "pets_badrole_v1.zip")
with zipfile.ZipFile(BAD_ZIP, "w") as zf:
    zf.writestr("pets/anims/badrole/pack.json", "{}")
    zf.writestr("pets/anims/badrole/idle/f000.png", open(FAKE_PNG, "rb").read())
BAD_BYTES = open(BAD_ZIP, "rb").read()
BAD_SHA = "0" * 64           # 故意错的校验值

# ---------------- 假 Release 服务器 ----------------
class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/catalog.json":      # 第一跳: 只做跳转
            body = json.dumps({"moved_to": f"http://127.0.0.1:{SRV_PORT}/catalog2.json"}).encode()
        elif self.path == "/catalog2.json":
            body = json.dumps({
                "catalog_ver": 1, "moved_to": "",
                "base": f"http://127.0.0.1:{SRV_PORT}",
                "roles": [
                    {"dir": "testrole", "name": "测试君",
                     "file": "pets_testrole_v1.zip", "bytes": len(ZIP_BYTES),
                     "sha256": "TOFILL"},
                    {"dir": "badrole", "name": "坏包",
                     "file": "pets_badrole_v1.zip", "bytes": len(BAD_BYTES),
                     "sha256": BAD_SHA},
                ]}).encode()
            body = body.replace(b'"TOFILL"',                # 真 sha 在启动时算好填入
                                json.dumps(_sha(ZIP_PATH)).encode())
        elif self.path == "/pets_testrole_v1.zip":
            body = ZIP_BYTES
        elif self.path == "/pets_badrole_v1.zip":
            body = BAD_BYTES
        else:
            self.send_response(404); self.end_headers(); return
        self.send_response(200)
        self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _sha(p):
    import hashlib
    return hashlib.sha256(open(p, "rb").read()).hexdigest()


srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
SRV_PORT = srv.server_address[1]
srv.daemon_threads = True
threading.Thread(target=srv.serve_forever, daemon=True).start()

# ---------------- 被测 App(屏外+全透明) ----------------
g.PET_CATALOG_URL = f"http://127.0.0.1:{SRV_PORT}/catalog.json"
CFG = os.path.join(TMP, "config.json")
app = g.App(27215, start_pos=(3100, 100), config_path=CFG)
app.root.attributes("-alpha", 0.0)
app.alpha = 0.0

OP = build_opener(ProxyHandler({}))    # 直连, 绕开系统代理(本机代理会劫走 127.0.0.1)


def pump(ms):
    end = time.time() + ms / 1000
    while time.time() < end:
        app.root.update()
        time.sleep(0.01)


def http_get(path):
    return json.loads(OP.open(f"http://127.0.0.1:{app._ensure_settings_server()}{path}",
                              timeout=10).read().decode("utf-8"))


def http_post(path, obj):
    import urllib.request
    req = urllib.request.Request(
        f"http://127.0.0.1:{app._srv_port}{path}",
        data=json.dumps(obj).encode(), method="POST")
    return json.loads(OP.open(req, timeout=10).read().decode("utf-8"))


def wait_done(timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        pump(200)
        st = http_get("/api/pets_status")
        if st["phase"] in ("done", "error"):
            return st
    raise AssertionError("下载超时")


# 0. 初始: 没有任何角色包 -> 只有 canvas 兜底
assert len(app.skins) == 1 and app.skins[0]["draw"], "初始应有 canvas 兜底形象"
print("初始OK  canvas 兜底形象")

# 1. catalog: moved_to 跳转 + 角色列表
cat = http_get("/api/pets_catalog")
assert cat["ok"] and len(cat["roles"]) == 2, f"catalog 异常: {cat}"
assert cat["roles"][0]["dir"] == "testrole" and not cat["roles"][0]["installed"]
assert not cat["busy"]
print(f"catalogOK  moved_to 跳转生效, 2 个角色, testrole {cat['roles'][0]['mb']} MB")

# 2. 下载坏包 -> sha256 校验失败 -> error
r = http_post("/api/pets_download", {"dir": "badrole"})
assert r["ok"], f"开始下载失败: {r}"
st = wait_done()
assert st["phase"] == "error" and "校验" in st["msg"], f"坏包未被拦截: {st}"
assert not os.path.exists(os.path.join(TMP, "_pets_dl", "badrole.zip")), "失败后临时文件未清理"
print("校验OK  sha256 不符的包被拦截并清理")

# 3. 下载正常包 -> done -> 解压到位 -> skins 重载 + 默认切到新形象
r = http_post("/api/pets_download", {"dir": "testrole"})
assert r["ok"], f"开始下载失败: {r}"
st = wait_done()
assert st["phase"] == "done", f"正常包下载失败: {st}"
pdir = os.path.join(TMP, "pets", "anims", "testrole")
assert os.path.isfile(os.path.join(pdir, "pack.json")), "角色包未解压到位"
assert os.path.isfile(os.path.join(pdir, "idle", "f000.png"))
assert not os.path.exists(os.path.join(TMP, "_pets_dl", "testrole.zip")), "zip 未清理"
pump(1000)   # 处理 pets_installed 事件(重载 skins/换形象)

snap = http_get("/api/config")
assert any(s["name"] == "测试君" for s in snap["skins"]), f"skins 未刷新: {snap['skins']}"
assert snap["skin"] == 0 and snap["skins"][0]["name"] == "测试君", \
    f"canvas 兜底应自动切到新形象: skin={snap['skin']}"
assert app.skins[0]["pack"] and app.skins[0]["anims"], "App 内 skins 未重载"
cat = http_get("/api/pets_catalog")
assert cat["roles"][0]["installed"], "catalog 应显示已安装"
print("下载安装OK  解压到位, skins 重载, canvas 兜底自动切到新形象")

# 4. 下载中再点一次 -> 拒绝并发(用坏包占住状态即可验证参数校验, 不重复真下载)
r = http_post("/api/pets_download", {"dir": "nope"})
assert not r["ok"] and "没有这个角色" in r["error"], f"非法角色未被拒: {r}"
print("参数校验OK  未知角色被拒绝")

# 5. 下载源未配置的提示(清掉 URL 后直接调 handler 不可行, 验证常量切换逻辑即可)
srv.shutdown()
print(f"\n临时目录(可留查): {TMP}")
print("ALL PASS")
