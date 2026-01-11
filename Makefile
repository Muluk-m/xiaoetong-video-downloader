.PHONY: help install test clean run setup check fix

help:
	@echo "小鹅通视频下载器 - 可用命令:"
	@echo "  make install    - 安装依赖"
	@echo "  make setup      - 环境设置"
	@echo "  make test       - 运行测试"
	@echo "  make run        - 运行程序"
	@echo "  make check      - 检查环境"
	@echo "  make fix        - 修复已下载的加密视频"
	@echo "  make clean      - 清理临时文件"

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

clean:
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	find . -type f -name "*.tmp" -delete
	rm -rf .pytest_cache/