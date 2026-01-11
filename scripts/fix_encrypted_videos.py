#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
修复已下载的加密视频
下载密钥文件并更新m3u8文件
"""

import os
import sys
import requests
import m3u8
from pathlib import Path

# 添加src目录到Python路径
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from xiaoet_downloader import logger


def fix_video_directory(video_dir: str) -> bool:
    """
    修复单个视频目录
    
    Args:
        video_dir: 视频目录路径
        
    Returns:
        bool: 是否修复成功
    """
    m3u8_file = os.path.join(video_dir, 'video.m3u8')
    
    if not os.path.exists(m3u8_file):
        logger.warning(f"未找到m3u8文件: {m3u8_file}")
        return False
    
    logger.info(f"处理: {video_dir}")
    
    try:
        # 解析m3u8文件
        with open(m3u8_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        media = m3u8.loads(content)
        
        # 检查是否有加密密钥
        if not media.keys or not media.keys[0]:
            logger.info("视频未加密，无需处理")
            return True
        
        key = media.keys[0]
        if not key.uri:
            logger.info("没有找到密钥URI")
            return True
        
        # 如果密钥URI已经是本地文件，跳过
        if not key.uri.startswith('http'):
            logger.info("密钥已经是本地文件，无需处理")
            return True
        
        key_file = os.path.join(video_dir, 'encryption.key')
        
        # 下载密钥
        if not os.path.exists(key_file):
            logger.info(f"下载密钥: {key.uri}")
            try:
                response = requests.get(key.uri, timeout=30)
                if response.status_code == 200:
                    with open(key_file, 'wb') as f:
                        f.write(response.content)
                    logger.info(f"密钥下载成功，大小: {len(response.content)} 字节")
                else:
                    logger.error(f"下载密钥失败: HTTP {response.status_code}")
                    return False
            except Exception as e:
                logger.error(f"下载密钥出错: {str(e)}")
                return False
        else:
            logger.info("密钥文件已存在")
        
        # 更新m3u8文件
        key.uri = 'encryption.key'
        
        # 保存更新后的m3u8
        with open(m3u8_file, 'w', encoding='utf-8') as f:
            f.write(media.dumps())
        
        logger.info("m3u8文件已更新")
        return True
        
    except Exception as e:
        logger.error(f"处理出错: {str(e)}")
        return False


def main():
    """主函数"""
    download_dir = 'download'
    
    if not os.path.exists(download_dir):
        logger.error(f"下载目录不存在: {download_dir}")
        return 1
    
    # 遍历所有视频目录
    success_count = 0
    fail_count = 0
    
    for dir_name in os.listdir(download_dir):
        video_dir = os.path.join(download_dir, dir_name)
        
        # 只处理目录
        if not os.path.isdir(video_dir):
            continue
        
        # 跳过非视频目录
        if not dir_name.startswith('v_'):
            continue
        
        if fix_video_directory(video_dir):
            success_count += 1
        else:
            fail_count += 1
    
    logger.info(f"\n处理完成:")
    logger.info(f"  成功: {success_count}")
    logger.info(f"  失败: {fail_count}")
    
    return 0 if fail_count == 0 else 1


if __name__ == '__main__':
    sys.exit(main())

