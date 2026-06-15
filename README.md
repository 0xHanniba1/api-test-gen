# API Test Agent

API 文档 → 测试用例 → pytest+requests 自动化代码，一键生成。

## 工具架构

### 整体流水线

```
                          api-test-agent
┌──────────────────────────────────────────────────────────────┐
│                                                              │
│  ┌─────────┐    ┌───────────────┐    ┌──────────────────┐   │
│  │ Parser  │    │  TestCase     │    │  Code            │   │
│  │         │───>│  Generator    │───>│  Generator       │   │
│  │ 文档解析 │    │  用例生成      │    │  代码生成         │   │
│  └─────────┘    └───────────────┘    └──────────────────┘   │
│       │                │                     │               │
│       │                │                     ├─ flat 模式     │
│       │                │                     └─ layered 模式  │
│  ┌─────────┐    ┌───────────────┐    ┌──────────────────┐   │
│  │ 格式检测 │    │    Skills     │    │   Validator      │   │
│  │ auto    │    │  可插拔知识模块 │    │  语法/格式/collect │   │
│  └─────────┘    └───────────────┘    └──────────────────┘   │
│                                                              │
└──────────────────────────────────────────────────────────────┘
```

### 三阶段流水线

| 阶段 | 模块 | 输入 | 输出 | LLM 调用 |
|------|------|------|------|---------|
| **1. 解析** | `parser/` | API 文档（Swagger/Postman/Markdown） | `ApiEndpoint` 统一结构 | Markdown 格式需要 |
| **2. 生成用例** | `generator/testcase.py` + `skills/` | `ApiEndpoint` + 深度级别 | 测试用例文档（Markdown 表格） | 每接口 1 次 |
| **3. 生成代码** | `generator/code.py` 或 `layered.py` | 测试用例文档（+ endpoints） | pytest 代码文件 | flat: 每接口 1 次, layered: 每 tag 4 次 |
| **3.1 质量校验** | `generator/validator.py` | 生成的代码文件 | 校验通过 / 错误反馈 → LLM 重试 | 仅重试时调用 |

每个阶段可独立运行：`gen-cases` 只执行 1→2，`gen-code` 只执行 3，`run` 执行 1→2→3。

### 项目结构

```
src/api_test_agent/
├── cli.py                 # CLI 入口（Click），参数与用户反馈
├── pipeline.py            # 应用层编排：解析、过滤、生成器选择
├── output.py              # 安全写盘、append 与路径冲突检查
├── llm.py                 # LLM 调用封装（litellm），支持 Claude/GPT/Gemini
├── parser/                # 文档解析器 —— 将各种格式统一为 ApiEndpoint
│   ├── base.py            #   数据模型：ApiEndpoint, Param（Pydantic）
│   ├── detect.py          #   格式自动检测
│   ├── swagger.py         #   OpenAPI/Swagger 解析（直接解析，无需 LLM）
│   ├── postman.py         #   Postman Collection 解析（直接解析）
│   └── markdown.py        #   自由文本解析（通过 LLM 提取）
├── generator/             # 代码生成器
│   ├── common.py          #   两种生成器共用的提取、校验与重试逻辑
│   ├── testcase.py        #   测试用例草稿生成（LLM + Skills 驱动）
│   ├── testcase_document.py # JSON 草稿校验、编号、Markdown 解析/渲染
│   ├── naming.py          #   endpoint/tag 确定性命名与碰撞处理
│   ├── code.py            #   平铺模式：每接口一个 test_*.py
│   ├── layered.py         #   分层模式：五层架构项目（LLM + 模板）
│   └── validator.py       #   生成代码质量校验（语法/YAML/pytest collect）
├── skills/                # 可插拔测试知识 —— Markdown 文件注入 LLM prompt
│   ├── loader.py          #   根据接口特征自动选择 skills
│   ├── base.md            #   基础测试规则（始终加载）
│   ├── param-validation.md    # 有参数时加载
│   ├── pagination.md          # 有分页参数时加载
│   ├── file-upload.md         # multipart/form-data 时加载
│   ├── auth-testing.md        # depth=full 时加载
│   └── idempotency.md         # depth=full 时加载
└── prompts/               # LLM Prompt 模板
    ├── testcase.md        #   用例生成输出格式规范
    ├── code.md            #   平铺模式代码生成规则
    ├── layered_api.md     #   分层 - 接口封装层
    ├── layered_data.md    #   分层 - 数据层 YAML
    ├── layered_services.md    # 分层 - 业务编排层
    └── layered_tests.md       # 分层 - 用例层
```

