#!/bin/bash
# QSearch WebUI 启动脚本 (Linux/Mac)

# 设置数据库根目录
export QSEARCH_DATABASES_ROOT=databases

# 激活虚拟环境（如果使用）
# source .venv/bin/activate

# 启动 Streamlit
echo "启动 QSearch WebUI..."
echo "数据库目录: $QSEARCH_DATABASES_ROOT"
streamlit run src/qsearch/webui/app.py
