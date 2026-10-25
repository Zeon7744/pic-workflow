# CHANGELOG

> pic-workflow 变更日志（Keep a Changelog 结构，随 patch/feat/chore commit 补充）

## [Unreleased] — 2026-10-24

本周三端巡检自动补全（billing 收款层 / paywall 门控 / 文档 / 冒烟测试）

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