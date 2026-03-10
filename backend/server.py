#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
小鹅通视频下载器 - FastAPI 后端服务
提供 REST API 供 Tauri 前端调用
"""

import asyncio
import json
import os
import re
import sys
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, Optional

import rookiepy
import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# 添加src目录到Python路径
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from xiaoet_downloader import XiaoetConfig, XiaoetDownloadManager, logger
from xiaoet_downloader.models.video import (
    DownloadResult,
    DownloadStatus,
    ResourceType,
    VideoResource,
)

app = FastAPI(title="小鹅通视频下载器 API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============ 全局状态 ============

CONFIG_PATH = str(PROJECT_ROOT / "config.json")

# 下载任务状态跟踪
download_tasks: Dict[str, Dict[str, Any]] = {}


# ============ 请求模型 ============


class ConfigUpdate(BaseModel):
    app_id: str = ""
    cookie: str = ""
    product_id: str = ""
    download_dir: str = "download"
    max_workers: int = 5


class ParseUrlRequest(BaseModel):
    url: str


class DownloadRequest(BaseModel):
    resource_ids: list[str] = []  # 为空则下载全部
    nocache: bool = False
    auto_transcode: bool = True


# ============ URL 解析 ============


@app.post("/api/parse-url")
async def parse_url(req: ParseUrlRequest):
    """从小鹅通课程 URL 中提取 app_id 和 product_id"""
    url = req.url.strip()

    # Extract app_id from subdomain, e.g. "appuab59i5o3529" from
    # "https://appuab59i5o3529.h5.xiaoeknow.com/..."
    app_id_match = re.search(r"https?://(app[a-zA-Z0-9]+)\.h5\.", url)
    if not app_id_match:
        return {"success": False, "message": "无法从 URL 中解析 app_id，请确认链接格式正确"}

    app_id = app_id_match.group(1)

    # Extract product_id from path, e.g. "p_693bd2bfe4b0694c5b61a406"
    product_id_match = re.search(r"/(p_[a-zA-Z0-9]+)", url)
    if not product_id_match:
        return {"success": False, "message": "无法从 URL 中解析 product_id，请确认链接包含课程/专栏 ID"}

    product_id = product_id_match.group(1)

    return {"success": True, "app_id": app_id, "product_id": product_id}


# ============ Cookie 相关 ============


@app.get("/api/cookies")
async def get_chrome_cookies():
    """从 Chrome 浏览器自动读取小鹅通的 Cookie"""
    try:
        # 小鹅通使用多个域名
        domains = [".xiaoe-tech.com", ".xet.citv.cn", ".xiaoeknow.com", ".xet.tech"]

        all_cookies = []
        for domain in domains:
            try:
                cookies = rookiepy.chrome([domain])
                all_cookies.extend(cookies)
            except Exception:
                pass

        # 如果按域名没找到，从全量 cookie 中搜索
        if not all_cookies:
            try:
                all_browser_cookies = rookiepy.chrome()
                keywords = ["xiaoe", "xet", "ko_token", "colla_login"]
                all_cookies = [
                    c for c in all_browser_cookies
                    if any(kw in c.get("domain", "").lower() or kw in c.get("name", "").lower() for kw in keywords)
                ]
            except Exception:
                pass

        if not all_cookies:
            return {"success": False, "message": "未找到小鹅通相关 Cookie，请先在 Chrome 中登录小鹅通", "cookie": ""}

        # 去重（按 name 去重，保留最后一个）
        seen = {}
        for c in all_cookies:
            seen[c["name"]] = c["value"]

        cookie_str = "; ".join(f"{k}={v}" for k, v in seen.items())

        return {"success": True, "message": f"成功读取 {len(seen)} 个 Cookie", "cookie": cookie_str}
    except Exception as e:
        return {"success": False, "message": f"读取 Cookie 失败: {str(e)}", "cookie": ""}


# ============ 配置相关 ============


@app.get("/api/config")
async def get_config():
    """获取当前配置"""
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                config = json.load(f)
            return {"success": True, "config": config}
        return {"success": True, "config": {"app_id": "", "cookie": "", "product_id": "", "download_dir": "download", "max_workers": 5}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/config")
async def save_config(config: ConfigUpdate):
    """保存配置"""
    try:
        config_dict = config.model_dump()
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(config_dict, f, ensure_ascii=False, indent=2)
        return {"success": True, "message": "配置已保存"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============ 视频列表 ============


@app.get("/api/videos")
async def list_videos():
    """获取课程视频列表"""
    try:
        config = _load_config()
        manager = XiaoetDownloadManager(config)
        videos = manager.list_course_videos()
        return {"success": True, "videos": videos, "total": len(videos)}
    except Exception as e:
        return {"success": False, "message": str(e), "videos": [], "total": 0}


# ============ 环境检查 ============


@app.get("/api/check")
async def check_environment():
    """检查运行环境"""
    try:
        config = _load_config()
        manager = XiaoetDownloadManager(config)
        ok = manager.check_environment()
        return {"success": ok, "message": "环境检查通过" if ok else "环境检查失败"}
    except Exception as e:
        return {"success": False, "message": str(e)}


# ============ 下载相关 ============


@app.post("/api/download")
async def start_download(req: DownloadRequest):
    """启动下载任务，返回 task_id"""
    try:
        config = _load_config()
    except Exception as e:
        return {"success": False, "message": str(e)}

    task_id = str(uuid.uuid4())[:8]
    download_tasks[task_id] = {
        "status": "running",
        "progress": [],
        "current": 0,
        "total": 0,
        "current_title": "",
        "segments_downloaded": 0,
        "segments_total": 0,
        "results": {"success": [], "failed": []},
    }

    # 在后台线程执行下载
    thread = threading.Thread(
        target=_run_download,
        args=(task_id, config, req.resource_ids, req.nocache, req.auto_transcode),
        daemon=True,
    )
    thread.start()

    return {"success": True, "task_id": task_id}


@app.get("/api/download/status/{task_id}")
async def get_download_status(task_id: str):
    """获取下载任务状态"""
    if task_id not in download_tasks:
        raise HTTPException(status_code=404, detail="任务不存在")
    return download_tasks[task_id]


@app.get("/api/download/stream/{task_id}")
async def stream_download_status(task_id: str):
    """SSE 流式推送下载进度"""
    if task_id not in download_tasks:
        raise HTTPException(status_code=404, detail="任务不存在")

    async def event_generator():
        last_progress_len = 0
        while True:
            task = download_tasks.get(task_id)
            if not task:
                break

            data = json.dumps(task, ensure_ascii=False)
            yield f"data: {data}\n\n"

            if task["status"] in ("completed", "failed"):
                break

            await asyncio.sleep(0.5)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/api/download/cancel/{task_id}")
async def cancel_download(task_id: str):
    """取消下载任务"""
    if task_id not in download_tasks:
        raise HTTPException(status_code=404, detail="任务不存在")
    download_tasks[task_id]["status"] = "cancelled"
    return {"success": True, "message": "已发送取消信号"}


# ============ 辅助函数 ============


def _load_config() -> XiaoetConfig:
    """加载配置"""
    if not os.path.exists(CONFIG_PATH):
        raise Exception("配置文件不存在，请先保存配置")
    return XiaoetConfig.from_file(CONFIG_PATH)


def _run_download(task_id: str, config: XiaoetConfig, resource_ids: list, nocache: bool, auto_transcode: bool):
    """在后台线程中执行下载"""
    task = download_tasks[task_id]

    try:
        manager = XiaoetDownloadManager(config)

        # 获取用户信息
        navigation_info = manager.api_client.get_micro_navigation_info()
        user_id = navigation_info.get("user_id")
        if not user_id:
            task["status"] = "failed"
            task["progress"].append({"type": "error", "message": "无法获取用户ID，Cookie 可能已失效"})
            return

        # 获取视频列表
        if resource_ids:
            # 下载指定的视频
            all_videos = manager.list_course_videos()
            videos = [v for v in all_videos if v.get("resource_id") in resource_ids]
        else:
            videos = manager.list_course_videos()

        if not videos:
            task["status"] = "failed"
            task["progress"].append({"type": "error", "message": "没有找到可下载的视频"})
            return

        task["total"] = len(videos)

        for index, video in enumerate(videos):
            if task["status"] == "cancelled":
                task["progress"].append({"type": "info", "message": "下载已取消"})
                return

            resource_id = video.get("resource_id")
            resource_title = video.get("resource_title", "未知")
            task["current"] = index + 1
            task["current_title"] = resource_title

            task["progress"].append({"type": "info", "message": f"[{index+1}/{len(videos)}] 开始处理: {resource_title}"})

            try:
                resource = VideoResource(
                    resource_id=resource_id,
                    title=resource_title,
                    resource_type=ResourceType.VIDEO,
                )

                # 获取播放URL
                play_url = manager._get_play_url(resource, user_id)
                if not play_url:
                    task["results"]["failed"].append({"title": resource_title, "id": resource_id, "message": "无法获取播放地址"})
                    task["progress"].append({"type": "error", "message": f"  无法获取播放地址: {resource_title}"})
                    continue

                # 定义分片进度回调
                def on_segment_progress(downloaded, total_seg):
                    task["segments_downloaded"] = downloaded
                    task["segments_total"] = total_seg

                # 下载视频
                download_result = manager.downloader.download_m3u8_video(
                    resource, play_url, config.download_dir, nocache,
                    progress_callback=on_segment_progress
                )

                if download_result.success and auto_transcode:
                    task["progress"].append({"type": "info", "message": f"  正在转码: {resource_title}"})
                    transcode_result = manager.transcoder.transcode_video(resource)
                    if transcode_result.success:
                        task["results"]["success"].append({"title": resource_title, "id": resource_id, "message": "下载转码完成"})
                        task["progress"].append({"type": "success", "message": f"  完成: {resource_title}"})
                    else:
                        task["results"]["failed"].append({"title": resource_title, "id": resource_id, "message": transcode_result.message})
                        task["progress"].append({"type": "error", "message": f"  转码失败: {resource_title}"})
                elif download_result.success:
                    task["results"]["success"].append({"title": resource_title, "id": resource_id, "message": "下载完成"})
                    task["progress"].append({"type": "success", "message": f"  下载完成: {resource_title}"})
                else:
                    task["results"]["failed"].append({"title": resource_title, "id": resource_id, "message": download_result.message})
                    task["progress"].append({"type": "error", "message": f"  下载失败: {resource_title} - {download_result.message}"})

            except Exception as e:
                task["results"]["failed"].append({"title": resource_title, "id": resource_id, "message": str(e)})
                task["progress"].append({"type": "error", "message": f"  出错: {resource_title} - {str(e)}"})

        task["status"] = "completed"
        success_count = len(task["results"]["success"])
        failed_count = len(task["results"]["failed"])
        task["progress"].append({"type": "info", "message": f"全部完成！成功 {success_count} 个，失败 {failed_count} 个"})

    except Exception as e:
        task["status"] = "failed"
        task["progress"].append({"type": "error", "message": f"下载过程出错: {str(e)}"})


# ============ 启动 ============

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=19528, log_level="info")
