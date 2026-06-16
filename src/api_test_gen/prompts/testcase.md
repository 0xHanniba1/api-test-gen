# 输出格式要求

只输出一个 JSON 数组，可以包在 `json` 代码块中。每个元素必须包含：

```json
{
  "scenario": "场景描述",
  "input": {"请求参数或请求体": "值"},
  "expected_status": 200,
  "expected_response": "预期响应描述",
  "priority": "P0"
}
```

## 规则
- 不要生成编号、Markdown 标题或表格
- input 必须是合法 JSON 值；无输入时使用 null
- 优先级：P0=核心正常流程, P1=重要异常场景, P2=边缘场景
- 每个接口的第一个用例必须是正常场景（P0）
