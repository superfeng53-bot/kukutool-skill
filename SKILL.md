---
name: kukutool-video-download
description: >-
  通过 dy.kukutool.com 纯 HTTP 解析短视频分享链接并本地下载原视频/音频（微信视频号、抖音、快手、小红书等）。
  小红书限流或 CDN 403 时改用 yt-dlp（可带 Chrome Cookie）。在用户提到 kukutool、酷酷工具、去水印解析、
  视频号/小红书下载、xhslink.cn、提取音频，或给出 weixin.qq.com/sph、v.douyin.com、xhslink 等分享链接时使用。
---

# KuKuTool 视频/音频下载

用纯请求调用 [dy.kukutool.com](https://dy.kukutool.com/) 的解析接口，拿到直链后下载到本地。站点自带的「提取音频」是浏览器端 ffmpeg.wasm；本技能下载视频后用本机 `ffmpeg` 抽音轨。

**用途边界**：仅用于用户有权保存的内容（如自己的素材、已获授权）。不要批量爬取、绕过付费墙或二次分发他人作品。

## Failure patterns（本技能要避免）

| 失败 | 原因 | 正确做法 |
|------|------|----------|
| 小红书直链 `curl` 403 | 下载带了 `Referer: dy.kukutool.com/`，`xhscdn.com` 拒收 | 脚本已按 CDN 选 Referer（XHS → `xiaohongshu.com`） |
| 批量 auth HTTP 429 / `securityDialog` | kukutool IP 限流（常见 `restrictionMinutes:20`，`auto_script`） | **立刻停轮询**；已写的 `.json` 可直接下 CDN；小红书改走 **yt-dlp** |
| 把无链接的分类文字当视频下 | 分类标记无 URL | 只提取真实链接（`xhslink.cn` / `http(s)://…`） |

**What didn't work**：对 kukutool 429 继续连打；用 kukutool Referer 下 `sns-video-*.xhscdn.com`；纯 curl 展开 `xhslink.cn`（常 404，需 yt-dlp 或解析器跟跳转）。

## 快速开始

```bash
# 依赖：curl、python3、cryptography；抽音频还需 ffmpeg；小红书兜底还需 yt-dlp
pip3 install -r requirements.txt
# 可选：pip3 install -U yt-dlp

# 解析 + 下载视频 + 抽音频
python3 scripts/download.py \
  "https://weixin.qq.com/sph/<分享ID>" \
  --out ~/Downloads/kukutool --audio

# 只看解析 JSON
python3 scripts/download.py "链接" --json-only

# 只要音频（下载后删除视频）
python3 scripts/download.py "链接" --audio-only
```

脚本路径按仓库根目录。装到 Cursor 后一般为：

`~/.cursor/skills/kukutool-skill/scripts/download.py`

默认输出目录：`~/Downloads/kukutool/`，会写出 `{标题}.mp4`、可选 `{标题}.m4a`、以及 `{标题}.json` 元数据。

**画质：** 解析 JSON 里 `videos[].video_fullinfo` 可能有「正常 / 超高清」等档。脚本默认下 **超高清（或 size 最大）**，不要改用顶层 `url` / `videos[0].url` 的「正常」档。小红书批量限流时改 yt-dlp `-f "bv*+ba/b"`，取同源最高档。

## Agent 工作流

1. 从用户消息提取分享链接（可含前后文案，脚本会用正则取出 URL）。**跳过无 URL 的分类行**。
2. 执行 `scripts/download.py`；用户要音频时加 `--audio` 或 `--audio-only`。
3. **批量**：串行 + 每条间隔 ≥2s；条数多（≥8）时优先按「小红书 → yt-dlp」或放慢节奏，避免触发 kukutool IP 冷却。
4. 失败分流：
   - **下载 403 且已有同名 `.json`**：用 JSON 里 `video_fullinfo` 超高清（或 size 最大）URL，以平台匹配的 Referer 再 `curl`（不必重新 parse）。
   - **auth/parse 429 / `securityDialog`**：停止 kukutool；小红书走下方 yt-dlp；其他平台告知冷却分钟数后重试。
   - 其它：把 stderr 原文给用户，并按 [reference.md](reference.md) 排查。
5. **不要**用浏览器自动化当主路径；只有纯请求与 yt-dlp 都失败且用户明确要求时再考虑打开网页。

## 小红书兜底：yt-dlp

kukutool 限流或 XHS 直链异常时：

```bash
pip3 install -U yt-dlp
yt-dlp --cookies-from-browser chrome \
  -f "bv*+ba/b" --merge-output-format mp4 \
  -o "/path/to/out/%(title).80s [%(id)s].%(ext)s" \
  --no-playlist --no-overwrites \
  "http://xhslink.cn/o/xxxx"
```

- Chrome Cookie 读取可能触发钥匙串授权；无 Cookie 有时也能解析，失败再加 `--cookies-from-browser chrome`。
- 标题偶发为 `XiaoHongShu video #<id>`：按用户文案或笔记标题重命名。
- 开源备选（需自行配 Cookie 与环境）：[JoeanAmier/XHS-Downloader](https://github.com/JoeanAmier/XHS-Downloader)。

## 协议摘要（实现已封装在脚本）

1. `GET /` 拿 Cookie
2. `POST /api/{authRoute}`，body：`{requestURL, pagePath:"/", mode:"single"}` → `authKey` + `authSeed`
3. 明文参数 AES-GCM 加密后 `POST /api/parse`（字段名随前端 profile 混淆）
4. 若 `encrypt:true`，按站点 `kukudemethod` 解密得到 `title/url/videos/pics`
5. `curl` 下载 `url`（**按 CDN 选 Referer**）；音频用本机 `ffmpeg -vn`

完整字段、加解密步骤、限流说明见 [reference.md](reference.md)。

## 常见失败

| 现象 | 处理 |
|------|------|
| auth/parse 非 200 或 `securityDialog` | IP 或频率限制；**停**；读 `restrictionMinutes`；小红书改 yt-dlp |
| `status` ≠ 0 | 链接失效或平台暂不支持；核对链接是否完整 |
| 下载 403（尤其 `xhscdn.com`） | 先查 Referer 是否误用 kukutool；有 `.json` 则换 Referer 重下；否则重新 parse 或 yt-dlp |
| 无 `ffmpeg` | `brew install ffmpeg`，或只下视频 |
| yt-dlp 读 Chrome Cookie 卡住 | 在系统钥匙串放行，或改用 safari / 导出 cookies.txt |
