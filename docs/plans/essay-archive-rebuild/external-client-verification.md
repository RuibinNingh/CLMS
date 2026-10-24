# 外部客户端与模拟自测

记录日期：2026-10-11（Asia/Shanghai）。用户当前选择“先写脚本模拟自测”。本阶段执行官方 MCP SDK 客户端经真实 TCP 端口初始化、tools/list、tools/call、页图像读取，脚本按精确版本/hash 生成非真实模型评价，再由真实网页审核入档。

这证明协议、权限、媒体交付与审核闭环，不证明外部模型理解图像。没有真实 AI 账户/模型识图证据，E01–E05 不标 pass。

| 编号 | 当前状态 | 必需补验 |
| --- | --- | --- |
| E01 图片识图 | NOT_RUN_REAL_AI | 记录实际客户端/版本、鉴权；图片含独特词且文件名/元数据不含词，模型准确描述内容 |
| E02 PDF 指定页 | NOT_RUN_REAL_AI | 多页视觉内容不同，模型区分指定源页及稿件页映射 |
| E03 评价闭环 | SIMULATION_ONLY | 实际模型工具调用→pending回执→网页截图→精确版本正式评价 ID |
| E04 分类提案 | SIMULATION_ONLY | 实际外部客户端提交自定义分类、网页批准、正式 ID 可使用 |
| E05 越权失败 | AUTOMATION_ONLY | 实际客户端尝试批准/伪造actor失败、无业务变化 |

自动化实际结果见 `artifacts/verification.json` 中 mcp-protocol/browser/security 门禁和各日志；该表中的 SIMULATION_ONLY 描述验证类型，具体是否通过以执行报告为准。

## 人工补验记录模板

- 日期/时区、客户端名称和版本、模型名称：
- MCP endpoint（脱敏）、协议协商版本、Bearer/OAuth 支持情况：
- 测试档案/Attempt/Version ID、manifest hash、snapshot hash：
- 图片/PDF 校验词（保存在私有证据，不能出现在工具元数据）：
- 真实模型识图文字与工具调用记录、待审 operation ID：
- 网页决定 revision/digest、正式 evaluation/category ID：
- 越权请求与无变化查询证据：
- 限制/失败、脱敏截图/日志路径：

不保存真实 token、Cookie、带权限 URL 或私人作文原件到 Git。若客户端不支持自定义 Bearer，记录准确失败，不声称普遍兼容，不自动增加范围外 OAuth 服务。

## 0.10.2 附件入口补验

新增 `upload_attachment` 的ChatGPT原生文件参数及 `upload_asset` 字节上传。自动化通过真实MCP端口发送文件参数/字节，受控下载响应不代表宿主已实际发出附件。实际客户端须刷新工具列表，然后用自己的图片和多页PDF确认宿主提供file对象、原件哈希/页数正确、返回staged，再提交pending并网页审核。未获得此证据前，不把ChatGPT真实附件透传或E01–E05记为通过。
