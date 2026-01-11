#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
from typing import List, Dict, Tuple, Optional, Any

from ..models.config import XiaoetConfig
from ..models.video import VideoResource, DownloadResult, ResourceType
from ..api.client import XiaoetAPIClient
from ..core.downloader import VideoDownloader
from ..core.transcoder import VideoTranscoder
from ..utils.file_utils import FileUtils
from ..utils.logger import logger


class XiaoetDownloadManager:
    """小鹅通下载管理器"""
    
    def __init__(self, config: XiaoetConfig):
        """初始化下载管理器"""
        self.config = config
        self.api_client = XiaoetAPIClient(config)
        self.downloader = VideoDownloader(config)
        self.transcoder = VideoTranscoder(config.download_dir)
        
        # 确保下载目录存在
        FileUtils.ensure_dir(config.download_dir)
    
    def download_course(self, nocache: bool = False, auto_transcode: bool = True) -> Dict[str, List[DownloadResult]]:
        """
        下载整个课程
        
        Args:
            nocache: 是否忽略缓存
            auto_transcode: 是否自动转码
            
        Returns:
            Dict[str, List[DownloadResult]]: 下载结果统计
        """
        results = {
            'success': [],
            'failed': []
        }
        
        try:
            # 获取用户信息
            navigation_info = self.api_client.get_micro_navigation_info()
            user_id = navigation_info.get('user_id')
            if not user_id:
                logger.error("无法获取用户ID")
                return results
            
            # 获取课程资源列表
            resource_items = self.api_client.get_column_items(self.config.product_id)
            if not resource_items:
                logger.warning("未找到课程资源")
                return results
            
            logger.info(f"找到 {len(resource_items)} 个资源")
            
            # 处理每个资源
            for index, item in enumerate(resource_items):
                try:
                    resource_id = item.get('resource_id')
                    resource_title = item.get('resource_title')
                    resource_type_code = item.get('resource_type', 0)
                    
                    # 只处理视频资源（resource_type == 3）
                    if resource_type_code != 3:
                        logger.info(f"跳过非视频资源: {resource_title}")
                        continue
                    
                    logger.info(f"[{index+1}/{len(resource_items)}] 处理视频: {resource_title} ({resource_id})")
                    
                    # 创建视频资源对象
                    resource = VideoResource(
                        resource_id=resource_id,
                        title=resource_title,
                        resource_type=ResourceType.VIDEO
                    )
                    
                    # 获取播放URL
                    play_url = self._get_play_url(resource, user_id)
                    if not play_url:
                        result = DownloadResult(resource, False, "无法获取播放地址")
                        results['failed'].append(result)
                        continue
                    
                    # 下载视频
                    download_result = self.downloader.download_m3u8_video(
                        resource, play_url, self.config.download_dir, nocache
                    )
                    
                    if download_result.success and auto_transcode:
                        # 自动转码
                        transcode_result = self.transcoder.transcode_video(resource)
                        if transcode_result.success:
                            results['success'].append(transcode_result)
                        else:
                            results['failed'].append(transcode_result)
                    elif download_result.success:
                        results['success'].append(download_result)
                    else:
                        results['failed'].append(download_result)
                        
                except Exception as e:
                    error_msg = f"处理视频 {resource_title} 时出错: {str(e)}"
                    logger.error(error_msg)
                    result = DownloadResult(
                        VideoResource(resource_id, resource_title), 
                        False, 
                        error_msg
                    )
                    results['failed'].append(result)
            
            # 打印处理结果
            self._print_summary(results)
            
        except Exception as e:
            logger.error(f"下载课程时发生错误: {str(e)}")
        
        return results
    
    def download_single_video(self, resource_id: str, nocache: bool = False, 
                             auto_transcode: bool = True) -> DownloadResult:
        """
        下载单个视频
        
        Args:
            resource_id: 资源ID
            nocache: 是否忽略缓存
            auto_transcode: 是否自动转码
            
        Returns:
            DownloadResult: 下载结果
        """
        try:
            # 获取用户信息
            navigation_info = self.api_client.get_micro_navigation_info()
            user_id = navigation_info.get('user_id')
            if not user_id:
                return DownloadResult(
                    VideoResource(resource_id, "未知"), 
                    False, 
                    "无法获取用户ID"
                )
            
            # 创建视频资源对象（标题暂时未知）
            resource = VideoResource(
                resource_id=resource_id,
                title="未知",
                resource_type=ResourceType.VIDEO if resource_id.startswith('v_') else ResourceType.AUDIO
            )
            
            # 获取播放URL
            play_url = self._get_play_url(resource, user_id)
            if not play_url:
                return DownloadResult(resource, False, "无法获取播放地址")
            
            # 下载视频
            download_result = self.downloader.download_m3u8_video(
                resource, play_url, self.config.download_dir, nocache
            )
            
            if download_result.success and auto_transcode:
                # 自动转码
                return self.transcoder.transcode_video(resource)
            
            return download_result
            
        except Exception as e:
            error_msg = f"下载视频 {resource_id} 时出错: {str(e)}"
            logger.error(error_msg)
            return DownloadResult(
                VideoResource(resource_id, "未知"), 
                False, 
                error_msg
            )
    
    def _get_play_url(self, resource: VideoResource, user_id: str) -> Optional[str]:
        """获取播放URL"""
        try:
            # 获取视频详情
            video_details = self.api_client.get_video_detail_info(resource.resource_id)
            play_sign = video_details.get('play_sign')
            
            if not play_sign:
                logger.warning(f"无法获取视频 {resource.title} 的播放标识")
                return None
            
            # 更新资源的play_sign
            resource.play_sign = play_sign
            
            # 获取播放URL列表
            play_list_dict = self.api_client.get_play_url(user_id, play_sign)
            
            # 获取最佳质量的播放URL
            play_url, quality = self.api_client.get_best_quality_url(play_list_dict)
            
            if play_url:
                logger.info(f"获取到 {quality} 播放地址")
                resource.play_url = play_url
                return play_url
            else:
                logger.warning(f"无法获取视频 {resource.title} 的播放地址")
                return None
                
        except Exception as e:
            logger.error(f"获取播放URL时出错: {str(e)}")
            return None
    
    def _print_summary(self, results: Dict[str, List[DownloadResult]]) -> None:
        """打印处理结果摘要"""
        total = len(results['success']) + len(results['failed'])
        success_count = len(results['success'])
        failed_count = len(results['failed'])
        
        logger.info("\n" + "="*50)
        logger.info("处理完成:")
        logger.info(f"成功: {success_count}/{total}")
        logger.info(f"失败: {failed_count}/{total}")
        
        if results['failed']:
            logger.info("\n失败的视频:")
            for result in results['failed']:
                logger.error(f"- {result.resource.title} ({result.resource.resource_id}): {result.message}")
        
        if results['success']:
            logger.info("\n成功的视频:")
            for result in results['success']:
                logger.info(f"+ {result.resource.title}")
        
        logger.info("="*50)
    
    def check_environment(self) -> bool:
        """检查运行环境"""
        logger.info("检查运行环境...")
        
        # 检查配置
        try:
            self.config.validate()
            logger.info("✓ 配置验证通过")
        except ValueError as e:
            logger.error(f"✗ 配置验证失败: {str(e)}")
            return False
        
        # 检查ffmpeg
        if self.transcoder.check_ffmpeg_availability():
            logger.info("✓ ffmpeg 可用")
        else:
            logger.warning("⚠ ffmpeg 不可用，将无法进行视频转码")
        
        # 检查下载目录
        try:
            FileUtils.ensure_dir(self.config.download_dir)
            logger.info(f"✓ 下载目录已准备: {self.config.download_dir}")
        except Exception as e:
            logger.error(f"✗ 无法创建下载目录: {str(e)}")
            return False
        
        return True
    
    def list_course_videos(self) -> List[Dict[str, Any]]:
        """
        列出所有课程视频
        
        Returns:
            List[Dict]: 视频列表，每个字典包含资源的详细信息
        """
        try:
            # 获取课程资源列表
            resource_items = self.api_client.get_column_items(self.config.product_id)
            if not resource_items:
                logger.warning("未找到课程资源")
                return []
            
            # 只返回视频资源（resource_type == 3）
            videos = []
            for item in resource_items:
                if item.get('resource_type') == 3:
                    videos.append(item)
            
            return videos
            
        except Exception as e:
            logger.error(f"获取课程列表时出错: {str(e)}")
            return []
    
    def interactive_download(self, nocache: bool = False, auto_transcode: bool = True) -> Dict[str, List[DownloadResult]]:
        """
        交互式下载
        
        Args:
            nocache: 是否忽略缓存
            auto_transcode: 是否自动转码
            
        Returns:
            Dict[str, List[DownloadResult]]: 下载结果统计
        """
        # 获取视频列表
        videos = self.list_course_videos()
        
        if not videos:
            logger.error("没有找到可下载的视频")
            return {'success': [], 'failed': []}
        
        # 显示视频列表
        print("\n" + "="*100)
        print(f"找到 {len(videos)} 个视频:")
        print("="*100)
        for index, video in enumerate(videos, 1):
            title = video.get('resource_title', '未知标题')
            resource_id = video.get('resource_id', '')
            start_at = video.get('start_at', '')
            learn_progress = video.get('learn_progress', 0)
            
            # 进度条
            progress_bar = self._make_progress_bar(learn_progress)
            
            print(f"{index:3d}. {title}")
            print(f"     ID: {resource_id} | 日期: {start_at} | 进度: {progress_bar} {learn_progress}%")
        print("="*100)
        
        # 获取用户选择
        print("\n请选择要下载的视频（支持多种输入方式）:")
        print("  - 单个: 1")
        print("  - 多个: 1,3,5")
        print("  - 范围: 1-10")
        print("  - 混合: 1,3-5,8")
        print("  - 全部: all 或 *")
        print("  - 取消: q 或 quit")
        
        while True:
            try:
                choice = input("\n请输入: ").strip()
                
                if choice.lower() in ['q', 'quit', 'exit']:
                    logger.info("已取消下载")
                    return {'success': [], 'failed': []}
                
                # 解析选择
                selected_indices = self._parse_selection(choice, len(videos))
                
                if not selected_indices:
                    print("❌ 无效的输入，请重新输入")
                    continue
                
                # 确认选择
                selected_videos = [videos[i] for i in selected_indices]
                print(f"\n✓ 已选择 {len(selected_videos)} 个视频:")
                for video in selected_videos:
                    title = video.get('resource_title', '未知标题')
                    print(f"  - {title}")
                
                confirm = input("\n确认下载? (y/n): ").strip().lower()
                if confirm in ['y', 'yes']:
                    break
                else:
                    print("已取消，请重新选择")
                    
            except KeyboardInterrupt:
                print("\n\n已取消下载")
                return {'success': [], 'failed': []}
            except Exception as e:
                print(f"❌ 输入错误: {str(e)}")
                continue
        
        # 下载选中的视频
        return self.download_selected_videos(selected_videos, nocache, auto_transcode)
    
    def download_selected_videos(self, videos: List[Dict[str, Any]], 
                                 nocache: bool = False, 
                                 auto_transcode: bool = True) -> Dict[str, List[DownloadResult]]:
        """
        下载选中的视频
        
        Args:
            videos: 视频列表，每个字典包含资源详细信息
            nocache: 是否忽略缓存
            auto_transcode: 是否自动转码
            
        Returns:
            Dict[str, List[DownloadResult]]: 下载结果统计
        """
        results = {
            'success': [],
            'failed': []
        }
        
        try:
            # 获取用户信息
            navigation_info = self.api_client.get_micro_navigation_info()
            user_id = navigation_info.get('user_id')
            if not user_id:
                logger.error("无法获取用户ID")
                return results
            
            logger.info(f"\n开始下载 {len(videos)} 个视频")
            
            # 处理每个视频
            for index, video in enumerate(videos):
                try:
                    resource_id = video.get('resource_id')
                    resource_title = video.get('resource_title')
                    
                    logger.info(f"\n[{index+1}/{len(videos)}] 处理视频: {resource_title} ({resource_id})")
                    
                    # 创建视频资源对象
                    resource = VideoResource(
                        resource_id=resource_id,
                        title=resource_title,
                        resource_type=ResourceType.VIDEO
                    )
                    
                    # 获取播放URL
                    play_url = self._get_play_url(resource, user_id)
                    if not play_url:
                        results['failed'].append(
                            DownloadResult(resource, False, "无法获取播放地址")
                        )
                        continue
                    
                    # 下载视频
                    download_result = self.downloader.download_m3u8_video(
                        resource, play_url, self.config.download_dir, nocache
                    )
                    
                    if download_result.success and auto_transcode:
                        # 自动转码
                        transcode_result = self.transcoder.transcode_video(resource)
                        if transcode_result.success:
                            results['success'].append(transcode_result)
                        else:
                            results['failed'].append(transcode_result)
                    elif download_result.success:
                        results['success'].append(download_result)
                    else:
                        results['failed'].append(download_result)
                        
                except Exception as e:
                    error_msg = f"处理视频时出错: {str(e)}"
                    logger.error(error_msg)
                    results['failed'].append(
                        DownloadResult(
                            VideoResource(resource_id, resource_title, ResourceType.VIDEO),
                            False,
                            error_msg
                        )
                    )
            
            # 打印结果摘要
            self._print_summary(results)
            
        except Exception as e:
            logger.error(f"批量下载时发生错误: {str(e)}")
        
        return results
    
    def _parse_selection(self, choice: str, max_count: int) -> List[int]:
        """
        解析用户选择
        
        Args:
            choice: 用户输入
            max_count: 最大数量
            
        Returns:
            List[int]: 选中的索引列表（从0开始）
        """
        if choice.lower() in ['all', '*']:
            return list(range(max_count))
        
        selected = set()
        
        # 分割输入
        parts = choice.split(',')
        
        for part in parts:
            part = part.strip()
            
            # 处理范围 (如 1-10)
            if '-' in part:
                try:
                    start, end = part.split('-')
                    start = int(start.strip())
                    end = int(end.strip())
                    
                    if start < 1 or end > max_count or start > end:
                        raise ValueError(f"范围无效: {part}")
                    
                    # 添加范围内的所有索引（转换为从0开始）
                    for i in range(start - 1, end):
                        selected.add(i)
                        
                except ValueError as e:
                    raise ValueError(f"无效的范围格式: {part}")
            
            # 处理单个数字
            else:
                try:
                    num = int(part)
                    if num < 1 or num > max_count:
                        raise ValueError(f"数字超出范围: {num}")
                    selected.add(num - 1)  # 转换为从0开始的索引
                except ValueError:
                    raise ValueError(f"无效的数字: {part}")
        
        return sorted(list(selected))
    
    def _make_progress_bar(self, progress: int, width: int = 20) -> str:
        """
        生成进度条
        
        Args:
            progress: 进度（0-100）
            width: 进度条宽度
            
        Returns:
            str: 进度条字符串
        """
        filled = int(width * progress / 100)
        bar = '█' * filled + '░' * (width - filled)
        return f"[{bar}]"