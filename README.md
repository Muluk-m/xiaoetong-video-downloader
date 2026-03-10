<p align="center">
  <img src="assets/logo.svg" width="128" height="128" alt="logo">
</p>

<h1 align="center">小鹅通视频下载器</h1>

<p align="center">
  一款带 GUI 界面的小鹅通课程视频下载工具，支持自动读取 Chrome Cookie、加密视频、批量下载。
</p>

<p align="center">
  <a href="#桌面端下载">桌面端下载</a> · <a href="#命令行使用">命令行使用</a> · <a href="#常见问题">常见问题</a>
</p>

---

> 本工具仅支持下载用户已购买的课程，不存在任何破解行为。仅供个人学习使用，请勿用于商业用途。

## 功能特性

- **桌面端 GUI** — 基于 Tauri 的原生桌面应用，可视化操作
- **自动读取 Cookie** — 一键从 Chrome 浏览器获取登录态，无需手动复制
- **加密视频支持** — 自动处理 HLS AES-128 加密流
- **批量下载** — 勾选多个视频一键下载，支持全选
- **实时进度** — 视频级 + 分片级双层进度显示
- **自动转码** — 下载完成后自动合并为 MP4（需要 ffmpeg）
- **命令行模式** — 同时保留完整的 CLI 工具，适合服务器/脚本使用

## 桌面端下载

前往 [Releases](../../releases) 页面下载最新版本：

| 平台 | 文件 |
|------|------|
| macOS (Apple Silicon) | `小鹅通视频下载器_x.x.x_aarch64.dmg` |
| macOS (Intel) | `小鹅通视频下载器_x.x.x_x64.dmg` |

> 首次打开 macOS 可能提示"无法验证开发者"，请在 **系统设置 → 隐私与安全性** 中允许打开。

### 前提条件

- **ffmpeg**：视频转码需要，推荐通过 Homebrew 安装
  ```bash
  brew install ffmpeg
  ```
- **Python 3.10+**：桌面端会自动调用项目自带的 Python 后端

## 桌面端使用

1. 打开应用，在「配置」页点击 **自动获取** Cookie（确保 Chrome 已登录小鹅通）
2. 填写 `App ID` 和 `Product ID`（从课程链接中获取）
3. 点击 **保存配置**
4. 切换到「视频列表」页，点击 **刷新列表**
5. 勾选要下载的视频，点击 **下载选中**
6. 在「下载任务」页查看实时进度

### 如何获取 App ID 和 Product ID

从课程链接中提取：

```
https://appuab59i5o3529.h5.xet.citv.cn/p/course/column/p_693bd2bfe4b0694c5b61a406
       ^^^^^^^^^^^^^^^^                                  ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
       App ID                                            Product ID
```

## 命令行使用

```bash
# 安装依赖
pip install -r requirements.txt

# 复制配置文件并填写
cp config.json.example config.json

# 交互式下载（推荐）
python main.py --interactive

# 列出所有视频
python main.py --list

# 下载整个课程
python main.py

# 下载单个视频
python main.py --single v_123456789

# 检查环境
python main.py --check
```

### 配置说明

| 字段 | 说明 | 默认值 |
|------|------|--------|
| `app_id` | 店铺标识，从课程链接获取 | - |
| `cookie` | 小鹅通 Cookie（桌面端可自动获取） | - |
| `product_id` | 课程标识，从课程链接获取 | - |
| `download_dir` | 下载目录 | `download` |
| `max_workers` | 并发数 | `5` |

## 项目结构

```
xiaoetong-video-downloader/
├── gui/                          # Tauri 桌面端
│   ├── src/                      # 前端 (HTML/CSS/JS)
│   └── src-tauri/                # Tauri 后端 (Rust)
├── backend/                      # FastAPI 后端服务
│   └── server.py
├── src/xiaoet_downloader/        # Python 核心库
│   ├── api/client.py             # 小鹅通 API 客户端
│   ├── core/
│   │   ├── downloader.py         # M3U8 视频下载器
│   │   ├── transcoder.py         # FFmpeg 转码器
│   │   └── manager.py            # 下载管理器
│   ├── models/                   # 数据模型
│   └── utils/                    # 工具类
├── main.py                       # CLI 入口
├── config.json.example           # 配置模板
└── requirements.txt
```

## 从源码构建桌面端

```bash
# 前提：安装 Node.js、Rust、Python 3.10+

# 1. 安装 Python 依赖
python -m venv .venv
source .venv/bin/activate
PYO3_USE_ABI3_FORWARD_COMPATIBILITY=1 pip install -r requirements.txt

# 2. 安装前端依赖
cd gui && npm install

# 3. 开发模式运行
npm run tauri dev

# 4. 构建发布版本
npm run tauri build
```

## 常见问题

**Q: Cookie 自动获取失败？**
确保 Chrome 浏览器已登录小鹅通，且 Chrome 已完全关闭（macOS 上需要退出 Chrome，不只是关闭窗口）。

**Q: ffmpeg 未找到？**
安装 ffmpeg 并确保在 PATH 中：`brew install ffmpeg`

**Q: 合并视频时 httpproxy 错误？**
运行 `python scripts/fix_encrypted_videos.py` 将加密密钥下载到本地。

**Q: macOS 提示无法打开？**
系统设置 → 隐私与安全性 → 点击"仍要打开"。

## 致谢

- [xiaoetong-video-downloader](https://github.com/miaoyc666/xiaoetong-video-downloader) — 原始项目
- [Tauri](https://tauri.app/) — 桌面端框架
- [rookiepy](https://github.com/thewh1teagle/rookie) — 浏览器 Cookie 读取

## 许可证

本项目仅供学习和个人使用。
