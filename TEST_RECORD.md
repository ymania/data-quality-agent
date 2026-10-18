# 验收记录

记录覆盖 2026-10-16 至 2026-10-18。下表是当前结论；后文按时间保留排障过程，早期写的“尚未实测”以更新的验收记录为准。基准页面证据见 [页面测试报告](docs/evidence/HERMES_TEST/测试报告.md)，自然语言接口和复现步骤见 [问题三报告](docs/问题三_自然语言规则与后端接口报告.md)。

| 开发要求中的场景 | 预期 | 当前证据与结论 |
| --- | --- | --- |
| 自然语言创建非空规则 | 保存规则并展示 ID | Hermes 浏览器实测通过 |
| 值域信息缺失、补充上下文 | 先追问允许值，补充后创建 | Hermes 真实模型实测通过 |
| 运行规则、组合任务 | 创建并运行两条规则，获得独立执行 ID | Hermes 真实模型工具轨迹实测通过 |
| 查询结果与“刚才”追问 | 返回对应统计与历史异常样例 | Hermes 浏览器实测通过；本轮真实模型同进程和跨进程追问均读取保存快照，工具轨迹可见 |
| 无效表、字段、规则/执行 ID | 明确拒绝或返回 404 | Hermes API 实测通过 |
| 数据变化后重跑 | 新结果变化，旧快照不变 | Hermes 集成测试实测通过 |
| 数据库异常 | 页面与 Agent 不报告成功 | 2026-10-18 隔离 Docker 停库实测：健康状态 unavailable，运行接口 HTTP 503，恢复后历史结果可读 |
| 空表、全部跳过 | 参与数为 0，通过率 N/A | `tests/test_acceptance.py::test_empty_and_all_skipped` 在真实 MySQL 上通过；上传空数据集也有测试 |
| 大小写、尾空格精确匹配 | 不自动归一化 | Hermes 集成测试实测通过 |
| 异常样例上限 | 统计覆盖全量，样例最多 20 条 | 集成测试覆盖 25 条新增异常；万级表两条规则分别发现 284/196 条异常，但各只保存 20 条样例 |
| 20 条基准数据 | 非空 20/20/17/3/0/85.00%；值域 20/19/17/2/1/89.47% | Hermes MySQL 8.4 实测通过；`sql/seed.sql` 仍固定 20 条 |

## Faker 批量数据扩展

`demo_orders_faker` 与 `demo_orders` 分开，因而不改变开发要求的 20 条基准。`scripts/generate_orders.py` 默认预览 10000 条，固定种子并分批写入。新增 `--verify`：对目标 ID 区间做数据库全量聚合，比较实际行数、客户名异常数、状态非法数和状态 NULL 数；可在已写入后只读复核。页面和 Agent 已将“模拟订单表”映射到该表，并复用同一套规则执行逻辑。

第一轮受限会话中，外网和本机 MySQL socket 均被沙箱阻止。全权限会话中，PyPI 可访问，项目 `.env` 中的 `dq_app` 账号成功连接 MySQL 8.4。由于该账号只有 SELECT/INSERT/UPDATE/DELETE 权限，管理员在本机执行 `sql/schema.sql` 创建 `demo_orders_faker` 后，固定种子成功写入 **10000 条**。生成器 `--verify` 的数据库全量统计与预览一致：客户名称异常 284 条、状态非法 196 条、状态 NULL 93 条。两条真实规则执行得到非空 **10000/10000/9716/284/0/97.16%**、值域 **10000/9907/9711/196/93/98.02%**（总数/参与/通过/失败/跳过/通过率），各保存 20 条异常样例；原 `demo_orders` 仍为 20 条。

真实模型在新表上依次调用 `create_quality_rule`、`run_quality_rule`、`get_quality_result`；同会话追问和跨进程追问有 `get_quality_result` 工具轨迹。`POST /api/chat`、`GET /api/schema`、`GET /api/rules/{id}/latest`、`GET /api/results/{id}` 返回 200。`tests/test_generator.py` **2 项通过**，`tests/test_acceptance.py` **4 项通过**，JavaScript 语法和 Python 编译通过。本机 `ALL_PROXY=socks://...` 会使模型客户端初始化失败；运行服务时去掉该环境变量后模型调用成功。MySQL 完全断线的页面场景仍未实测。

