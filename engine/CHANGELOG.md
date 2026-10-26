# CHANGELOG

> pic-workflow 变更日志

## [Unreleased]

## [0.5.14] — 2026-10-26

### feat
- `bin/bench.py`：档位基准测试脚本，支持 T0/T1/T2 全档位输出配置摘要 + JSON 模式
- `templates/`：剧本模板系统（workplace_drama.md / historical.md / romance.md），含完整占位符
- `pipeline_cli.py`：修复无 GPU 环境下的 graceful degradation（CPU-only 自动降级为 T0）

### fix
- `bench.py`：`generate_and_dump` 参数修正，改用 `generate_workflow` 支持 scenario 参数
- `bench.py`：JSON 模式下 progress 输出改走 stderr，stdout 纯 JSON

### test
- 全量 201 passed, 1 skipped（GPU 实机冒烟，CI 环境跳过）

---

## [0.5.13] — 2026-10-26

### feat
- 四维矩阵：shot_patterns 24 / platform_profiles 8 / hook_patterns 16 / pace_profiles 10
- 叙事结构层 + 平台交付层
- 三级降级预案：OOM/超时/质量失败类型路由

---

## [0.5.8] — 2026-10-24

### feat
- 本地模型真跑接线：runner 扫描 D 盘 checkpoints 注入实跑 prompt + auto_repair 本地降级
