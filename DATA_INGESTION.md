# 数据接入：文件 → MySQL → 规则 → 执行快照

在首页“数据来源”选择 CSV / XLSX，点“预览文件”，查看样例后点“确认导入”。成功后自动选择上传数据集；可以输入自然语言，也可以展开手动创建规则。配置真实模型后才可使用自然语言；上传和手动运行不依赖模型密钥。

## 当前支持范围

订单数据，固定表结构。保留 demo_orders、demo_empty_orders、demo_null_orders、demo_orders_faker 四张 MySQL 表。上传数据写入同一个已配置的 MySQL 的 uploaded_orders 表，按 dataset_id 隔离。不支持任意外部数据库/任意表直接发现。

- UTF-8 CSV、单工作表 XLSX，最多 5 MiB、20000 条；XLSX 解压总量最多 30 MiB。
- 必需表头：order_id,customer_name,order_status；可选：amount,created_at。不接受未知列和重复列。
- order_id 是文件内唯一的正整数，最多 9007199254740991；不同数据集可使用相同订单 ID。
- customer_name 最多 255 字符，order_status 最多 32 字符；允许空值和不符合业务规则的状态，不自动修正。
- CSV 的空单元格是空字符串，字面量 `\N` 为 NULL；Excel 空单元格为 NULL。不接受 Excel 公式。
- amount 可为空，否则为 DECIMAL(10,2)；created_at 可为空，否则为无时区、精确到秒的 ISO 日期时间。
- 只有表头也是合法空数据集，运行规则显示无可校验数据。

## 接口清单

| 方法与路径 | 输入 | 输出/用途 |
| --- | --- | --- |
| GET /api/datasets/template.csv | 无 | 下载订单模板 |
| POST /api/datasets/preview | multipart/form-data：file | SHA-256、行数、前 5 行；不入库 |
| POST /api/datasets | multipart：file、expected_sha256 | 数据集 id、行数、reused；整份入库 |
| GET /api/datasets | 可选 before_id | 最新 100 份；用末条 id 继续翻页 |
| GET /api/datasets/{id} | 数据集 ID | 元数据、前 5 行 |
| POST /api/rules | 原字段 + table_name=uploaded_orders、dataset_id | 绑定数据集的新规则 |
| POST /api/chat | session_id、message、dataset_id、table_name | 使用当前选择的数据创建规则；已有规则保留原目标 |
| POST /api/rules/{id}/run | session_id 可选 | 新的 execution_id 和真实统计 |
| GET /api/results/{id} | 执行 ID | 保存的统计和异常样例，不重查业务表 |

HTTP 400：结构错误或预览哈希不匹配；404：数据集不存在；413：请求体超限；429：上传名额已满；503：数据库不可用。字段缺失或类型错误可能返回 FastAPI 的 422。

## 数据怎样写入

浏览器用 FormData 传文件，不能手写 multipart 的 Content-Type，否则会丢失 boundary：

```javascript
const form = new FormData();
form.append('file', file);
form.append('expected_sha256', previewed.sha256);
await api('/api/datasets', {method: 'POST', headers: {}, body: form});
```

`app/datasets.py:import_dataset` 先保存元数据，得到 dataset_id，再分批参数化写入订单，最后只提交一次事务：

```python
cur.executemany(
    'INSERT INTO uploaded_orders '
    '(dataset_id,order_id,customer_name,order_status,amount,created_at) '
    'VALUES (%s,%s,%s,%s,%s,%s)',
    [(dataset_id, *row) for row in parsed['rows'][offset:offset + 500]],
)
conn.commit()
```

循环每批 500 行减少单条 SQL 大小，**不是每批提交**。任一批失败会 rollback，元数据与明细一起回滚。所有文件行先通过结构校验，再进入写库阶段。SQL 表名固定，用户数据只作为参数，不拼进 SQL。

SHA-256 与文件类型的联合唯一约束保证同一文件重试、并发提交只得到一个数据集。重命名不产生副本。文件改变则生成新的 ID；旧规则仍绑定旧 ID。没有删除或替换上传数据的 API。

规则保存 dataset_id；执行时统计与异常样例都带 `WHERE dataset_id=%s`。两次查询在 MySQL REPEATABLE READ 一致性快照中完成。最终统计、样例、规则配置写入 quality_runs，之后按 execution_id 读取，不回查源数据。

## 并发：已做与待做

已做：单进程内同会话 Agent 串行；每条规则的一致性快照；上传每进程 2 个名额，满额返回 429；请求体上限在 multipart 解析前检查；上传事务与唯一约束；迁移用 MySQL 命名锁避免多进程同时 ALTER。

未做：跨进程同会话锁、全站校验扫描限额、持久任务队列、用户级配额。页面手动执行不经过 Agent 会话锁。

下一步优先统一所有 run_rule 入口的执行名额：单进程演示先用 BoundedSemaphore；多实例需共享队列或数据库槽位。队列引入后再增加排队状态、超时、取消和重试幂等键。事务解决读写一致性，不等同于限制同时运行的任务数量。

## 升级和边界

已有 MySQL 卷不重建、不重放 seed。新库的 `sql/schema.sql` 已包含上传表与 `dataset_id`；旧库可在本机 `/setup` 的“初始化演示库与订单”中临时提供管理员账号完成幂等升级，旧规则保持 NULL。缺少表时，应用账号如果具有 DDL 权限，也可在首次使用数据集时自动升级；表已齐全时普通应用账号只需数据读写权限。

当前仍是本机演示应用，没有多用户鉴权与租户隔离；dataset_id 用于业务数据隔离，不等于访问授权。不要直接将本机端口公开成多人生产服务。
