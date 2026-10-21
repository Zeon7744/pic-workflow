# pic-workflow · 硬件自适应短剧视频生成工作流引擎

## 一句话
输入剧本，引擎自动探测用户机器 → 匹配档位 → 生成"这台机器能跑通"的工作流，
从 4GB 集显到 32GB 旗舰都能产出短剧成片。工作流是 YAML 数据不是代码。

## MVP 边界
- 只做 **T0(纯云端) + T1(6-8GB) + T2(10-12GB)** 三档，覆盖 63% 用户；T3/T4/T5 二期。
- 开发机：白皇 GTX 1060 6GB (Pascal) + 32GB 内存，定位 **T1 档验证主力**。

## 目录规范（10 个一级目录）
```
00_项目简报/   本文件 + 引擎架构说明
01_剧本/       结构化剧本 / 分集
02_图像/       角色卡 / 场景卡 / 画风总纲（Git LFS 追踪）
03_分镜/       分镜提示词
04_视频/       镜头视频（网盘直连，不进 Git）
05_成片/       整合成片（网盘）
06_音频/       BGM / TTS / 音效（网盘）
07_特效字幕/   特效 / 字幕 / 封面（网盘）
08_SOP与模板/  SOP + 各 Agent 指令 + 可复用模板
08_素材库/     特效/音效素材
09_部署/       ComfyUI 启动配置 + 模型权重(本机 NVMe 直存)
engine/        ★ 自适应引擎（核心资产）
```

## 引擎入口
```
python3 engine/bin/hw_probe.py --match     # 硬件探针 + 档位匹配
python3 engine/bin/generate_workflow.py T1  # 生成 T1 工作流
python3 engine/bin/shot_qa.py shot.mp4 --prompt "..."  # 镜头 4 维质检
python3 engine/bin/sync_cloud.py --mode all  # 三路同步
```
