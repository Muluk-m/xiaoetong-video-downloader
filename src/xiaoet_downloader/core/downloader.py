#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import time
import requests
import m3u8
import threading
from typing import List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed
from m3u8.model import SegmentList, Segment, find_key

from ..models.config import XiaoetConfig
from ..models.video import VideoResource, VideoMetadata, DownloadResult, DownloadStatus
from ..utils.file_utils import FileUtils
from ..utils.logger import logger


class VideoDownloader:
    """视频下载器"""
    
    def __init__(self, config: XiaoetConfig):
        """初始化下载器"""
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36',
            'Referer': f'https://{config.app_id}.h5.xiaoeknow.com/'
        })
    
    def download_m3u8_video(self, resource: VideoResource, play_url: str, 
                           download_dir: str, nocache: bool = False) -> DownloadResult:
        """
        下载m3u8视频
        
        Args:
            resource: 视频资源对象
            play_url: m3u8播放地址
            download_dir: 下载目录
            nocache: 是否忽略缓存
            
        Returns:
            DownloadResult: 下载结果
        """
        if not play_url:
            return DownloadResult(resource, False, "无效的播放地址")
        
        # 创建资源目录
        resource_dir = os.path.join(download_dir, resource.resource_id)
        FileUtils.ensure_dir(resource_dir)
        
        try:
            resource.download_status = DownloadStatus.DOWNLOADING
            logger.info(f"开始下载视频: {resource.title}")
            
            # 获取m3u8内容
            response = self.session.get(play_url)
            if response.status_code != 200:
                return DownloadResult(resource, False, f"获取m3u8内容失败: HTTP {response.status_code}")
            
            # 解析m3u8内容
            try:
                media = m3u8.loads(response.text)
            except Exception as e:
                return DownloadResult(resource, False, f"解析m3u8内容失败: {str(e)}")
            
            if not media.data.get('segments'):
                return DownloadResult(resource, False, "m3u8文件中没有找到视频片段")
            
            # 获取URL前缀
            url_prefix = self._get_url_prefix(play_url)
            segments = SegmentList()
            changed = False
            complete = True
            total_segments = len(media.data['segments'])
            downloaded_segments = 0
            
            logger.info(f"总计 {total_segments} 个视频片段")
            
            # 下载加密密钥（如果存在）
            key_file = None
            if media.keys:
                key_file = self._download_encryption_keys(media.keys, resource_dir)
            
            # 使用线程安全的计数器
            lock = threading.Lock()
            
            # 准备下载任务
            download_tasks = []
            for index, segment in enumerate(media.data['segments']):
                ts_file = os.path.join(resource_dir, f'v_{index}.ts')
                
                # 如果文件已存在且不忽略缓存，则跳过
                if not nocache and os.path.exists(ts_file):
                    logger.info(f"[{index+1}/{total_segments}] 已下载: {os.path.basename(ts_file)}")
                    with lock:
                        downloaded_segments += 1
                else:
                    # 添加到下载任务列表
                    download_tasks.append((index, segment, ts_file))
                
                # 更新片段URI为本地文件
                segment['uri'] = f'v_{index}.ts'
                segments.append(Segment(base_uri=None, keyobject=find_key(segment.get('key', {}), media.keys), **segment))
            
            # 并发下载视频片段
            if download_tasks:
                logger.info(f"使用 {self.config.max_workers} 个线程并发下载 {len(download_tasks)} 个片段")
                changed = True
                
                with ThreadPoolExecutor(max_workers=self.config.max_workers) as executor:
                    # 提交所有下载任务
                    future_to_task = {
                        executor.submit(
                            self._download_segment,
                            segment,
                            ts_file,
                            url_prefix,
                            index + 1,
                            total_segments
                        ): (index, ts_file)
                        for index, segment, ts_file in download_tasks
                    }
                    
                    # 等待所有任务完成
                    for future in as_completed(future_to_task):
                        index, ts_file = future_to_task[future]
                        try:
                            success = future.result()
                            with lock:
                                if success:
                                    downloaded_segments += 1
                                else:
                                    complete = False
                        except Exception as e:
                            logger.error(f"[{index+1}/{total_segments}] 下载任务异常: {str(e)}")
                            with lock:
                                complete = False
            
            # 生成本地m3u8文件
            m3u8_file = os.path.join(resource_dir, 'video.m3u8')
            if changed or not os.path.exists(m3u8_file):
                media.segments = segments
                # 如果下载了密钥，修改m3u8使用本地密钥
                if key_file and media.keys:
                    for key in media.keys:
                        if key:
                            key.uri = os.path.basename(key_file)
                with open(m3u8_file, 'w', encoding='utf8') as f:
                    f.write(media.dumps())
            
            # 保存元数据
            metadata = VideoMetadata(
                title=resource.title,
                complete=complete,
                total_segments=total_segments,
                downloaded_segments=downloaded_segments
            )
            FileUtils.save_json(metadata.to_dict(), os.path.join(resource_dir, 'metadata.json'))
            
            # 更新资源状态
            resource.download_status = DownloadStatus.COMPLETED if complete else DownloadStatus.FAILED
            
            if complete:
                logger.info(f"视频下载完成: {resource.title}")
                return DownloadResult(resource, True, "下载完成", resource_dir)
            else:
                logger.warning(f"视频下载不完整: {resource.title} ({downloaded_segments}/{total_segments})")
                return DownloadResult(resource, False, f"下载不完整 ({downloaded_segments}/{total_segments})")
                
        except Exception as e:
            resource.download_status = DownloadStatus.FAILED
            logger.error(f"下载视频时发生错误: {str(e)}")
            return DownloadResult(resource, False, f"下载失败: {str(e)}")
    
    def _get_url_prefix(self, play_url: str) -> str:
        """获取URL前缀"""
        if 'v.f230' in play_url:
            return play_url.split('v.f230')[0]
        return play_url.rsplit('/', 1)[0] + '/'
    
    def _download_segment(self, segment: dict, ts_file: str, url_prefix: str, 
                         current: int, total: int, max_retries: int = 3) -> bool:
        """
        下载单个视频片段
        
        Args:
            segment: 片段信息
            ts_file: 本地文件路径
            url_prefix: URL前缀
            current: 当前片段序号
            total: 总片段数
            max_retries: 最大重试次数
            
        Returns:
            bool: 是否下载成功
        """
        # 构建片段URL
        segment_url = segment.get('uri')
        if not segment_url.startswith('http'):
            segment_url = url_prefix + segment_url
        
        retry_count = 0
        while retry_count < max_retries:
            try:
                response = self.session.get(segment_url, timeout=30)
                if response.status_code == 200:
                    # 写入临时文件，下载完成后重命名
                    temp_file = ts_file + '.tmp'
                    with open(temp_file, 'wb') as f:
                        f.write(response.content)
                    os.rename(temp_file, ts_file)
                    logger.info(f"[{current}/{total}] 下载成功: {os.path.basename(ts_file)}")
                    return True
                else:
                    logger.warning(f"[{current}/{total}] 下载失败: HTTP {response.status_code}")
                    retry_count += 1
            except requests.exceptions.RequestException as e:
                logger.warning(f"[{current}/{total}] 下载出错: {str(e)}")
                retry_count += 1
                if retry_count < max_retries:
                    time.sleep(1)  # 等待1秒后重试
        
        logger.error(f"[{current}/{total}] 达到最大重试次数，下载失败")
        return False
    
    def _download_encryption_keys(self, keys: List, resource_dir: str, max_retries: int = 3) -> Optional[str]:
        """
        下载HLS加密密钥
        
        Args:
            keys: 密钥列表
            resource_dir: 资源目录
            max_retries: 最大重试次数
            
        Returns:
            Optional[str]: 密钥文件路径，如果下载失败返回None
        """
        if not keys:
            return None
        
        # 获取第一个有效的密钥
        key = None
        for k in keys:
            if k and hasattr(k, 'uri') and k.uri:
                key = k
                break
        
        if not key or not key.uri:
            logger.debug("没有找到有效的加密密钥")
            return None
        
        key_file = os.path.join(resource_dir, 'encryption.key')
        
        # 如果密钥文件已存在，直接返回
        if os.path.exists(key_file):
            logger.info("加密密钥文件已存在")
            return key_file
        
        logger.info(f"开始下载加密密钥: {key.uri}")
        
        retry_count = 0
        while retry_count < max_retries:
            try:
                response = self.session.get(key.uri, timeout=30)
                if response.status_code == 200:
                    # 写入密钥文件
                    temp_file = key_file + '.tmp'
                    with open(temp_file, 'wb') as f:
                        f.write(response.content)
                    os.rename(temp_file, key_file)
                    logger.info(f"加密密钥下载成功，大小: {len(response.content)} 字节")
                    return key_file
                else:
                    logger.warning(f"下载密钥失败: HTTP {response.status_code}")
                    retry_count += 1
            except requests.exceptions.RequestException as e:
                logger.warning(f"下载密钥出错: {str(e)}")
                retry_count += 1
                if retry_count < max_retries:
                    time.sleep(1)
        
        logger.error("达到最大重试次数，密钥下载失败")
        return None