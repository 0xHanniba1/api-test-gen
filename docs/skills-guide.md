# Skills 编写指南

## 什么是 Skill

Skill 是一个 Markdown 文件，包含特定场景的测试策略知识。当 agent 生成测试用例时，会根据接口特征自动选择合适的 skills 注入到 LLM prompt 中。

## Skill 文件格式

```markdown
# Skill 名称

## 测试策略
- 具体的测试场景描述
- 期望的输入和输出
- 注意事项

## 示例用例（可选）
| 编号 | 场景 | 输入 | 预期 |
|------|------|------|------|
| ... | ... | ... | ... |
```

## 现有 Skills

| 文件 | 用途 | 触发条件 |
|------|------|---------|
| base.md | 基础测试规则 | 始终加载 |
| param-validation.md | 参数验证策略 | 接口有参数时 |
| pagination.md | 分页测试策略 | 检测到分页参数（page/size/limit/offset） |
| file-upload.md | 文件上传测试 | content_type 为 multipart/form-data |
| auth-testing.md | 鉴权与权限测试 | depth=full 时 |
| idempotency.md | 幂等性测试 | depth=full 时 |

## 添加新 Skill

### 第一步：创建 Skill 文件

在 `src/api_test_gen/skills/` 目录创建 `.md` 文件：

```bash
# 例如添加限流测试策略
touch src/api_test_gen/skills/rate-limiting.md
```

### 第二步：编写内容

参考现有 skill 文件的格式，写入测试策略。

### 第三步：添加加载规则

编辑 `src/api_test_gen/skills/loader.py`，在 `select_skills()` 函数中添加匹配条件：

```python
# 示例：当接口文档中提到限流相关信息时加载
if depth == "full":
    skills.append("rate-limiting.md")
```

### 第四步：写测试

在 `tests/test_skills.py` 中添加对应的测试用例。
