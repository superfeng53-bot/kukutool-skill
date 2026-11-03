# KuKuTool 协议细节

前端为 Next.js。鉴权 profile 嵌在静态 chunk（如 `9802-*.js`）的 `JSON.parse('{"activeProfileId":...}')` 中；脚本会自动发现，失败时回退到内置 profile。

## 1. Auth

```
POST https://dy.kukutool.com/api/auth-9e25f1
Content-Type: application/json
credentials / Cookie: 同站

{"requestURL":"<分享链接>","pagePath":"/","mode":"single"}
```

当前 active profile `2026060303` 响应字段：

```json
{"k_9e25f1":"<authKey>","s_9e25f1":"<authSeed>"}
```

`authRoute` / 字段名会随 profile 轮换（如旧版 `auth-86a05b` / `k_86a05b`）。

## 2. 请求加密（parse v3）

明文参数（页面同源）：

```json
{
  "requestURL": "...",
  "captchaKey": "",
  "captchaInput": "",
  "totalSuccessCount": "0",
  "successCount": "0",
  "firstSuccessDate": "",
  "pagePath": "/",
  "uwx_id": "",
  "isMobile": "false",
  "geoipIp": ""
}
```

加密：

1. `key = SHA-256(authKey + ":" + authSeed)`（原始 32 字节）
2. 随机 12 字节 IV，AES-GCM 加密 `JSON.stringify(params)`（密文含 tag，与 WebCrypto 一致）
3. POST body 字段名来自 `parseRequestFields`，例如：

```json
{
  "version": 3,
  "k_9e25f1": "<authKey>",
  "p_9e25f1": "<base64 ciphertext+tag>",
  "r_9e25f1": 1,
  "i_9e25f1": "<base64 iv>"
}
```

## 3. 响应解密（kukudemethod）

成功形如：

```json
{"status":0,"encrypt":true,"data":"<混淆串>","iv":"<混淆串>"}
```

固定口令：`12345678901234567890123456789013`（前端硬编码）。

对 `data` 与 `iv` 各自：

1. 逐字节 XOR `90`
2. 每 8 字符一段反转
3. 字符集映射  
   `ZYXABCDEFGHIJKLMNOPQRSTUVWzyxabcdefghijklmnopqrstuvw9876543210-_`  
   → 标准 Base64 字母表
4. Base64 解码后，用 `SHA-256(口令)` 作 AES-CBC 密钥解密（PKCS7）
5. `JSON.parse` 得到业务数据

典型字段：

```json
{
  "title": "...",
  "type": "video",
  "cover": "https://...",
  "url": "https://data.hellotik.app/pksr?s=...",
  "videos": [{
    "url": "...",
    "video_fullinfo": [
      {"url": "...", "size": 8122485, "type": "正常"},
      {"url": "...", "size": 33080616, "type": "超高清"}
    ]
  }],
  "pics": ["..."]
}
```

视频直链可能是：

- 代理：`data.hellotik.app/...` → Referer 用 `https://dy.kukutool.com/` 通常可用
- **小红书源站 CDN**：`sns-video-*.xhscdn.com/...` → **禁止** kukutool Referer（会 403）；用 `https://www.xiaohongshu.com/` 或省略 Referer。脚本 `download_referer()` 已按 host 分流。

`download.py` 会在下载**之前**写出 `{title}.json`。若 CDN 下载失败但 JSON 已在，读 **`video_fullinfo` 里 `type=超高清`（或 size 最大）** 重下，不要用顶层「正常」`url`。

## 4. 音频

解析结果通常**不单独返回音轨 URL**。官网 `/audio-extractor` 用 ffmpeg.wasm 从视频抽音。技能侧：

```bash
ffmpeg -y -i video.mp4 -vn -acodec copy out.m4a
```

## 5. 前端相关路径

| 路径 | 用途 |
|------|------|
| `/api/{authRoute}` | 发 ticket / 密钥 |
| `/api/parse` | 加密解析 |
| `/_next/static/chunks/3052.*.js` | `kukudemethod` 实现 |
| `/_next/static/chunks/9802-*.js` | profile + 请求封装 |

## 6. 限流与人机

站点可能弹广告解锁、验证码（业务码如 511）、或 `securityDialog`（IP 冷却/日限额）。纯请求无法替用户看广告；遇限流应告知稍后重试，不要暴力轮询。

实测（2026-07-30）连续 ~10 次小红书 parse 后：

```json
{
  "securityDialog": true,
  "reason": "temporary_access_unavailable",
  "supportCode": "ticket_ip_restricted|auto_script|<ip>",
  "restrictionMinutes": 20
}
```

处理：立即停止对该 IP 的 kukutool 请求；冷却期内小红书改用 **yt-dlp**（见 SKILL.md）；已写出的 JSON 仍可直接拉 CDN。

## 7. 小红书兜底（yt-dlp）

```bash
yt-dlp --cookies-from-browser chrome \
  -f "bv*+ba/b" --merge-output-format mp4 \
  -o "OUT/%(title).80s [%(id)s].%(ext)s" \
  --no-playlist --no-overwrites \
  "http://xhslink.cn/o/...."
```

备注：

- 短链 `xhslink.cn` / `xhslink.com`：裸 `curl -L` 常 404；交给 yt-dlp 跟跳转更稳。
- 备选开源：[JoeanAmier/XHS-Downloader](https://github.com/JoeanAmier/XHS-Downloader)（配置更重，批量素材时优先 yt-dlp）。
