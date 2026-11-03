#!/usr/bin/env python3
"""KuKuTool (dy.kukutool.com) pure-HTTP parse + local download.

Usage:
  python3 download.py "https://weixin.qq.com/sph/..."
  python3 download.py "URL" --out ~/Downloads/kukutool --audio
  python3 download.py "URL" --json-only
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.parse
from pathlib import Path

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives import padding
except ImportError:
    print("缺少 cryptography，请执行: pip3 install cryptography", file=sys.stderr)
    sys.exit(1)

BASE = "https://dy.kukutool.com"
UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
DECRYPT_KEY = "12345678901234567890123456789013"
FALLBACK_PROFILE = {
    "id": "2026060303",
    "authRoute": "auth-9e25f1",
    "authResponseFields": {"key": "k_9e25f1", "seed": "s_9e25f1"},
    "parseRequestFields": {
        "key": "k_9e25f1",
        "payload": "p_9e25f1",
        "iv": "i_9e25f1",
        "version": "r_9e25f1",
    },
}


def curl(
    method: str,
    url: str,
    data: dict | None = None,
    cookie_jar: str | None = None,
    out_file: str | None = None,
    extra_headers: list[str] | None = None,
) -> tuple[int, bytes]:
    cmd = [
        "curl",
        "-sS",
        "-L",
        "-X",
        method,
        "-A",
        UA,
        "-H",
        "Accept: application/json, text/plain, */*",
        "-H",
        f"Origin: {BASE}",
        "-H",
        f"Referer: {BASE}/",
        "-H",
        "Accept-Language: zh-CN,zh;q=0.9",
        "-w",
        "\n__HTTP_STATUS__:%{http_code}",
    ]
    if cookie_jar:
        cmd += ["-c", cookie_jar, "-b", cookie_jar]
    if extra_headers:
        for h in extra_headers:
            cmd += ["-H", h]
    body_file = None
    if data is not None:
        body_file = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        body_file.write(json.dumps(data, ensure_ascii=False).encode())
        body_file.close()
        cmd += ["-H", "Content-Type: application/json", "--data-binary", f"@{body_file.name}"]
    if out_file:
        # write body to file; status still on stdout via -w after body... use -o + -w on stderr-ish.
        # Simpler: download separately without status in body.
        pass
    cmd.append(url)
    try:
        out = subprocess.check_output(cmd)
    finally:
        if body_file is not None:
            os.unlink(body_file.name)
    if b"__HTTP_STATUS__:" not in out:
        return 0, out
    body, st = out.rsplit(b"__HTTP_STATUS__:", 1)
    return int(st.strip()), body


def download_referer(url: str) -> str | None:
    """CDN hosts often reject kukutool Referer (XHS returns 403)."""
    host = urllib.parse.urlparse(url).netloc.lower()
    if "xhscdn.com" in host or "xiaohongshu.com" in host or "rednote.com" in host:
        return "https://www.xiaohongshu.com/"
    if "douyin" in host or "byteimg" in host or "tiktokcdn" in host:
        return "https://www.douyin.com/"
    return f"{BASE}/"


def curl_download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "curl",
        "-sSL",
        "-A",
        UA,
        "--fail",
        "--max-time",
        "300",
        "-o",
        str(dest),
        url,
    ]
    ref = download_referer(url)
    if ref:
        # Insert after UA args: curl -sSL -A UA -H Referer ...
        cmd[4:4] = ["-H", f"Referer: {ref}"]
    subprocess.check_call(cmd)


def discover_profile(cookie_jar: str) -> dict:
    """Load active auth profile from frontend chunk; fall back to known profile."""
    st, html = curl("GET", f"{BASE}/", cookie_jar=cookie_jar)
    if st != 200:
        return FALLBACK_PROFILE
    text = html.decode("utf-8", "ignore")
    chunks = re.findall(r"/_next/static/chunks/([0-9]+-[a-f0-9]+\.js)", text)
    # Prefer the chunk that historically embeds the profile JSON.
    candidates = [c for c in chunks if c.startswith("9802-")] + chunks
    for name in candidates[:12]:
        st, js = curl("GET", f"{BASE}/_next/static/chunks/{name}", cookie_jar=cookie_jar)
        if st != 200:
            continue
        m = re.search(
            r"JSON\.parse\('(\{\"activeProfileId\":.*?\})'\)",
            js.decode("utf-8", "ignore"),
        )
        if not m:
            continue
        try:
            cfg = json.loads(m.group(1))
            active = cfg.get("activeProfileId")
            for p in cfg.get("profiles") or []:
                if p.get("id") == active:
                    return p
            if cfg.get("profiles"):
                return cfg["profiles"][0]
        except json.JSONDecodeError:
            continue
    return FALLBACK_PROFILE


def remap_b64(s: str) -> str:
    src = "ZYXABCDEFGHIJKLMNOPQRSTUVWzyxabcdefghijklmnopqrstuvw9876543210-_"
    dst = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    return "".join(dst[src.index(ch)] if ch in src else ch for ch in s)


def rev8(s: str, n: int = 8) -> str:
    return "".join(s[i : i + n][::-1] for i in range(0, len(s), n))


def xor90(s: str, t: int = 90) -> str:
    return "".join(chr(ord(c) ^ t) for c in s)


def kukudemethod(data: str, iv: str, key: str = DECRYPT_KEY) -> dict:
    d = remap_b64(rev8(xor90(data)))
    p = remap_b64(rev8(xor90(iv)))
    ct = base64.b64decode(d)
    ivb = base64.b64decode(p)
    keyb = hashlib.sha256(key.encode()).digest()
    cipher = Cipher(algorithms.AES(keyb), modes.CBC(ivb))
    dec = cipher.decryptor()
    pt = dec.update(ct) + dec.finalize()
    unpad = padding.PKCS7(128).unpadder()
    pt = unpad.update(pt) + unpad.finalize()
    return json.loads(pt.decode())


def encrypt_params(params: dict, auth_key: str, auth_seed: str, profile: dict) -> dict:
    key = hashlib.sha256(f"{auth_key}:{auth_seed}".encode()).digest()
    iv = os.urandom(12)
    ct = AESGCM(key).encrypt(iv, json.dumps(params, ensure_ascii=False).encode(), None)
    pf = profile["parseRequestFields"]
    return {
        "version": 3,
        pf["key"]: auth_key,
        pf["payload"]: base64.b64encode(ct).decode(),
        pf["version"]: 1,
        pf["iv"]: base64.b64encode(iv).decode(),
    }


def extract_first_url(text: str) -> str:
    m = re.search(r"https?://[^\s\"'<>]+", text)
    if not m:
        raise ValueError("未找到有效链接")
    return m.group(0).rstrip(")。,.，")


def parse_media(share_url: str) -> dict:
    with tempfile.TemporaryDirectory() as td:
        jar = str(Path(td) / "cookies.txt")
        Path(jar).write_text("")
        curl("GET", f"{BASE}/", cookie_jar=jar)
        profile = discover_profile(jar)
        auth_body = {"requestURL": share_url, "pagePath": "/", "mode": "single"}
        st, raw = curl(
            "POST",
            f"{BASE}/api/{profile['authRoute']}",
            data=auth_body,
            cookie_jar=jar,
        )
        if st != 200:
            raise RuntimeError(f"auth 失败 HTTP {st}: {raw[:300]!r}")
        auth = json.loads(raw.decode())
        af = profile["authResponseFields"]
        auth_key = auth.get(af["key"]) or auth.get("authKey")
        auth_seed = auth.get(af["seed"]) or auth.get("authSeed")
        if not auth_key or not auth_seed:
            raise RuntimeError(f"auth 响应缺少密钥字段: {list(auth.keys())}")

        params = {
            "requestURL": share_url,
            "captchaKey": "",
            "captchaInput": "",
            "totalSuccessCount": "0",
            "successCount": "0",
            "firstSuccessDate": "",
            "pagePath": "/",
            "uwx_id": "",
            "isMobile": "false",
            "geoipIp": "",
        }
        body = encrypt_params(params, auth_key, auth_seed, profile)
        st, raw = curl("POST", f"{BASE}/api/parse", data=body, cookie_jar=jar)
        if st != 200:
            raise RuntimeError(f"parse 失败 HTTP {st}: {raw[:400]!r}")
        resp = json.loads(raw.decode("utf-8", "surrogateescape"))
        if resp.get("status") != 0:
            raise RuntimeError(f"parse 业务失败: {json.dumps(resp, ensure_ascii=False)[:800]}")
        data = resp.get("data")
        if resp.get("encrypt"):
            data = kukudemethod(resp["data"], resp["iv"])
        if not isinstance(data, dict):
            raise RuntimeError(f"无法解析媒体数据: {type(data)}")
        return data


def sanitize_filename(name: str, fallback: str = "media") -> str:
    name = re.sub(r"[\\/:*?\"<>|\n\r\t]+", "_", name).strip(" ._")
    return (name[:80] or fallback)


def _quality_score(info: dict) -> tuple[int, int]:
    """Prefer 超高清/原画, then larger size. `url`/`videos[].url` is often 正常档."""
    t = str(info.get("type") or "")
    try:
        size = int(info.get("size") or 0)
    except (TypeError, ValueError):
        size = 0
    rank = 0
    if any(k in t for k in ("超高清", "原画", "4K", "4k")):
        rank = 3
    elif "高清" in t or "1080" in t:
        rank = 2
    elif t:
        rank = 1
    return (rank, size)


def pick_video_url(data: dict) -> str | None:
    cands: list[dict] = []
    for v in data.get("videos") or []:
        if isinstance(v, dict):
            infos = v.get("video_fullinfo") or []
            if infos:
                for info in infos:
                    if isinstance(info, dict) and info.get("url"):
                        cands.append(info)
            elif v.get("url"):
                cands.append(v)
        elif isinstance(v, str) and v:
            cands.append({"url": v, "type": "", "size": 0})
    if cands:
        best = max(cands, key=_quality_score)
        return best.get("url")
    return data.get("url") or None


def extract_audio(video_path: Path, audio_path: Path) -> Path:
    audio_path.parent.mkdir(parents=True, exist_ok=True)
    # Prefer stream copy for AAC; fall back to re-encode.
    try:
        subprocess.check_call(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(video_path),
                "-vn",
                "-acodec",
                "copy",
                str(audio_path),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        audio_path = audio_path.with_suffix(".m4a")
        subprocess.check_call(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(video_path),
                "-vn",
                "-acodec",
                "aac",
                str(audio_path),
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    return audio_path


def main() -> int:
    ap = argparse.ArgumentParser(description="KuKuTool 纯请求解析并本地下载")
    ap.add_argument("url", help="分享链接或含链接的文本")
    ap.add_argument("--out", default=str(Path.home() / "Downloads" / "kukutool"), help="输出目录")
    ap.add_argument("--audio", action="store_true", help="额外用 ffmpeg 从视频抽出音频")
    ap.add_argument("--video-only", action="store_true", help="只下载视频")
    ap.add_argument("--audio-only", action="store_true", help="下载视频后只保留音频")
    ap.add_argument("--json-only", action="store_true", help="只打印解析 JSON，不下载")
    args = ap.parse_args()

    share = extract_first_url(args.url)
    data = parse_media(share)
    if args.json_only:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return 0

    out_dir = Path(args.out).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    title = sanitize_filename(data.get("title") or "media")
    meta_path = out_dir / f"{title}.json"
    meta_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    video_url = pick_video_url(data)
    results = {"title": data.get("title"), "type": data.get("type"), "meta": str(meta_path)}

    if not video_url:
        # image-only posts
        pics = data.get("pics") or []
        for i, pic in enumerate(pics):
            ext = ".jpg"
            dest = out_dir / f"{title}_{i}{ext}"
            curl_download(pic, dest)
            results.setdefault("pics", []).append(str(dest))
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return 0

    video_path = out_dir / f"{title}.mp4"
    curl_download(video_url, video_path)
    results["video"] = str(video_path)

    need_audio = args.audio or args.audio_only
    if need_audio:
        audio_path = out_dir / f"{title}.m4a"
        audio_path = extract_audio(video_path, audio_path)
        results["audio"] = str(audio_path)
        if args.audio_only and video_path.exists():
            video_path.unlink()
            results.pop("video", None)

    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print(f"错误: {e}", file=sys.stderr)
        raise SystemExit(1)
