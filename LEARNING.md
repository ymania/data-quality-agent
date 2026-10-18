# 学习记录

此前不熟悉 Deep Agents 的调用方式。阅读 [Deep Agents 官方仓库](https://github.com/langchain-ai/deepagents) 和 [LangChain 的 Deep Agents 示例](https://github.com/langchain-ai/docs/blob/main/src/oss/langchain/quickstart.mdx) 后，确认 `create_deep_agent` 可接收自定义工具、显式模型和 checkpointer，返回可 `invoke` 的图。本项目把模型的“理解和编排”与确定性的 SQL 校验分开，并用 `thread_id` 关联同一会话。

遇到的关键问题是 MySQL 默认排序规则可能把 `new` 与 `NEW` 看作相等，甚至忽略尾随空格。实现中没有依赖默认 collation，而是把字段值和允许值都 `CAST(... AS BINARY)` 再比较，并在集成测试中加入小写与尾随空格样例。另一处边界是历史结果：结果接口只读当次 `quality_runs` 保存的快照，不重新扫描业务表。

这次使用 AI 编程助手生成代码骨架、页面和测试，人工核对需求中的统计口径、SQL 参数化、错误路径与历史数据不变性。基准流程已由 Hermes 在真实模型和 MySQL 8.4 环境中做过页面验收，记录见 [页面测试报告](docs/evidence/HERMES_TEST/测试报告.md)；后续加入的 Faker 万级数据也已完成数据库、真实模型和 HTTP 接口实测，详见 [测试记录](TEST_RECORD.md) 与 [问题三报告](docs/问题三_自然语言规则与后端接口报告.md)。本机代理变量 `ALL_PROXY=socks://...` 曾使模型客户端初始化失败，去掉该无效变量后可继续使用已有的 HTTP(S) 代理。

最后一轮学到两个工程边界。第一，数据库结构升级与订单写入是不同权限：新库由 `sql/schema.sql` 初始化，已有库由配置页临时管理员连接补列；应用账号在结构齐全后只需数据读写权限。第二，上传预览先检查格式，随后一次事务保存文件元数据和全部订单；数据库里的空字符串、NULL 和错误状态必须保留，才能交给质量规则准确检出。浏览器上传实测还遇到隔离 `/tmp` 路径无法被浏览器读取的问题，换成双方可见的工作区文件后，网页的预览、导入和规则执行全部通过。
