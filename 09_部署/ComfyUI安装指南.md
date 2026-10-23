# ComfyUI 安装指南（pic-workflow · T0/T1/T2）

> 配合 `engine/config/comfyui/comfyui_T*.yaml` 使用。
> 开发机：白皇 GTX 1060 6GB (Pascal) + 32GB 内存 = **T1 档验证主力**。
> 本机路径：`F:\项目\开发\pic`。

## 一、前置依赖（先装这些）

| 依赖 | 版本 | 用途 |
|---|---|---|
| Python | 3.10–3.12（**别用 3.13**） | ComfyUI 运行环境 |
| PyTorch (CUDA) | 2.x，匹配你的 CUDA | 推理引擎 |
| Git | 任意 | 拉源码 |
| nvidia-smi | 驱动自带 | 显存监控（引擎探针用） |
| git-lfs | 可选 | 管理模型权重（引擎里 09_部署/models 走 NVMe 直存） |

> 本机当前 Python 是 3.13（引擎开发用），**跑 ComfyUI 建议单开一个 3.10/3.11 venv**，
> 避免版本打架。下面以 Windows + conda/venv 为例。

## 二、安装 ComfyUI（Windows）

```powershell
# 1. 进项目部署目录
cd F:\项目\开发\pic\09_部署

# 2. 拉 ComfyUI 源码
git clone https://github.com/comfyanonymous/ComfyUI.git

# 3. 建 3.10/3.11 venv（别用 3.13）
py -3.11 -m venv ComfyUI\.venv        # 或 conda create -n comfy python=3.11
ComfyUI\.venv\Scripts\activate        # Windows
# conda activate comfy                # 若用 conda

# 4. 装依赖 + 匹配 CUDA 的 PyTorch
pip install -r ComfyUI\requirements.txt
# Pascal(1060, compute 6.1) 用 cu118 或 cu121（支持 6.1 的最后两代）
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
```

## 三、按档位选启动参数（引擎已生成三套 yaml）

| 档位 | 显存 | 启动命令要点 | 配置文件 |
|---|---|---|---|
| T0 纯云端 | 0（不跑本地） | 不启 ComfyUI，全走 Kling/Seedream API | `comfyui_T0.yaml` |
| **T1** | 6–8GB（1060 主力） | `--lowvram --use-pytorch-cross-attention --fp16-vae --high-ram`，**关 SageAttention**（Pascal 不支持） | `comfyui_T1.yaml` |
| T2 | 10–12GB | `--fp16-vae --use-pytorch-cross-attention --high-ram`，可开 SageAttention（Ampere+） | `comfyui_T2.yaml` |

**T1（1060 6GB）启动：**
```powershell
cd ComfyUI
# GGUF Q4 模型放 models/checkpoints/ + models/gguf/，VAE 开 tiling
.\.venv\Scripts\python main.py --lowvram --use-pytorch-cross-attention --fp16-vae --high-ram
# 浏览器开 http://127.0.0.1:8188
```

> **Pascal 1060 三大坑（引擎已规避）**：
> 1. **不支持 FP8 / SageAttention** → T1 配置里 `sage: false`，用 PyTorch 交叉注意力
> 2. **6GB 显存紧张** → 必须 `--lowvram` + `--high-ram`（吃 32GB 内存做 offload）+ VAE Tiling
> 3. **量化** → 走 GGUF Q4_K_M（`sd15.safetensors(gguf Q4)`、`Wan2.1-T2V-1.3B-q4.gguf`），不是 fp16

## 四、模型权重放哪（引擎约定）

```
09_部署/models/
  checkpoints/   sd15.safetensors(gguf Q4_K_M)
  gguf/          Wan2.1-T2V-1.3B-q4.gguf / GPT-SoVITS-q4.gguf
  ltx/           LTX-Video-0.95.safetensors (T2)
  gpt_sovits/    GPT-SoVITS_full.bin (T2)
```
> 权重 80GB+ **本机 NVMe 直存，不进 Git**（.gitignore 已忽略 09_部署/models/）。
> 跑 `engine/bin/sync_cloud.py --mode manifest` 生成 `models_manifest.json` 登记清单。

## 五、验证装好没

```powershell
# 1. 显存探针（引擎自带，读 nvidia-smi）
python F:\项目\开发\pic\engine\bin\hw_probe.py --match
#   应看到: GPU GeForce GTX 1060  VRAM=6GB  arch=Pascal  fp8=False  档位=T1

# 2. 生成 T1 工作流（确认按 1060 裁剪了）
python F:\项目\开发\pic\engine\bin\generate_workflow.py T1

# 3. ComfyUI 起来后，T1 出图应选 512、视频 480P、GGUF Q4 + offload
```

## 六、常见问题

| 现象 | 处理 |
|---|---|
| 1060 跑 512 图 OOM | 确认 `--lowvram --high-ram` 都开了，VAE tiling 开；还不行切 T0 云端 Seedream |
| `torch.cuda.is_available()=False` | PyTorch 装成 CPU 版了，重装 `--index-url .../cu118` |
| Python 3.13 import 报错 | 换 3.11 venv（3.13 太新，部分扩展没 wheel） |
| 跑完本地镜头 OOM 想自动迁云端 | `python engine/bin/adaptive_feedback.py --workdir <state目录>`，引擎会反哺 matrix |
