# pic-workflow — AI 图片/视频工作流引擎

给个人创作者的"图片→视频→成片"工作流编排工具，覆盖短剧/营销图/创意内容的多模态生产。

## 目录结构
- `00_项目简报/` 项目背景、定位、目标
- `02_图像/` 图片素材库
- `08_SOP与模板/` 标准作业流程与模板
- `engine/` 核心引擎（bin/config/src/tests）

## 快速上手
```bash
cd engine
pip install -r requirements.txt
python -m pic_workflow --input "02_图像/sample.png" --output "out/"
```

## 合规
本项目遵循开源许可（见 LICENSE）。生成内容版权归原作者所有，商用请遵守相关平台 AIGC 标注要求。

> English: AI image/video workflow engine for creators — image→video→final-cut pipeline for short-drama & marketing content.