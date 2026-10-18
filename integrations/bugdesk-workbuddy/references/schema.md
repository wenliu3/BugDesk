# 本地建议协议

该技能需要正在运行的新版 BugDesk。用户在 BugDesk 开启 WorkBuddy 连接，提示提供本地连接文件路径；无需 Python、Node 或禅道账号。优先显式使用 Windows PowerShell 5.1：

```powershell
powershell.exe -NoProfile -File '<技能目录>\scripts\bugdesk.ps1' -Action context -ConnectionFile '<用户提示中的连接文件>'
powershell.exe -NoProfile -File '<技能目录>\scripts\bugdesk.ps1' -Action stage -ConnectionFile '<用户提示中的连接文件>' -InputFile '<本地UTF8建议JSON>'
```

将实际路径作为独立参数传入。表格内容写入 JSON 文件，不插入命令行。

已安装且获准使用的 PowerShell 7 可以将上述 `powershell.exe` 换成 `pwsh`；脚本同时接受两版 JSON 解析器产生的整数类型，不接受浮点数或字符串形式的 schema/摘要计数。

保持公司的 PowerShell 执行策略。脚本被策略拦截时报告限制，使用公司批准的执行方式；不要设置全局策略或添加 Bypass。

## 连接与上下文

连接文件由 BugDesk 创建，包含 `schema:1`、`url`、`instance`、`token`、`expires_at`。地址必须是 `http://127.0.0.1:<端口>/`；不能换成公司地址或远程地址。文件和 token 仅在本机使用，不复述或上传。`expires_at` 是带时区的 ISO 8601 字符串。

脚本先读取 `/health`，确认 `app=BugDesk` 和 `instance` 一致，再读取 `GET /api/workbuddy/context`。仅后一个请求携带 `X-BugDesk-WorkBuddy-Token`。上下文提供 `context_id` 及当前批次的草稿资料；以实际响应的 ID 为准，不自行生成或使用上一批的 ID。

网络 JSON 响应最多 8 MiB，用于读取包含多条完整草稿的上下文；超过时明确停止，不截断事实。该额度不扩大建议输入限制：连接文件、建议 JSON 文件和 `stage` 请求仍各限 1 MiB。

## 暂存输入

`POST /api/workbuddy/stage` 接收以下 UTF-8 JSON。文字字段均为字符串，可以留空；换行使用 JSON 转义或 JSON 序列化保留。`candidate_bug_ids`、`source_actual`、`review_notes` 可省略；BugDesk 与配套技能的首个正式版本 1.0.0 均支持这些字段。

```json
{
  "context_id": "从本次context响应取得",
  "rows": [
    {
      "case_id": "PD10000-CA10002",
      "title": "全程语音控制",
      "group": "示例用例/1.0版本/示例播放器",
      "tester": "示例测试员",
      "date": "10月13日",
      "preconditions": "视频播放过程中",
      "steps": "1.语音：先别播了",
      "expected": "1.播放暂停",
      "actual": "会返回到上一界面",
      "source_actual": "【厂商差异】【1.0需求版本】【示例播放器】会返回到上一界面",
      "review_notes": [],
      "suggested_bug_id": "从context草稿取得的唯一对应ID",
      "match_reason": "用例及草稿都记录语音‘先别播了’后返回上一界面。",
      "candidate_bug_ids": []
    }
  ]
}
```

没有唯一匹配时，`suggested_bug_id` 留空，在候选数组列出现有草稿 ID，理由说明需用户确认。`title` 是原用例名称，仅作来源信息，不表示要改写 Bug 标题。空的 `actual` 必须由用户补充事实。

一次 1–300 条，JSON 文件不超过 1 MiB。四项事实每项最多 20,000 字；用例 ID、人员最多 200 字，名称 1,000 字，分组 2,000 字，日期 100 字，匹配理由 1,000 字。每条用例最多列出 20 个候选 Bug ID；候选过多时说明无法缩小范围，不能随意选定一条。输入不包含附件路径、状态、优先级、审核标记或提交命令。

`source_actual` 是原始失败备注，最多 20,000 字；`review_notes` 是待确认事项的字符串数组，最多 20 条，每条最多 2,000 字。它们只供核对，不填入 Bug 的实际结果。对新版协议不兼容时先提示更新 BugDesk，不把待确认事项塞回 `actual`。

## 实际结果的整理

按失败用例的步骤理解触发动作，以备注中明确记录的现象为依据，组织自然、独立可读的结果描述。保留测试含义，不需要逐字复制备注。只有预期结果或“失败”状态而没有现象时，留空并在 `review_notes` 请求补充。

- 失败备注：`【厂商差异】【1.0需求版本】【消息订阅】删除修改过的消息订阅播报任务，会重新生成修改前的任务`。可写 `actual`：`删除已修改的消息订阅播报任务后，列表中重新出现修改前的任务。` 若步骤只有点击删除、点击确定，没有修改过程，在 `review_notes` 写“备注提到已修改的任务，但步骤未记录修改过程，需确认修改内容及发生时间”；不能擅自补进复现步骤。
- 备注 `唤醒后页面提示【设备离线】` 中的括号是界面提示，应保留为 `唤醒设备后，页面提示【设备离线】。` 管理标签和产品界面文字需要按上下文区分，不能一律删除括号。
- 备注只有 `失败，具体响应未记录` 时，`actual` 留空，`review_notes` 说明需要补充设备响应；不能根据“应进入页面”的预期自行写“未进入页面”。

成功响应包含 `plan_id` 和 `summary`，计数为 `total`、`exact`、`suggested`、`unmatched`。脚本只返回这些摘要及“已暂存，请回 BugDesk 核对并填入”；不会把服务响应里的其他内容回显。上下文过期或草稿发生变化时，重新执行 `context`，重新理解和核对后生成新的建议；不要自动重试旧建议。

## 生效位置

`stage` 只暂存待核对建议。草稿的填入、覆盖确认、审核、附件处理和提交仍由用户在 BugDesk 完成。此技能包的创建不表示已经安装到用户公司的 WorkBuddy，也不表示已连接共享文档。
