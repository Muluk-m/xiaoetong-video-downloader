.PHONY: help install test clean run setup check fix download-ffmpeg download-ffmpeg-all

help:
	@echo "小鹅通视频下载器 - 可用命令:"
	@echo "  make install    - 安装依赖"
	@echo "  make setup      - 环境设置"
	@echo "  make test       - 运行测试"
	@echo "  make run        - 运行程序"
	@echo "  make check      - 检查环境"
	@echo "  make fix              - 修复已下载的加密视频"
	@echo "  make download-ffmpeg  - 下载当前架构的 ffmpeg"
	@echo "  make download-ffmpeg-all - 下载所有架构的 ffmpeg"
	@echo "  make clean            - 清理临时文件"

install:
	pip3 install -r requirements.txt

setup:
	python scripts/setup.py

test:
	python -m pytest tests/ -v

run:
	python main.py

check:
	python main.py --check

fix:
	python scripts/fix_encrypted_videos.py

download-ffmpeg:
	bash scripts/download-ffmpeg.sh

download-ffmpeg-all:
	bash scripts/download-ffmpeg.sh --all

clean:
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	find . -type f -name "*.tmp" -delete
	rm -rf .pytest_cache/