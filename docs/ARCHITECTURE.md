# pic-workflow 模块结构

## 目录
```
pic-workflow/
├── engine/ (bin/ src/ config/ tests/ + pro_gate.py + orchestrator/combo_optimizer/conflict_check)
├── billing.py
├── 00_项目简报/ 02_图像/ 08_SOP与模板/
└── docs/
```

## 数据流
1. engine 读图片素材 → 编排工作流 → 生成视频/成片
2. 每次生成前走 billing.check_access('free','use') 门控（1 次/天）
3. 超限 402 + 升级链接（爱发电 https://afdian.com/@Zeon7744）