### 核心设计决策

- **流水线架构，非 Agent** — 流程固定（解析→用例→代码），不需要 LLM 自主决策循环
- **Skills 驱动测试质量** — 测试知识以 Markdown 文件存在，注入 LLM system prompt，易于扩展和版本管理
- **结构化中间契约** — LLM 只返回 JSON 草稿；程序校验后分配全局 `TC-XXX` 编号并渲染 Markdown，后续生成器再结构化解析，Markdown 仍可人工审核和编辑
- **确定性输出命名** — 测试文件由 method + path 命名，规范化碰撞使用稳定哈希；不信任 LLM 返回的文件名
- **多模型支持** — 通过 litellm 统一调用 Claude/GPT/Gemini 等，一行切换模型
- **生成代码自动校验** — 代码生成后自动执行语法检查（ast.parse）、YAML 格式检查、pytest collect 检查，失败时将错误反馈给 LLM 重试（最多 2 次）；仍失败则命令返回非零状态，不写入无效代码
- **生成输出安全写盘** — 拒绝目录逃逸、符号链接逃逸和目标路径冲突，避免 LLM 返回的文件名覆盖输出目录之外的文件

## 安装

```bash
git clone <repo-url>
cd api-test-agent
uv sync
```

## 快速上手

### 全流程（推荐）

```bash
# 从 Swagger/OpenAPI 文档生成测试用例 + 代码（平铺模式）
api-test-agent run api-doc.yaml -o output/

# 生成分层架构代码（base/data/api/services/tests 五层）
api-test-agent run api-doc.yaml -o output/ --arch layered
```

### 分步执行

```bash
# 第一步：生成测试用例文档
api-test-agent gen-cases api-doc.yaml -o testcases.md

# 第二步：从测试用例生成代码（平铺模式）
api-test-agent gen-code testcases.md -o output/

# 第二步（分层模式）：需要通过 --doc 指定原始 API 文档
api-test-agent gen-code testcases.md -o output/ --arch layered --doc api-doc.yaml
```

### 运行生成的测试

```bash
cd output/
API_BASE_URL=http://localhost:8080 API_TOKEN=your-token pytest -v
```

## 支持的输入格式

| 格式 | 说明 |
|------|------|
| OpenAPI 3.x | YAML 或 JSON；支持 path/operation 参数合并、本地 `$ref`、request body、response schema 和 security 继承 |
| Swagger 2.0 | YAML 或 JSON；支持 body/formData、consumes、全局参数/响应引用和 security 继承 |
| Postman Collection v2.1 | JSON 导出文件；支持文件夹 tag、auth 继承、path/query/header 参数、raw/form-data/urlencoded/GraphQL body 和保存的响应示例 |
| Markdown / 文本 | 任意格式的接口文档（通过 LLM 解析） |

当前只解析同一文档内的本地 `$ref`。远程 `$ref` 不会被解析，也不会发起网络请求；需要完整生成时应先将引用内容合并到输入文档。

## 命令选项

```bash
api-test-agent run <doc> -o <dir> [OPTIONS]
api-test-agent gen-cases <doc> -o <file> [OPTIONS]
api-test-agent gen-code <cases> -o <dir> [OPTIONS]

Options:
  --depth quick|full    测试深度（默认 quick）
  --model <name>        LLM 模型（默认 claude-sonnet-4-20250514）
  --format auto|swagger|postman|markdown  文档格式（默认 auto）
  --filter <pattern>    按接口过滤，支持多次使用（见下方说明）
  --append              增量模式：追加用例 / 跳过已有代码文件
  --arch flat|layered   代码架构风格（默认 flat，见下方说明）
  --doc <file>          API 文档路径（gen-code 使用 --arch layered 时必填）
```

### 增量生成

新增接口时无需重新生成全量，使用 `--filter` 和 `--append` 组合：

```bash
# 只生成 POST /pets 相关的测试，追加到已有输出
api-test-agent run api-doc.yaml -o output/ --filter "POST /pets" --append

# 生成所有 GET 接口的测试
api-test-agent run api-doc.yaml -o output/ --filter "GET *" --append

# 多个 filter 组合
api-test-agent run api-doc.yaml -o output/ --filter "POST /orders*" --filter "PUT /orders*" --append
```

`--filter` 支持的模式：
- `"POST /pets"` — 匹配指定 method + path
- `"/pets/*"` — 任意 method，路径 glob 匹配
- 支持 `*` 和 `?` 通配符

