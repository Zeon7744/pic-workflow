# HookForge Web UI

三种出片方案，一个界面搞定。

## 启动

```bash
cd /root/pic-push/engine
PYTHONPATH=src streamlit run apps/web/app.py --server.port 8501
```

## 三种方案

| 方案 | 输入 | 操作 | 适用场景 |
|------|------|------|----------|
| 方案一：CLI 自动生产 | 剧本 .md 文件 | 一条命令 | 已有剧本，快速出片 |
| 方案二：表单 → LLM → 引擎 | 剧名/题材/角色等表单 | 填表 → 一键生成 | 从零开始，创意验证 |
| 方案三：上传剧本 | 上传 .md 文件 | 选参数 → 运行 | 临时测试，快速迭代 |

## 云端模型配置

编辑 `config/api_keys.env`：

```
WAN_API_KEY=sk-xxx          # 通义万相
KLING_API_KEY=xxx           # 快手可灵
SEEDREAM_API_KEY=xxx        # 腾讯 Seedream
```

或在环境变量中设置。
