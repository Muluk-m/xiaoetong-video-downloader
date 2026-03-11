# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec file for 小鹅通视频下载器 backend

import sys
from pathlib import Path

block_cipher = None

a = Analysis(
    ['server.py'],
    pathex=['../src'],
    binaries=[],
    datas=[],
    hiddenimports=[
        # uvicorn 及其子模块
        'uvicorn',
        'uvicorn.logging',
        'uvicorn.loops',
        'uvicorn.loops.auto',
        'uvicorn.loops.asyncio',
        'uvicorn.protocols',
        'uvicorn.protocols.http',
        'uvicorn.protocols.http.auto',
        'uvicorn.protocols.http.h11_impl',
        'uvicorn.protocols.http.httptools_impl',
        'uvicorn.protocols.websockets',
        'uvicorn.protocols.websockets.auto',
        'uvicorn.protocols.websockets.wsproto_impl',
        'uvicorn.protocols.websockets.websockets_impl',
        'uvicorn.lifespan',
        'uvicorn.lifespan.on',
        'uvicorn.lifespan.off',
        # fastapi
        'fastapi',
        'fastapi.middleware',
        'fastapi.middleware.cors',
        'fastapi.responses',
        # starlette (fastapi dependency)
        'starlette',
        'starlette.responses',
        'starlette.routing',
        'starlette.middleware',
        'starlette.middleware.cors',
        # pydantic
        'pydantic',
        # 第三方依赖
        'm3u8',
        'requests',
        'rookiepy',
        # 项目模块
        'xiaoet_downloader',
        'xiaoet_downloader.models',
        'xiaoet_downloader.models.config',
        'xiaoet_downloader.models.video',
        'xiaoet_downloader.core',
        'xiaoet_downloader.core.manager',
        'xiaoet_downloader.core.downloader',
        'xiaoet_downloader.core.transcoder',
        'xiaoet_downloader.api',
        'xiaoet_downloader.api.client',
        'xiaoet_downloader.utils',
        'xiaoet_downloader.utils.logger',
        'xiaoet_downloader.utils.file_utils',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='backend-server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
