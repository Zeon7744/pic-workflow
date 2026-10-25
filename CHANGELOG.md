# CHANGELOG

> pic-workflow 变更日志（Keep a Changelog 结构，随 patch/feat/chore commit 补充）

## [Unreleased] — 2026-10-25

### 0.5.13 — 叙事结构层 + 平台交付层（能力超前）

矩阵扩 4 个新维度 + 新增 3 个能力模块，补齐"整集怎么排"这一层
（此前只有单镜层 `shot_choreo` / 镜间层 `transition_design` / 成片层 `multimodal_qa`）。

**新增能力模块**
- `narrative_architect`：集级 beat sheet + 钩子开篇 + 爽点排布 + 叙事质检
  （7 种节拍角色、3 秒/15 秒双层钩子、≥3 爽点 + 1 甜点铁律校验）
- `hook_engine`：16 类钩子的生成 / 五维评分 / A-B-C 备选 / 发布闸门
- `platform_spec`：8 平台（红果/抖音/快手/视频号/哔哩/小红书/YouTube Shorts 等）
  成片合规校验 + ffmpeg 导出参数规划 + 批量分发

**矩阵 0.2.0 → 0.3.0（4 个新维度）**
- `shot_patterns` 24 镜型（景别/运镜/时长/节拍/强度）
- `platform_profiles` 8 平台档案（画幅/分辨率/时长/安全区/主钩子/节奏档）
- `hook_patterns` 16 钩子（节拍/3 秒 + 15 秒双层指令/情绪/承诺/门槛分）
- `pace_profiles` 10 节奏档（切镜密度/爽点密度/目标集长/画风/BGM/镜型/题材）

四维互为交叉引用：平台 → 节奏档 + 钩子；节奏档 → BGM + 画风 + 钩子 + 镜型 + 题材；
镜型 → 叙事节拍。任一处改名都会悬空，由 `config_validator` 在 CI 阶段拦住。

**修复**
- `matrix.yaml` 音轨维度畸形 key（`label:"战斗升级": null` 这类）导致
  voice/bbgm 两维字段整体丢失、`combo_optimizer` 情绪匹配永久失效 → 全量还原
- `shot_patterns.beats` 混用叙事节拍与戏剧意图 → 拆分 `beats` / `intent`
- `config_validator` 新维度校验：必备字段 / 互指 / 编号连续 / 数值区间 /
  3 秒钩子铁律 / 每集爽点铁律

**测试**：新增 40 项（`test_narrative_layer.py` 17 + `test_matrix_expand.py` 23），
全量 275 passed / 4 skipped，matrix validator 零 error 零 warning。

## 近期变更摘要

### 10-24

- `195ce46` chore(probe): 三端同步探测探针文件（临时）
- `5b49b70` feat(1060): 固化 Pascal CC6.1 踩坑结论 + 修 adaptive OOM 迁移串位
### 10-23

- `ac608fe` docs: 09_部署 增加 ComfyUI 安装指南（T0/T1/T2 启动参数 + 1060 Pascal 三坑 + 模型权重约定）
- `eb308d1` feat(paywall): 入口接入有偿授权门控（check_access/paywall，免费版拉满+超限拦截）
- `923a53d` docs(week3): 补 3 篇 docs + run.sh（smoke_test.sh 已有）
- `ccd7dde` feat(ui): 用者友好 Web 控制台 + 10分钟上手 + 分角色培训/使用辅助
- `4d24c78` feat: assembler ffmpeg 真合成（成片最后一公里落地）
- `58d0d9d` feat: A+B+C 端到端出片管线（市场短板补口全链）
- `5781800` feat(billing): 补 mbd 收款层 + 门控（Pro ¥99 对齐 README，全 11 仓收尾）
- `8c48682` feat: pipeline_runner 8 环节 dataflow 拓扑执行器（市场短板补口）
- `a02976e` feat: 1060 T1 实测基线固化 + comfyui_runner 断点/重试 + workflow_gen 8 节点全链路数据流
- `f9e6f7e` comfyui_runner：ComfyUI 实跑 runner + 自动 mock 降级，接 orchestrator 真链路
### 10-22

- `2056716` orchestrator 主链路接入三失败路由 + 双维 combo 学习
- `eb5a1a1` 闭环验证：双维combo学习+三失败路由实机跑数 + 对标市场6维全赢
- `f90fae2` ci: 三端全自动镜像（Gitee SSH + GitCode token）
- `e18a0b4` docs(readme): 先体验后付费 + 用户回馈驱动迭代
- `5f2df01` Merge branch 'main' of https://github.com/Zeon7744/pic-workflow
- `f3ce2ca` docs(readme): 统一补「面包多 Pay收款+社区发布」双区块（全仓共存）
- `c374751` feat(engine): 1060 实机数据验证 + matrix 悬空引用落地 + T1 出图降档
- `193fac7` ci: engine-tests workflow（全量单测 + matrix 配置校验，需 workflow scope）

## 维护说明

- 遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/) 结构
- 格式：`commit_sha` 简述（feat/fix/chore/docs/refactor/test）
- 生成时间：2026-10-24