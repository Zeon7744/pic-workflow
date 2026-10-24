@echo off
chcp 65001 >nul
:: 1060 Pascal T1 档 ComfyUI 启动脚本（秋葉 v3.2 兼容版 cu126 专用）
:: 用法：放到整合包根目录（如 D:\ComfyUI\aki\），按实际改下面 python 目录名
set TORCH_CUDA_ARCH_LIST=6.1
set NVIDIA_TF32_OVERRIDE=0
python\python.exe ComfyUI\main.py --lowvram --use-pytorch-cross-attention --fp16-vae --high-ram --port 8188
echo =================================================
echo  若浏览器没自动打开，手动访问: http://127.0.0.1:8188
echo  关闭本窗口 = 停止 ComfyUI
pause
