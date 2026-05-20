#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
import requests
from typing import Any, Dict, List, Optional, Tuple, Union
from ..models.config import XiaoetConfig
from ..models.video import VideoResource


class XiaoetAPIClient:
    """小鹅通API客户端"""

    GET_COLUMN_ITEMS_URL = "https://{0}.h5.xiaoeknow.com/xe.course.business.column.items.get/2.0.0"
    GET_VIDEO_DETAILS_INFO_URL = "https://{0}.h5.xiaoeknow.com/xe.course.business.video.detail_info.get/2.0.0"
    GET_MICRO_NAVIGATION_URL = "https://{0}.h5.xiaoeknow.com/xe.micro_page.navigation.get/1.0.0"
    GET_PLAY_URL = "https://{0}.h5.xiaoeknow.com/xe.material-center.play/getPlayUrl"

    DEFAULT_TIMEOUT = 15

    def __init__(self, config: XiaoetConfig):
        self.config = config
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36'
        })

    def _post(
        self,
        url: str,
        label: str,
        *,
        data: Optional[Union[Dict[str, str], str]] = None,
        json_payload: Optional[Dict[str, Any]] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """统一的 POST 请求封装,返回 response.json() 整体字典。

        label 用于异常消息前缀,例如 "获取导航信息"。
        """
        headers: Dict[str, str] = {'cookie': self.config.cookie}
        if json_payload is not None:
            headers['Content-Type'] = 'application/json'
            body = json.dumps(json_payload)
        else:
            body = data
        if extra_headers:
            headers.update(extra_headers)

        try:
            response = requests.post(url, headers=headers, data=body, timeout=self.DEFAULT_TIMEOUT)
            response.raise_for_status()
            return response.json()
        except requests.Timeout:
            raise Exception(f"{label}超时，请检查网络连接")
        except requests.RequestException as e:
            raise Exception(f"{label}失败: {str(e)}")
        except json.JSONDecodeError as e:
            raise Exception(f"解析{label}响应失败: {str(e)}")

    def get_micro_navigation_info(self) -> Dict[str, Any]:
        """获取微页面导航信息"""
        url = self.GET_MICRO_NAVIGATION_URL.format(self.config.app_id)
        resp = self._post(
            url,
            "获取导航信息",
            json_payload={"app_id": self.config.app_id, "agent_type": 1, "app_version": 0},
        )
        return resp.get('data', {})

    def get_column_items(self, column_id: str, page_index: int = 1,
                        page_size: int = 100, sort: str = 'desc') -> List[Dict[str, Any]]:
        """
        获取专栏项目列表

        Returns:
            List[Dict]: 包含资源详细信息的列表，每个字典包含：
                - resource_id: 资源ID
                - resource_title: 资源标题
                - resource_type: 资源类型（3=视频）
                - start_at: 开始时间
                - learn_progress: 学习进度（0-100）
                - 等等
        """
        url = self.GET_COLUMN_ITEMS_URL.format(self.config.app_id)

        all_items: List[Dict[str, Any]] = []
        current_page = page_index

        while True:
            resp = self._post(
                url,
                "获取专栏项目列表",
                data={
                    'bizData[column_id]': column_id,
                    'bizData[page_index]': str(current_page),
                    'bizData[page_size]': str(page_size),
                    'bizData[sort]': sort,
                },
            )
            data = resp.get('data', {})
            items = data.get('list', [])
            total = data.get('total', 0)

            if not items:
                break

            all_items.extend(items)

            if len(all_items) >= total:
                break

            current_page += 1

        return all_items

    def get_video_detail_info(self, resource_id: str) -> Dict[str, Any]:
        """获取视频详情信息"""
        url = self.GET_VIDEO_DETAILS_INFO_URL.format(self.config.app_id)
        resp = self._post(
            url,
            "获取视频详情",
            data={
                'bizData[resource_id]': resource_id,
                'bizData[product_id]': self.config.product_id,
                'bizData[opr_sys]': 'MacIntel',
            },
        )
        return resp.get('data', {}).get('video_info', {})

    def get_play_url(self, user_id: str, play_sign: str) -> Dict[str, Any]:
        """获取播放URL"""
        url = self.GET_PLAY_URL.format(self.config.app_id)
        resp = self._post(
            url,
            "获取播放URL",
            json_payload={
                "org_app_id": self.config.app_id,
                "app_id": self.config.app_id,
                "user_id": user_id,
                "play_sign": [play_sign],
                "play_line": "A",
                "opr_sys": "MacIntel",
            },
        )
        return resp.get('data', {}).get(play_sign, {}).get('play_list', {})

    def get_best_quality_url(self, play_list_dict: Dict[str, Any]) -> Optional[Tuple[str, str]]:
        """获取最佳质量的播放URL"""
        quality_order = ['1080p_hls', '720p_hls', '480p_hls', '360p_hls']

        for quality in quality_order:
            if quality in play_list_dict and play_list_dict.get(quality, {}).get('play_url'):
                return play_list_dict.get(quality, {}).get('play_url'), quality

        return None, None
