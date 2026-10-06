# -*- coding: utf-8 -*-
"""
PyInstaller 打包脚本 - 生成独立 exe
运行: python build.py
"""
import PyInstaller.__main__
import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 确保 build.py 所在目录在 path 最前面
sys.path.insert(0, BASE_DIR)

PyInstaller.__main__.run([
    os.path.join(BASE_DIR, 'main.py'),
    '--name=非油报表助手',
    '--windowed',
    '--onefile',
    f'--add-data={os.path.join(BASE_DIR, "frontend")}{os.pathsep}frontend',
    f'--add-data={os.path.join(BASE_DIR, "version.json")}{os.pathsep}.',
    f'--add-data={os.path.join(BASE_DIR, "store.py")}{os.pathsep}.',
    f'--add-data={os.path.join(BASE_DIR, "processor.py")}{os.pathsep}.',
    f'--add-data={os.path.join(BASE_DIR, "backend.py")}{os.pathsep}.',
    f'--add-data={os.path.join(BASE_DIR, "base_data.py")}{os.pathsep}.',
    f'--add-data={os.path.join(BASE_DIR, "base_data.json")}{os.pathsep}.',
    '--hidden-import=flask',
    '--hidden-import=pandas',
    '--hidden-import=openpyxl',
    '--hidden-import=PIL',
    '--hidden-import=webview',
    '--hidden-import=clr_loader',
    '--hidden-import=pythonnet',
    '--collect-all=flask',
    '--collect-all=pandas',
    '--collect-all=openpyxl',
    '--collect-all=PIL',
    '--collect-all=webview',
    '--noconfirm',
    '--clean',
    '--distpath=dist',
    '--workpath=build',
    '--specpath=.',
    # 图标（如果有的话可以加 --icon=xxx.ico）
])
