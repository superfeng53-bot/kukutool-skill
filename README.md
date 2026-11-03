# KuKuTool 视频下载 Skill

![License](https://img.shields.io/badge/license-MIT-green)

Cursor Agent Skill：用纯 HTTP 调用 [dy.kukutool.com](https://dy.kukutool.com/) 解析短视频分享链接，下载到本地，并用本机 `ffmpeg` 抽音频。支持微信视频号、抖音、快手、小红书等分享链接。

小红书被限流或 CDN 返回 403 时，改用 `yt-dlp`（可读本机 Chrome Cookie）。

**只保存你有权保存的内容**（自己的素材、已获授权的作品）。不要用它批量爬取、绕过付费墙，或二次分发别人的作品。

## 安装

依赖：`curl`、`python3`、`ffmpeg`（抽音频）。Python 包见 `requirements.txt`。小红书兜底另需 `yt-dlp`。

```bash
pip3 install -r requirements.txt
# 可选
pip3 install -U yt-dlp
brew install ffmpeg   # 还没有 ffmpeg 时
```

装成 Cursor Skill：

```bash
git clone https://github.com/superfeng53-bot/kukutool-skill.git \
  ~/.cursor/skills/kukutool-skill
```

克隆完成后，在对话里贴上分享链接即可。Agent 会读 `SKILL.md`。

## 命令行

```bash
# 解析并下载视频，同时抽音频
python3 scripts/download.py "分享链接或含链接的一段文字" \
  --out ~/Downloads/kukutool --audio

# 只看解析 JSON
python3 scripts/download.py "分享链接" --json-only

# 只要音频（下完后删除视频）
python3 scripts/download.py "分享链接" --audio-only
```

默认输出目录是 `~/Downloads/kukutool/`，会写出 `{标题}.mp4`、可选 `{标题}.m4a`，以及 `{标题}.json`。

画质默认取解析结果里的「超高清」（没有就取体积最大的一档）。

## 目录

```
kukutool-skill/
├── SKILL.md              # Agent 指令
├── reference.md          # 接口与加解密说明
├── scripts/download.py   # 解析 + 下载
├── requirements.txt
├── README.md
└── LICENSE
```

站点会轮换鉴权字段。脚本会从页面静态资源里自动发现当前 profile，发现失败时用内置 fallback。字段说明见 [reference.md](reference.md)。

## 许可

[MIT](LICENSE)