复现扩展验证：

```bash
cd '/home/why/codex/date agent/data-quality-agent'
mysql -u root -p < sql/schema.sql
.venv/bin/python -m pip install --index-url https://pypi.org/simple 'Faker==40.39.0'
.venv/bin/python -m scripts.generate_orders --rows 10000 --seed 20261016
.venv/bin/python -m scripts.generate_orders --rows 10000 --seed 20261016 --write --verify
.venv/bin/python -m pytest -q tests/test_generator.py tests/test_acceptance.py
```

若 ID 1–10000 已写入，跳过 `--write`，改用 `--verify` 只读核对。网页基准流程已有 Hermes 截图；万级表本轮完成了数据库、真实模型及 HTTP 接口实测，尚未单独补拍浏览器截图。

## 2026-10-17 可视化启动与配置扩展

在 `/home/why/codex/date agent/data-quality-agent` 运行 `./start.sh`，启动器复用现有 `.venv`，在 `127.0.0.1:8000` 启动 FastAPI 并打开 `/setup`。浏览器确认配置页显示 MySQL 与模型状态，已保存的模型密钥仅显示“已保存”，不回显原值；本机 `.env` 权限为 `0600`。通过页面把旧模型名更新为 `deepseek-flash`，密钥输入框留空后原密钥继续可用，无需重启。

真实浏览器对话完成组合任务：新建规则 **#44 状态值域**、**#45 客户名非空**，执行 **#56**、**#57**，分别得到 **20/19/17/2/1/89.47%** 与 **20/20/17/3/0/85.00%**，异常 ID 分别为 **4、5** 与 **1、2、3**；工具轨迹包括创建、运行和读取结果。继续问“刚才有哪些异常订单？”后，页面展示本会话两次执行的原始字段值，轨迹可见 `get_quality_result`。`tests/test_acceptance.py` 与新 `tests/test_settings.py` 合计 **6 项通过**；新 JS、Python 和 Bash 语法检查通过。

## 2026-10-17 本轮补全验证

本轮在隔离副本中修复代理选择与真实模型测试、组合任务的“刚才”关联、失败时工具轨迹保留、规则详情和分页、页面按钮进入会话轨迹，并增加 Docker Compose 交付文件。原项目的 `.env` 没有复制到发布包，也没有在测试输出中打印密钥。

真实模型连通测试返回 `connected=true, tool_calling=true`。对现有 20 条 `demo_orders` 发出“检查订单客户名称不能为空，订单状态只能是 NEW、PAID、CANCELLED，创建后运行，并展示异常订单”，Agent 真实工具轨迹依次包含 schema、两次创建、两次执行、两次结果读取。保存规则 **#46、#47**、执行 **#62、#63**：客户名异常 **3 条**（订单 1=NULL、2=空串、3=纯空格），状态异常 **2 条**（订单 4=UNKNOWN、5=REFUNDED）；通过率分别为 **85.00%** 和 **89.47%**。同会话追问“刚才有哪些异常订单？”再次读取该任务的两条执行快照并准确列出以上样例。

`tests/test_agent_resilience.py`、`tests/test_settings.py`、`tests/test_generator.py` 共 **8 项通过**。修正验收测试加载本地配置后，`tests/test_acceptance.py` **4 项通过**，其中重新插入异常数据会得到新统计，两个旧执行 ID 的统计与样例均保持字节一致；空表和全部跳过的通过率为 `null`。前端两个 JavaScript 文件通过 `node --check`，Compose YAML 解析通过。Docker 命令未安装，因此容器实际启动未验证；MySQL 整体断线场景仍未实测。


## 数据 Agent 回答精简

新增按任务区分的简洁回答规范。常规历史结果查询从真实工具结果生成固定短行，解释类和混合请求继续使用模型回答。针对样例截断、空分母、原始空值、重复执行及失败保留的测试通过；`tests/test_agent_resilience.py` 共 7 项通过。真实模型读取 #62/#63 的两轮测试确认工具查询正常，也暴露了纯提示词可能产生冗余自我修正，因此增加固定格式。

