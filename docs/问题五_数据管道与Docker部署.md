> 本文保留早期的数据管道学习概览。交付版的实际上传接口见 [数据接入说明](../DATA_INGESTION.md)，Docker 启动见 [部署说明](../DOCKER_DEPLOY.md)，学习总结见 [学习记录](../LEARNING.md)。

# 问题五：数据管道、Kafka、Spark、Airflow 与 Docker

## 像讲故事一样理解

把订单想成一张张写好的纸条。**数据管道**是纸条从业务系统送到检查员面前的整条路线：接收、清洗、保存、检查和展示，每一段都要知道输入、输出和失败后的处理。

- **Kafka** 像有编号的收件箱：订单变化先成为事件，生产者写入主题，消费者按自己的进度读取。它解决多个系统异步收发事件的问题。[Apache Kafka 介绍](https://kafka.apache.org/intro/)
- **Spark** 像能同时处理许多纸条的分拣台：把事件解析、去重、转换、汇总。Structured Streaming 可持续处理流数据，也可用相近的 DataFrame 写法处理批数据。[Spark Structured Streaming](https://spark.apache.org/docs/latest/streaming/index.html)
- **Airflow** 像值日表：按顺序或时间安排“取数 → 转换 → 质量检查 → 通知”这些任务，并记录哪一步失败。它的 Dag 表示任务及依赖关系。[Airflow Dags](https://airflow.apache.org/docs/apache-airflow/stable/concepts/dags.html)
- **数据质量 Agent** 像听懂检查要求的管理员：用户说什么要检查，Agent 选择创建、运行和查询工具；真正的判断与数字来自后端和 MySQL。
- **Docker Compose** 像把应用和数据库各装进一个有明确连接方式的盒子，并用持久卷保存数据库。Compose 使用 YAML 描述服务、网络和卷。[Docker Compose](https://docs.docker.com/compose/intro/compose-application-model/)

## 当前项目的实际路线

```text
浏览器自然语言或按钮
  → Deep Agents / FastAPI
  → 已保存的质量规则
  → MySQL demo_orders 的一致性快照查询
  → 独立的质量执行记录和异常样例
  → 浏览器统计与追问
```

当前 20 条订单在 MySQL 中，已经足以完成原始作业。Kafka、Spark、Airflow **尚未接入当前项目**。引入它们的前提是订单需要持续从其他系统流入、数据量或转换复杂度增加，或者需要定时运行质量规则。

## 将来怎样接入

### Kafka：先确定事件契约

上游业务系统把订单新增、修改事件写入 `orders.events` 主题。每条消息至少带 `order_id`、事件类型、事件时间、来源版本及相关字段；消费者确认写入目标表后再推进读取进度。仅靠“读到一次消息”不能保证 MySQL 最终只写一次，消费者需要按订单 ID 与来源版本设计幂等写入。当前演示表尚无来源版本列，因此这一步属于未来的数据模型扩展。

### Spark：把订单事件变成可检查的数据

Spark 作业从 Kafka 读取，按约定解析字段、隔离无效消息、去重，再批量写入 MySQL 业务表或专门的待检表。Spark 的 checkpoint 管理处理进度；写入 MySQL 时仍需用主键、来源版本或批次键约束重复写入。**质量规则的合法值域依旧来自业务确认，不能让 Spark 根据当前出现的值自动推断。**

### Airflow：编排批次与质量检查

可以定义如下 Dag：

```text
订单入库完成 → 核对入库行数 → 运行客户名称规则和订单状态规则
          → 读取两个 execution_id → 根据保存的统计生成报告
```

调度器应调用现有 `quality.run_rule(rule_id)` 业务服务，生成独立的执行记录；报告按具体 `execution_id` 读取快照。若通过 HTTP 调用，需要为调度器设计内部认证。当前应用只为本机单人演示设计，没有提供供外部调度器使用的认证接口，因此这里是接入方案，尚非现成功能。

## Docker 部署当前演示应用

项目根目录已提供 `Dockerfile` 和 `compose.yaml`。先复制 `.env.example` 为 `.env`，至少填写 `MYSQL_PASSWORD`；需要使用 Agent 对话时再填写模型名称、接口和密钥。之后运行：

```bash
docker compose up --build -d
docker compose ps
docker compose logs -f agent
```

浏览器打开 `http://127.0.0.1:8000/setup`。在全新 MySQL 数据卷中，官方 MySQL 容器会按顺序执行建表和演示数据 SQL。以后重启继续使用同一数据卷，不再重复导入。停止使用 `docker compose down`；保留卷才能保留历史规则和执行结果。

容器里的 `localhost` 指容器自己。应用连接数据库使用 Compose 服务名 `mysql`，模型或代理若运行在宿主机，则要填写容器能访问的主机地址，并在设置页测试工具调用。Web 端口绑定宿主机环回地址；当前配置页适用于本机演示。

## 学习与实践顺序

先掌握当前应用的 **规则 → 执行 → 快照**；然后用 Docker 运行同一应用；有外部实时订单来源时再引入 Kafka；数据转换真正需要并行计算时引入 Spark；需要按时执行或编排依赖时引入 Airflow。每新增一层，都继续用同一组订单统计和旧快照不变性测试验证结果。