`--append` 行为：
- `gen-cases` / `run`：从已有最大 `TC-XXX` 继续编号并追加；已有同 method + path 章节时拒绝追加
- `gen-code` / `run`：跳过已存在的代码文件，只写入新文件

### 分层架构模式

使用 `--arch layered` 生成按接口自动化五层架构组织的代码。

#### 架构总览

```
┌─────────────────────────────────────────────────┐
│                 用例与执行层 (tests/)              │
│  pytest 测试用例，调用下层接口，数据从 YAML 加载     │
├─────────────────────────────────────────────────┤
│                 业务编排层 (services/)             │
│  组合多个接口完成业务流程（创建→查询→更新→删除）      │
├─────────────────────────────────────────────────┤
│                 接口封装层 (api/)                  │
│  每个接口封装为方法，屏蔽 HTTP 细节                  │
├─────────────────────────────────────────────────┤
│                 数据层 (data/)                    │
│  YAML 文件管理测试数据，数据与代码分离               │
├─────────────────────────────────────────────────┤
│                 基础层 (base/)                    │
│  HttpClient 封装、环境配置、公共能力                │
└─────────────────────────────────────────────────┘
```

#### 各层职责

| 层 | 目录 | 职责 | 示例 |
|----|------|------|------|
| **基础层** | `base/` | 统一的 HTTP 客户端封装，环境配置（BASE_URL、TOKEN）通过环境变量注入 | `HttpClient` 封装 `requests.Session`，提供 get/post/put/delete 方法 |
| **数据层** | `data/` | YAML 文件管理测试数据，实现数据与代码分离，便于维护和批量修改 | `users.yaml` 按操作和场景组织：`create_user.valid`、`create_user.missing_name` |
| **接口封装层** | `api/` | 每个资源一个类，每个接口一个方法，屏蔽路径拼接和参数传递细节 | `UsersApi.create_user(body)` 内部调用 `self.client.post("/api/users", json=body)` |
| **业务编排层** | `services/` | 组合多个接口调用完成端到端业务流程，通过响应数据串联各步骤 | `UserFlow.full_lifecycle()`: 创建 → 查询 → 更新 → 删除 → 验证删除 |
| **用例与执行层** | `tests/` | pytest 测试用例，通过 fixture 获取 api 实例，从 YAML 加载数据，不直接调用 requests | `test_users.py` 中 `users_api.create_user(d["body"])` + `assert resp.status_code == d["expected_status"]` |

#### 调用关系

```
tests/test_users.py
    │
    ├── 读取 data/users.yaml（测试数据）
    │
    ├── 通过 fixture 获取 api/users_api.py（接口封装）
    │        │
    │        └── 调用 base/client.py（HTTP 客户端）
    │                │
    │                └── 读取 base/config.py（环境配置）
    │
    └── 可选：调用 services/users_flow.py（业务编排）
             │
             └── 内部调用 api/users_api.py
```

#### 生成的目录结构

```
output/
├── base/              # 基础层
│   ├── config.py      #   环境变量配置（API_BASE_URL, API_TOKEN）
│   └── client.py      #   HttpClient 封装
├── data/              # 数据层
│   └── users.yaml     #   按资源/tag 一个 YAML 文件
├── api/               # 接口封装层
│   └── users_api.py   #   按资源/tag 一个类
├── services/          # 业务编排层
│   └── users_flow.py  #   CRUD 业务流程
├── tests/             # 用例与执行层
│   ├── conftest.py    #   fixtures（client + api 实例）
│   └── test_users.py  #   测试用例
├── Jenkinsfile        # Jenkins Pipeline
└── requirements.txt   # 依赖
```

接口按 API 文档中的 tag 分组，每个 tag 在各层生成对应文件。

#### Jenkins CI 集成

生成的 `Jenkinsfile` 开箱即用，支持：
- **参数化构建**：通过 `ENV` 参数选择 dev/staging/prod 环境
- **Token 安全管理**：通过 Jenkins Credentials 注入 `api-token`
- **JUnit 报告**：自动收集 `reports/*.xml` 展示测试结果

## 配置

设置环境变量：

```bash
export ANTHROPIC_API_KEY=your-key    # 使用 Claude
export OPENAI_API_KEY=your-key       # 使用 GPT
```

## 项目文档

- [设计文档](docs/design.md) — 为什么这样设计
- [开发指南](docs/development.md) — 如何参与开发
- [Skills 编写指南](docs/skills-guide.md) — 如何扩展测试知识
