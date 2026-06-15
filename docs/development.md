# 开发指南

## 环境要求

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) 包管理器

## 环境搭建

```bash
git clone <repo-url>
cd api-test-agent
uv sync           # 安装所有依赖（包括开发依赖）
```

## 运行测试

```bash
uv run pytest -v           # 运行所有测试
uv run pytest tests/test_swagger_parser.py -v   # 运行单个测试文件
```

## 项目结构

```
src/api_test_agent/
├── cli.py              # CLI 入口（Click）
├── pipeline.py         # 应用层编排（解析、过滤、生成器选择）
├── output.py           # 生成文件安全写盘
├── llm.py              # LLM 调用封装（litellm）
├── parser/             # 文档解析器
│   ├── base.py         # 数据模型（ApiEndpoint, Param）
│   ├── detect.py       # 格式自动检测
│   ├── swagger.py      # OpenAPI/Swagger 解析
│   ├── postman.py      # Postman Collection 解析
│   └── markdown.py     # Markdown 文档解析（LLM）
├── generator/          # 生成器
│   ├── common.py       # 公共代码提取、校验重试与文件冲突检查
│   ├── testcase.py     # 测试用例 JSON 草稿生成（LLM + Skills）
│   ├── testcase_document.py # 草稿校验、编号、Markdown 解析/渲染
│   ├── naming.py       # endpoint/tag 确定性命名
│   ├── code.py         # pytest 代码生成 - 平铺模式（LLM）
│   ├── layered.py     # pytest 代码生成 - 分层架构模式（LLM + 模板）
│   └── validator.py   # 生成代码质量校验（语法/YAML/collect）
├── skills/             # 可插拔测试知识模块
│   ├── loader.py       # Skill 选择与加载
│   ├── base.md         # 基础测试规则
│   └── *.md            # 各类测试策略
└── prompts/            # Prompt 模板
    ├── testcase.md     # 用例生成 prompt
    ├── code.md         # 代码生成 prompt（平铺模式）
    ├── layered_api.md  # 分层 - 接口封装层 prompt
    ├── layered_data.md # 分层 - 数据层 prompt
    ├── layered_services.md  # 分层 - 业务编排层 prompt
    └── layered_tests.md     # 分层 - 用例层 prompt
```

## 数据流

```
输入文档 → [Parser] → ApiEndpoint → [TestCaseGenerator + Skills] → JSON 草稿 → Markdown
                                                                       ↓
                                    --arch flat:  [CodeGenerator]     → 平铺 pytest 文件
                                    --arch layered: [LayeredCodeGenerator] → 五层架构项目
```

## 如何添加新的解析器

1. 在 `parser/` 目录创建新文件（如 `har.py`）
2. 实现 `parse_xxx(file_path: Path) -> list[ApiEndpoint]` 函数
3. 在 `detect.py` 添加格式检测逻辑
4. 在 `pipeline.py` 的 `parse_document()` 添加分支
5. 写测试

解析器测试应至少包含：

- 格式检测 fixture
- 参数位置、必填性、约束和示例
- 请求体 schema、媒体类型和响应 schema
- 格式自身的继承/覆盖规则
- 无效引用或无效输入的显式失败行为

OpenAPI/Swagger 的本地 `$ref` 可解析，远程 `$ref` 不允许触发网络请求。Postman 示例数据必须转换为 JSON Schema，不能直接把示例对象当作 schema。

## 如何添加新的代码架构模式

1. 在 `generator/` 创建新文件（如 `custom.py`）
2. 实现生成器类，`generate()` 方法返回 `dict[str, str]`（文件路径 → 内容）
3. 在 `prompts/` 添加对应的 LLM prompt 模板
4. 在 `pipeline.py` 的 `generate_code()` 接入，并扩展 CLI 的 `--arch` 选项
5. 写测试

## 生成输出约束

- 生成器返回 `dict[str, str]`，key 必须是输出目录内的相对路径
- 不允许绝对路径、`..`、符号链接逃逸或多个 key 指向同一文件
- 常规命名碰撞应使用稳定哈希消解；最终文件路径重复必须显式报错，不能依赖字典覆盖
- 不允许从 LLM 输出注释中读取目标文件名
- 校验重试后仍失败时抛出 `GenerationValidationError`，CLI 返回非零状态
