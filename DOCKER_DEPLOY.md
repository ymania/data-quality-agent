# 给另一台电脑使用：Docker 一键启动

## 接收者只需做什么

1. 安装并打开 [Docker Desktop](https://docs.docker.com/get-docker/)（Windows 使用 Linux containers）；Linux 也可使用 Docker Engine + Compose v2 + Buildx。当前账户必须能运行 `docker info`。
2. 将 `data-quality-agent.zip` 完整解压到自己的目录，不要在压缩包里直接运行。
3. 启动：Windows 双击 `start-docker.cmd`，macOS 双击 `start-docker.command`，Linux 双击 `启动Docker应用.desktop`（首次选择“允许启动”）或执行 `bash start-docker.sh`。
4. 首次需要联网下载 Python、MySQL 镜像与 Python 依赖。成功后自动打开 `http://127.0.0.1:18000/setup`；浏览器没打开时手动访问该地址。
5. 数据库已就绪。只填写自己的模型接口地址、模型名称、API Key，保存并点击“测试模型和工具调用”。测试会消耗少量模型用量。没有模型密钥时，页面创建规则和按钮运行仍可使用。

> “一键”指 Docker 可用后的应用部署。首次安装 Docker、配置模型账号仍由使用者完成。交付包不包含开发者密钥、原电脑数据库或历史记录。

## 验收业务

输入：“检查订单客户名称不能为空，订单状态只能是 NEW、PAID、CANCELLED，创建后运行。”

| 规则 | 总数 | 检查数 | 通过 | 失败 | 跳过 | 异常 ID |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| 客户名称非空 | 20 | 20 | 17 | 3 | 0 | 1、2、3 |
| 订单状态值域 | 20 | 19 | 17 | 2 | 1 | 4、5 |

追问“刚才有哪些异常”，应引用本会话的执行记录。保存规则与模型配置后停止、重新启动，应仍能查询之前的规则和执行快照。

## 启动器做了哪些事

```text
检查 Docker → 生成数据库随机密码 → 校验 Compose 配置
→ 构建 Python 应用镜像 → 启动 MySQL → 首次建表、导入订单
→ 启动 Web → 检查 HTTP 和数据库 → 打开配置网页
```

- `Dockerfile`：Python 3.12 应用及脚本；无需宿主机安装 Python。
- `compose.yaml`：MySQL 8.4 + 应用，数据库不向宿主机映射端口。
- `.docker.env`：每台电脑独立生成的数据库密码和 Web 端口。Linux/macOS 权限为 600。不加载开发模式的 `.env`。
- `dq-desktop_dq_mysql` 卷：订单、规则、执行快照、会话记录。
- `dq-desktop_dq_config` 卷：网页保存的模型与数据库配置。
- 项目名固定为 `dq-desktop`，移动解压目录后也能找到相同数据卷；同一台电脑默认只部署一套。
- 应用健康检查确认 HTTP 可达且数据库结构就绪；未配置模型不会阻止打开设置页。

## 改端口、停止与日志

在解压后的项目目录执行。18000 被占用时，例如改为 18001：

```bash
# Linux / macOS
bash start-docker.sh 18001
```

```powershell
# Windows 终端
.\start-docker.cmd -Port 18001
```

以下命令三种系统均可使用：

```bash
# 查看容器状态
docker compose -p dq-desktop --env-file .docker.env ps
# 查看应用日志
docker compose -p dq-desktop --env-file .docker.env logs --tail 100 agent
# 停止并移除容器，保留数据卷
docker compose -p dq-desktop --env-file .docker.env down
```

重新运行启动脚本即可恢复。**不要给停止命令添加 `--volumes` 或 `-v`，它会删除数据库和配置卷。** 不要删除或分享 `.docker.env`；如果文件丢失但数据卷仍存在，启动器会拒绝生成新密码，要求恢复原文件。只拷贝解压目录不会迁移 Docker 数据卷，迁移既有数据需要另外备份数据库和配置卷。

## 常见卡点

| 现象 | 处理 |
| --- | --- |
| 缺少 Buildx | Docker Desktop 更新至带构建插件的版本；Ubuntu 安装 `docker-buildx` |
| 没有 Docker / 无法连接 | 安装、启动 Docker；Linux 确认当前用户拥有 Docker 权限 |
| 镜像拉取或 pip 下载失败 | 检查 Docker 的联网、代理设置；修复后重新运行，不要删数据卷 |
| 端口被占用 | 用上面的端口参数重试 |
| macOS 提示脚本不能执行 | 在项目目录用 `bash start-docker.sh` 启动 |
| Windows 找不到脚本 | 先完整解压，避免只提取 `.cmd` 文件 |
| 网页数据库无法连接 | 自动部署的主机应为 `mysql`、端口 3306、用户 `dq_app`；不要改成本机的 `127.0.0.1` |
| 宿主机模型/代理地址连不上 | 容器的 localhost 指自己。Docker Desktop 可按官方说明使用 `host.docker.internal`；本地服务还需允许来自容器的连接。Linux Engine 需另行配置宿主机访问地址 |

## 开发者验证

普通使用者不必运行。开发者可用 Python 3 执行：

```bash
python3 scripts/verify_docker.py
```

脚本生成独立的随机 Compose 项目名、端口和密码，验证真实 MySQL 的首次初始化、3/2 异常样例、数据变化、旧快照、容器重建后的持久化以及数据库停机失败提示，最后清理它自己创建的测试容器和测试卷。它不操作 `dq-desktop`，也不需要模型密钥；自然语言模型调用仍需在网页配置后单独验收。

测试结果见 `TEST_RECORD.md`。启动脚本单元测试使用模拟 Docker CLI，只能证明启动器的失败处理和幂等性；不能代替实际容器构建、运行测试。Windows、macOS 原生运行需在对应系统补验。

配置语义参考：[Compose 环境变量](https://docs.docker.com/compose/how-tos/environment-variables/variable-interpolation/)、[启动等待健康状态](https://docs.docker.com/reference/cli/docker/compose/up/)。当前 Python 依赖使用版本范围，首次构建需要在线解析；尚未提供离线镜像包或跨平台镜像仓库发布。
