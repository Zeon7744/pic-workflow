# pic-workflow 收款与门控（爱发电 afdian）

## 定价档位（与 billing.py 对齐）
| 档位 | 价格 | 限制 |
|---|---|---|
| Free | ¥0 | 1 次/天生成 · 基础工作流 |
| Pro | ¥99/月 | 不限次 · 角色一致性 · 四维风格矩阵 |

## 收款流程（先体验后付费）
1. 免费 1 次/天，超限 402 + 升级链接（爱发电 https://afdian.com/@Zeon7744）
2. 付款 → billing.AfdianGateway.query_callback 核验 → 本地提权
3. 无 key 走 noop 安全降级