## 2026-10-17 第二轮暴力测试（并发/模糊/安全/降级/大数据）

四阶段实测，证据与报告在 `HERMES_TEST/bruteforce_20261017/`（原本机扩展证据目录，未纳入精简交付包）（测试报告 + 各阶段 JSON + 可复现脚本）。结果：并发风暴全绿（同规则 40 路并发运行 147ms、统计一致、无卡 RUNNING；同会话对话正确串行）；109 项模糊/安全用例 0 个 500（伪造 Origin/Host 403、无 CORS 泄漏、静态路径穿越 404、注入全部 400、前端无 innerHTML 注入面）；降级演练（隔离实例+模拟模型）验证死库→干净 503、垃圾模型→诚实 failed、无工具模型→设置页检出、坏参数工具调用→轨迹保留错误不谎报；大数据量 10 万行追加+11 万行运行 39ms/20 路并发 ~105ms，清理后基准复原（10000 行/284 异常）。

修复 2 个缺陷：session_id 超长（>64）在建规则/运行规则时返回误导性 503 并阻断操作 → 请求模型加 max_length=64，现返回 422（app/main.py）；/api/settings 静默吞掉未知配置项返回 200 → SettingsRequest 加 extra="forbid"，现返回 422。新增 `tests/test_bruteforce_regressions.py` 5 项回归，pytest 20/20。服务已重启加载修复。

遗留观察：应用无删除规则接口，测试产物堆积规则库（本轮 50→121 条，命名可识别）；聊天路径不单独检出"模型不支持工具调用"；initialize-database 不区分连接失败与认证失败；MySQL 真实停库演练因本机多项目共用未做（死端口实例已覆盖同一代码路径）。


## 2026-10-17 Docker 交付验收

环境：Ubuntu 26.04 x86_64；Docker 29.1.3；Compose 2.40.3；Buildx 0.30.1；镜像 Python 3.12.15、MySQL 8.4。应用镜像实际安装 Deep Agents 0.7.28、langchain-openai 1.7.2、FastAPI 0.143.3、PyMySQL 1.2.3。

本轮修正：独立 `.docker.env` 自动生成随机密码；无需分发开发者 `.env`；Windows/macOS/Linux 启动入口；缺少 Compose/Buildx/引擎权限时提前报错；HTTP 与数据库健康检查；显式 PyMySQL RSA 认证依赖；镜像包含数据生成脚本；启动等待就绪后才打开网页；配置文件丢失但数据卷存在时拒绝重置密码。

已完成：

- `docker compose ... config --quiet` 通过。
- Bash 语法检查、Linux desktop 文件验证、含空格目录的 desktop 命令解析与启动验证通过。
- 6 个启动器单元测试通过：无引擎权限、缺少 Buildx、重复启动/端口修改、配置丢失保护、构建失败不报就绪、非法端口；使用模拟 CLI，不冒充容器测试。
- 应用镜像真实构建成功；独立容器内 `import app.agent` 成功。
- 随机独立项目 `dq-verify-73ea17bf9444` 的真实 Docker/MySQL 集成验收通过，测试结束后其容器和测试卷已清理：
  - 首次自动建表、导入 20 条订单。
  - 非空规则失败 3 条，ID 1/2/3；值域规则失败 2 条，ID 4/5，跳过 1 条。
  - 插入一条客户名 NULL、状态 BROKEN 的订单后，总数 21，新失败数 4/3；旧执行结果与样例完全一致。
  - `down` 后重新 `up`，规则、执行快照、会话记录、网页保存的模型配置、21 条订单仍在；没有重新导入种子数据。
  - 停掉 MySQL 后，健康接口准确报告 unavailable，运行规则返回 HTTP 503；恢复 MySQL 后历史快照仍可读。

本机环境排障：Docker Hub 直连超时，通过既有 HTTP 代理 127.0.0.1:7892 解决；系统缺少 Buildx，从 Ubuntu 软件包安装到当前用户 Docker 插件目录；旧进程组权限通过临时调整 socket 组解决。这些本机设置未放入客户交付包。

