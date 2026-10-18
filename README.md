# 数据质量 Agent

浏览器中的订单质量检查应用。用户用自然语言创建、运行规则并追问结果；LangChain Deep Agents 负责理解与调用工具，Python/MySQL 负责真实校验与保存历史。页面按钮复用同一业务服务。

## 5 分钟演示

1. 按下方方式启动，打开首页。要使用自然语言，先到 `/setup` 填写支持工具调用的模型名称、接口地址和 API Key，并点“测试模型和工具调用”。手动创建、运行规则不需要模型密钥。
2. 在首页选择 **MySQL · demo_orders**，输入：

   > 检查订单客户名称不能为空，订单状态只能是 NEW、PAID、CANCELLED，创建后运行，并告诉我异常订单。

3. 查看两条规则、两个执行 ID 与异常样例。客户名规则：20 条中失败 3 条（ID 1、2、3），通过率 85.00%；状态值域规则：19 条参与、2 条失败（ID 4、5）、1 条跳过，通过率 89.47%。
4. 继续问“刚才有哪些异常订单？”，再查看保存的执行记录。修改业务数据并重跑后，旧执行的统计和样例仍保持原值。
5. 在“数据来源”上传 CSV 或单工作表 Excel，预览后确认导入。页面自动选中独立数据集；新规则按 `dataset_id` 限定扫描范围。下载页面上的模板即可试用。

缺少值域允许值时 Agent 应追问，不会替业务人员猜测；所有字段值由 MySQL 校验，不由模型判断。

## 一键启动

| 环境 | 入口 | 页面 |
| --- | --- | --- |
| Windows + Docker Desktop | 双击 `start-docker.cmd` | `http://127.0.0.1:18000` |
| macOS + Docker Desktop | 双击 `start-docker.command`，或运行 `bash start-docker.sh` | 同上 |
| Linux + Docker Engine、Compose v2、Buildx | 双击 `启动Docker应用.desktop`，或运行 `bash start-docker.sh` | 同上 |
| 本机 Python 3.11–3.14 + MySQL 8.0+ | 双击 `启动数据质量Agent.desktop`，或运行 `./start.sh` | `http://127.0.0.1:8000` |

Docker 首次启动自动生成 `.docker.env` 数据库密码、创建 MySQL 卷并装载 20 条演示订单；需要联网下载镜像与 Python 依赖。重启保留数据和设置。模型信息在本机 `/setup` 页面填写。无需另装 Python/MySQL。详见 [Docker 部署与排错](DOCKER_DEPLOY.md)。

本机 Python 启动首次创建 `.venv` 并安装依赖。配置页填写 MySQL 连接参数；点击“初始化演示库与订单”，可临时输入有建表权限的管理员账号，管理员密码不会保存。已有库升级会补齐上传表和规则的 `dataset_id` 列，保留已有订单、规则与执行快照。普通应用账号可只授予 `SELECT, INSERT, UPDATE, DELETE`；执行新库建表或旧库升级时需要管理员。也可由管理员运行 `sql/schema.sql` 建新库；旧库仍应在配置页执行一次初始化升级。`sql/create_user.sql` 是示例，使用前修改占位密码。

`.env.example` 给出环境变量示例。页面保存的密钥写入本地 `.env`，不回显原值；`.env` 和 `.docker.env` 不纳入交付包或 Git 仓库。

## 范围和接口

两类规则：`NOT_NULL` 将 NULL、空字符串、纯空格判为失败；`ENUM` 对非 NULL 字符串按原始字节精确比较，NULL 计入跳过。允许的 MySQL 表：`demo_orders`、`demo_empty_orders`、`demo_null_orders`、`demo_orders_faker`；上传订单使用 `uploaded_orders` 并绑定 `dataset_id`。目前只校验字符串业务字段。Agent 内置“订单表”“模拟订单表”“客户名称”“订单状态”别名；网页选择上传数据集后，新建规则以该数据集为目标，运行已有规则仍按保存的配置执行。

核心 API：`POST /api/chat`、`GET/POST /api/rules`、`POST /api/rules/{id}/run`、`GET /api/results/{id}`。上传 API 和写入代码见 [数据接入说明](DATA_INGESTION.md)；所有接口可在 `/docs` 查看。`GET /api/results/{id}` 返回已保存快照，不重新扫描当前订单。

## 测试与限制

```bash
python3 scripts/verify_docker.py   # 独立 Docker/MySQL：建库、规则、上传、快照、重启、断库
.venv/bin/python -m pytest -q tests/test_settings.py tests/test_deployment.py tests/test_generator.py
node --check app/static/app.js
```

Docker 验证脚本创建并清理**自己的**临时项目，不触碰正式 `dq-desktop` 数据卷。预期与实际结果、尚未复验之处见 [交付核对表](DELIVERY_CHECKLIST.md) 和 [测试记录](TEST_RECORD.md)。[设计说明](DESIGN.md)解释工具编排与统计口径；[学习记录](LEARNING.md)说明参考资料、遇到的问题及 AI 编程助手的使用方式。补充的面试讲解、专题报告和截图证据集中在 [docs](docs/README.md)。

当前是本机单用户演示，没有登录、租户隔离或任务队列；不要将端口直接开放为多人公网服务。模型须支持 OpenAI 兼容的工具调用。当前 Docker 实例未配置模型密钥，因此本轮上传数据的自然语言流程只验证了工具参数绑定，未重新做真实模型调用；原 20 条订单的真实模型组合任务与追问已有独立验收记录。上传文件最大 5 MiB、20000 行，字段契约见数据接入说明。Windows/macOS 启动入口已提供，实际容器验收在 Linux 完成。
