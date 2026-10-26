# pic-workflow 0.5.14 迭代终版记录

**日期：** 2026-10-26
**Commit：** 84aef9a
**状态：** ✅ 已推送 GitHub / Gitee / gitcode

---

## 迭代目标
在 0.5.13（矩阵扩4维+叙事结构层）基础上，完善工具链、验证三套方案、修复测试缺陷。

---

## 变更清单

### feat
1. **`bin/bench.py`** — 档位基准测试脚本
   - 支持 T0/T1/T2 全档位输出配置摘要
   - `--json` 纯 JSON 模式（stdout），progress 走 stderr
   - `--output` 写文件
   - 内置硬件探测 + 档位匹配结果

2. **`templates/`** — 剧本模板系统（3套）
   - `workplace_drama.md` — 职场复仇（占位符：TITLE/CHAR1_NAME/HIT1_DESC等）
   - `historical.md` — 古装权谋
   - `romance.md` — 甜宠爱情

3. **`scripts/daily_inspect.py`** — 每日巡检脚本
   - 集成 bench + pytest + pic-sync 三合一
   - 输出 JSON 报告到 `logs/daily/YYYY-MM-DD/`
   - 支持 `--json` / `--only-bench` 参数

4. **无 GPU 环境 graceful degradation**
   - CPU-only 机器自动匹配 T0（纯云端）
   - pipeline_cli 不再崩溃，正常输出报告

### fix
1. **`tests/test_workflow_explorer.py`** — 修复硬编码 Windows 路径
   - 原：`r"C:\Users\Administrator\pic-push\engine\config\matrix.yaml"`
   - 改：`os.path.join(os.path.dirname(__file__), "..", "config", "matrix.yaml")`
   - 影响 2 个测试用例

2. **`tests/test_ui_app.py`** — 修复绝对路径下载测试
   - 原：传绝对路径 `vid`（含盘符）到 `/download/` 端点
   - 改：传相对路径 `rel_dirname/out/final.mp4`
   - 原因：Flask send_file 对含盘符路径返回 308 redirect

### test
- 278 passed, 0 failed, 1 skipped（GPU 实机冒烟跳过）
- 较 0.5.13 的 275 passed 增加 3 个新测试（bench.py 覆盖）

---

## 实测数据

### 引擎端到端测试
| 剧本 | 档位 | 画风 | 环节 | 结果 |
|------|------|------|------|------|
| 助理反击_第1集 | T1 | S1_anime_jp | 9/9 | ✓ 10分镜，49行剧本 |
| 宫墙影_第1集 | T1 | S3_cn_shuimo | 9/9 | ✓ 12分镜，44行剧本 |

### Bench 基准（CPU-only 云电脑）
| 档位 | 节点数 | 生成耗时 | 主模型 |
|------|--------|----------|--------|
| T0（纯云端） | 8 | 0.11s | cloud_api_seedream + cloud_kling |
| T1（6-8GB） | 8 | 0.14s | sdxl_anime_lora + wan13b_gguf_q4 |
| T2（10-12GB） | 8 | 0.11s | sdxl_anime_lora + wan13b_gguf_q4 + gpt_sovits_q4 |

### 每日巡检
- Git HEAD：84aef9a
- 测试：278P / 0F / 0S
- 耗时：~42s（bench 41s + 测试 1s）

---

## 三套方案状态

| 方案 | 状态 | 入口 | 备注 |
|------|------|------|------|
| 一：自动生产 | ✅ 已验证 | `pipeline_cli` 一条命令 | 需手动写剧本 .md |
| 二：交互生成 | 🔄 进行中 | 表单模板 → LLM → 剧本 → 引擎 | 需接 LLM 自动生成剧本 |
| 三：独立应用 | 📋 已设计 | Streamlit Web UI | 架构文档在 HTML 报告中 |

---

## 遗留待办
- [ ] 接入真实 AI 模型（Wan/Kling/Seedream API），产出真实视频
- [ ] 方案二：表单→LLM→剧本 链路落地
- [ ] 方案三：Streamlit Web UI 原型
- [ ] pic-sync 定期巡检（Calendar 定时触发 daily_inspect.py）

---

## Git 历史
```
84aef9a fix(test): 修复硬编码路径和绝对路径下载测试
2983f1b test(0.5.14): 宫墙影剧本跑通引擎 + workflow_T1更新
aec4c83 feat(0.5.14): bench脚本 + 剧本模板系统 + 无GPU环境降级
093ee7a feat(0.5.14): bench脚本 + 剧本模板系统 + 无GPU环境降级
7143588 feat(0.5.13): 叙事结构层+平台交付层
```
