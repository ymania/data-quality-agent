# 开发要求交付核对表

核对依据：`数据质量Agent开发要求(2).md`。本文件给评审快速定位；启动与演示看 README，设计、测试、学习记录在根目录，补充报告和截图见 `docs/`。

| 开发要求 | 交付位置 | 实测情况 |
| --- | --- | --- |
| Web 页面和同会话对话 | `app/static/`、`app/main.py`、`app/agent.py` | 真实模型对 20 条基准订单完成组合任务与“刚才”追问；本轮 Docker 未配置模型密钥 |
| Deep Agents 调用工具 | `app/agent.py` | `create_deep_agent` 接入显式模型、工具、checkpointer；不是关键词固定回复 |
| 创建、运行、查询三类工具 | `app/agent.py`、`app/quality.py` | 返回规则 ID、执行 ID、统计、异常样例和错误；按钮复用同一服务 |
| 两种规则与精确值域比较 | `app/quality.py` | NULL、空串、纯空格、大小写和尾空格均有测试 |
| 20 条订单和控制表 | `sql/schema.sql`、`sql/seed.sql` | 非空失败 3 条（ID 1/2/3）、值域失败 2 条（ID 4/5），通过率 85.00% / 89.47% |
| 独立执行与历史快照 | `quality_runs`，见 `app/quality.py` | 数据变化后新统计为 4 / 3，旧统计与样例逐字一致 |
| 空表、全跳过、非法 ID、断库 | `tests/test_acceptance.py`、`scripts/verify_docker.py` | 空分母显示无可校验数据；非法 ID 返回 404；断库返回 503 |
| 文件上传扩展与 MySQL 保留 | `app/datasets.py`、`app/upload_api.py`、`DATA_INGESTION.md` | 网页实测 3 行上传、规则执行 #1：2 条异常，原 20 条库不混查 |
| 启动、依赖、配置 | `requirements.txt`、`.env.example`、`start*`、`compose.yaml` | Linux Docker 实际构建/部署；Windows/macOS 启动入口已提供，未在对应原生系统验证 |
| 设计、测试、学习记录 | `DESIGN.md`、`TEST_RECORD.md`、`LEARNING.md` | 均已交付；AI 辅助方式写在学习记录 |

## 12 个规定验收场景

| 场景 | 结论与证据 |
| --- | --- |
| 创建非空规则 | 真实模型和网页工具轨迹已验证 |
| 值域缺少允许值 | 真实模型追问已验证 |
| 补充允许值后创建 | 同会话真实模型已验证 |
| 运行刚才的规则 | 同会话工具调用生成独立执行 ID |
| 查询刚才结果与异常 | 回读保存快照并展示异常 ID/原值 |
| 一次请求两条规则 | 真实模型多次工具调用，分别汇总 3 / 2 条失败 |
| 不存在的表或字段 | 创建时拒绝且不保存 |
| 不存在的规则或执行 ID | 返回 404 |
| 数据变化与历史不变 | 独立 Docker/MySQL 测试，旧统计与样例不变 |
| 数据库异常 | 隔离 Docker 停库实测健康状态 unavailable、执行返回 503 |
| 空表 | 真实 MySQL 中 `demo_empty_orders` 执行规则：总数和参与数为 0，通过率 N/A；`tests/test_acceptance.py::test_empty_and_all_skipped` |
| 全部 NULL 的值域规则 | 全部跳过，参与数为 0，通过率 N/A |

## 演示前需了解的界限

本轮新增上传功能的浏览器上传、手动规则执行和工具参数绑定已验证；**上传数据的真实模型自然语言对话尚未重新验收**，因为当前 Docker 未配置模型密钥。原基准订单的真实模型闭环已有历史实测，详细记录在 `TEST_RECORD.md`。本应用面向本机单用户演示，不具备多人鉴权和全站规则扫描队列。首次 Docker 构建需要能访问镜像仓库和 Python 依赖仓库；本机在 PyPI 直连超时时使用本机代理构建已验证镜像。
