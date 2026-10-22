# -*- coding: utf-8 -*-
"""pic-workflow 自适应引擎包。

硬件自适应短剧视频生成工作流引擎。
核心资产：config/matrix.yaml（档位×节点矩阵）+ 三级降级预案。
YAML 是数据不是代码——引擎按硬件档位"算"出工作流。

模块契约（谁依赖谁 / 主入口）：
  入口  workflow_gen.generate_workflow     档位+画风+音频轨 → 全链路工作流
  判档  tier_scoring.match_tier            硬件 profile → T0-T5
  质量  qa_scoring.score_shot(tier=)       镜头 4 维打分 + 档位感知阈值 + 路由
        shot_qa.assess_and_record         真实 CLIP 观测 → qa_scoring
  降级  downgrade.route_fallback          OOM/超时/质量 三失败类型路由
  音频  audio_advisor.advise_tracks       剧种×档位 智能裁剪（省心省事）
        combo_optimizer.optimize          四维协同打分 best+alt（精准命中）
  冲突  conflict_check.check_conflict     0-100 适配分矩阵
  闭环  adaptive.run_feedback             record_metrics 历史 → 反哺 matrix
        record_metrics.record_step        实机指标采集
  对标  benchmark_advisory.run            4 参照物 6 维超越分
        resource_profiler                 实机省钱测算
  校验  config_validator.validate_matrix  matrix 结构+交叉引用校验（CI）
  编排  orchestrator.run_pipeline         8 环节断点重跑 + 指标采集
  探测  hw_probe                          硬件探测

各模块离线可单测，不依赖 torch/CLIP 实模型。
"""
__version__ = "0.2.0-mvp"