范围：本轮容器测试未调用真实模型，模型配置持久化使用无效域名和虚拟测试 key；自然语言和追问的真实模型测试见此前记录，不能据此宣称本轮已重新验收模型联网。Windows/macOS 启动文件已提供，未在对应原生系统运行；未验证 ARM、离线安装或公网部署。首次构建仍需联网，Python 依赖仍使用项目中的版本范围。


### 交付包与正式入口复验

- 原项目 `start-docker.sh` 已实际启动 `dq-desktop`，页面 `http://127.0.0.1:18000/setup` 返回 200，数据库健康；订单数 20，模型状态 unconfigured，未继承开发者模型密钥。
- 53 文件交付 ZIP 完整性检查通过；未包含 `.env`、`.docker.env`，扫描未发现原项目真实密钥（公开示例占位值不算私密凭据）。
- ZIP 解压到独立目录后，内置 `verify_docker.py` 在 `dq-verify-c075172a769d` 再次完成全流程并返回 0，包含异常原始字段值和 85.00 / 89.47 通过率断言；测试容器和测试卷已清理。
- 正式 `dq-desktop` 应用继续运行，配置页等待使用者填写自己的模型信息。

## 2026-10-18 网页数据接入

新增 CSV / XLSX 预览与原子导入、dataset_id 规则绑定、上传请求大小与并发限制。

- 本地启动器/配置/生成器测试：10 passed。
- 独立 MySQL 8.4 Docker 中上传、原验收、Agent 恢复、输入回归测试：29 passed。
- 验证不同数据集相同订单 ID 不串查；同时提交相同文件复用一个 ID；第二批写入模拟失败后前 500 行及元数据全部回滚。
- 验证空上传数据集、状态全部 NULL 的统计；已有执行统计与异常样例在源数据变化后不变。
- 原 20 条基准订单仍为非空异常 3 条、值域异常 2 条；新增异常后为 4 / 3，旧快照保持原样。
- 自然语言选中数据集的工具参数绑定已测试；当前 Docker 未配置模型密钥，未进行真实模型端到端验收。
- Python 编译检查和 JavaScript 语法检查通过。

重现：`python3 scripts/verify_docker.py` 创建独立临时 Compose 项目，验证后只删除该项目及其卷。可用 `DQ_VERIFY_IMAGE=<本地镜像名>` 跳过构建。

### 网页与部署收尾

- 本机新版容器健康运行，地址 http://127.0.0.1:18000。普通构建因 PyPI 直连超时失败，本次使用经过隔离验收的本地镜像部署；首次联网构建仍要求能访问依赖仓库。
- 网页实测完成 CSV 预览、导入数据集 #1、创建规则 #1、执行 #1：3 条订单，1 条通过、2 条失败，异常样例 order_id=2 的空字符串和 order_id=3 的 NULL。保留这份标注“网页验收”的测试数据供查看。
- 页面静态资源增加版本号，修复升级后沿用旧 JavaScript 的问题。
- 浏览器上传测试须选择真实工作区文件；隔离 /tmp 文件浏览器不可读，曾导致 Failed to fetch。更换测试文件路径后通过，无需修改上传接口。
- 容器重建数据持久性、断库返回 503、恢复后旧快照保持不变：隔离 Docker 验证通过。

## 2026-10-18 最终隔离验收与空表复核

最终镜像在独立 MySQL 8.4 容器中运行 `tests/test_uploads.py`、`tests/test_acceptance.py`、`tests/test_agent_resilience.py` 和 `tests/test_bruteforce_regressions.py`，**30 passed**。其中 `test_empty_and_all_skipped` 对 `demo_empty_orders` 执行非空规则：总数 0、参与数 0、通过率 `null`、异常样例空；对 `demo_null_orders` 执行值域规则：总数 3、参与数 0、跳过数 3、通过率 `null`。上传空数据集与全部 NULL 数据集也通过 `test_uploaded_empty_and_all_skipped`。页面将 `null` 显示为 `N/A`，并显示“无可校验数据”。

同次 Docker 验证还通过 20 条基准数据异常数 3 / 2、插入异常后新结果 4 / 3 且旧快照不变、容器重建后状态保留、停库 HTTP 503 及恢复。测试环境已清理。文档与目录调整不修改上述业务代码；本机正在运行的演示容器在此次记录后没有重建。
