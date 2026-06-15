# API Test Agent 设计文档

> 给定接口文档，自动生成测试用例文档 + pytest + requests 自动化代码。

## 1. 概述

### 1.1 目标

构建一个 CLI 工具，输入 API 文档，输出：
1. 结构化的测试用例文档（Markdown）
2. 可直接运行的 pytest + requests 自动化测试代码

### 1.2 核心原则

- **流水线架构** — 解析 → 生成用例 → 生成代码，每步可独立运行
- **不引入 agent 框架** — 流程固定，不需要 LLM 自主决策循环
- **测试知识驱动** — 用 skills（可插拔知识模块）指导 LLM 生成高质量用例
- **多模型支持** — 通过 litellm 统一调用 Claude/GPT/Gemini 等

### 1.3 技术栈

| 依赖 | 用途 |
|------|------|
| litellm | 多模型统一 API 调用 |
| click | CLI 框架 |
| pydantic | 数据结构定义与校验 |
| pyyaml | OpenAPI YAML 解析 |

---

## 2. 架构设计

### 2.1 数据流

```
输入文档 → [Parser] → ApiEndpoint (统一结构)
                            ↓
ApiEndpoint → [TestCase Generator + Skills] → JSON 草稿 → Markdown 文档
                            ↓                         ↓
                    (--arch layered)            (--arch flat，默认)
                            ↓                         ↓
              [LayeredCodeGenerator]          [CodeGenerator]
              testcases + endpoints           testcases only
                            ↓                         ↓
              五层架构项目目录                 平铺 pytest 文件
```

### 2.2 模块职责

```
api-test-agent/
├── pyproject.toml
├── README.md
├── src/
│   └── api_test_agent/
│       ├── __init__.py
│       ├── cli.py              # CLI 入口，参数与用户反馈
│       ├── pipeline.py         # 应用层编排：解析、过滤、生成器选择
│       ├── output.py           # 生成文件安全写盘
│       ├── parser/             # 文档解析器
│       │   ├── base.py         # ApiEndpoint 等模型定义
│       │   ├── swagger.py      # OpenAPI/Swagger 解析
│       │   ├── postman.py      # Postman Collection 解析
│       │   └── markdown.py     # Markdown 文档 → LLM 提取
│       ├── generator/          # 生成器
│       │   ├── common.py       # 公共提取、校验重试与冲突检测
│       │   ├── testcase.py     # 测试用例 JSON 草稿生成（LLM）
│       │   ├── testcase_document.py # 草稿校验、编号、Markdown 解析/渲染
│       │   ├── naming.py       # endpoint/tag 确定性命名
│       │   ├── code.py         # 代码生成 - 平铺模式（LLM）
│       │   ├── layered.py     # 代码生成 - 分层架构模式（LLM + 模板）
│       │   └── validator.py   # 生成代码质量校验
│       ├── skills/             # 可插拔测试知识模块
│       │   ├── loader.py       # skill 加载与选择逻辑
│       │   ├── base.md         # 基础测试规则（始终加载）
│       │   ├── param-validation.md   # 参数验证策略
│       │   ├── auth-testing.md       # 鉴权与权限测试
│       │   ├── pagination.md         # 分页接口专用
│       │   ├── file-upload.md        # 文件上传接口专用
│       │   └── idempotency.md        # 幂等性测试
│       ├── prompts/            # prompt 模板
│       │   ├── testcase.md     # 用例生成 prompt 模板
│       │   ├── code.md         # 代码生成 prompt 模板（平铺模式）
│       │   ├── layered_api.md  # 分层 - 接口封装层 prompt
│       │   ├── layered_data.md # 分层 - 数据层 YAML prompt
│       │   ├── layered_services.md  # 分层 - 业务编排层 prompt
│       │   └── layered_tests.md     # 分层 - 用例层 prompt
│       └── llm.py              # litellm 封装（模型调用、重试、错误处理）
├── tests/                      # 项目自身的测试
└── docs/
    ├── design.md               # 本设计文档
    ├── development.md          # 开发指南
    └── skills-guide.md         # 如何编写新 skill
```

---

## 3. 模块详细设计

### 3.1 文档解析器（Parser）

#### 统一数据模型

```python
class Param(BaseModel):
    name: str
    location: str          # query / path / header / cookie
    required: bool = False
    param_type: str = "string"
    description: str = ""
    constraints: dict = Field(default_factory=dict)
    example: Any | None = None

class ApiEndpoint(BaseModel):
    method: str              # 自动标准化为大写
    path: str                # /api/users/{id}
    summary: str = ""
    description: str = ""
    operation_id: str = ""
    parameters: list[Param] = Field(default_factory=list)
    request_body: dict | None  # 请求体 JSON Schema
    request_body_required: bool = False
    responses: dict = Field(default_factory=dict)
    auth_required: bool = False
    tags: list[str] = Field(default_factory=list)
    content_type: str = "application/json"
    content_types: list[str] = Field(default_factory=list)
```

`content_type` 保留为主要媒体类型，兼容 skill 选择；`content_types` 保存文档声明的全部请求媒体类型。Postman 请求示例会转换为带 `example` 的 JSON Schema，保证三种解析器输出同一语义。

#### 解析策略

| 输入格式 | 检测方式 | 解析方式 |
|----------|---------|---------|
| OpenAPI 3.x / Swagger 2.0 | 文件包含 `openapi` 或 `swagger` 字段 | 代码直接解析 YAML/JSON；合并 path/operation 参数并解析本地 `$ref` |
| Postman Collection v2.1 | `info._postman_id` 或官方 collection schema | 代码直接解析 JSON；递归继承 folder tag 和 auth |
| Markdown / 文本 | 以上都不匹配 | 交给 LLM 提取为 ApiEndpoint 结构 |

格式自动检测（`--format auto`），也支持手动指定。

解析边界：

- OpenAPI operation 参数按 `(name, in)` 覆盖 path 参数
- operation `security` 覆盖根级定义；空数组或包含空 requirement 表示不强制鉴权
- Swagger 2.0 `body` 转为请求 schema，`formData` 聚合为 object schema
- Postman 文件夹层级写入 `tags`，请求级 auth 覆盖文件夹和 collection auth
- 仅解析当前文件内的 JSON Pointer `$ref`；远程引用不解析、不下载

### 3.2 Skills 体系

#### 设计理念

Skills 是可插拔的测试知识模块，每个 skill 是一个 Markdown 文件，包含：
- 适用场景描述（用于自动匹配）
- 测试策略和用例设计指导
- 示例用例

#### 自动加载逻辑

```python
# loader.py 伪代码
def select_skills(endpoint: ApiEndpoint, depth: str) -> list[str]:
    skills = ["base.md"]  # 始终加载

    if depth == "full":
        skills.append("auth-testing.md")
        skills.append("idempotency.md")

    # 根据接口特征自动匹配
    if has_pagination_params(endpoint):
        skills.append("pagination.md")

    if endpoint.content_type == "multipart/form-data":
        skills.append("file-upload.md")

    if endpoint.parameters:
        skills.append("param-validation.md")

    return skills
```

#### 扩展方式

添加新 skill 只需：
1. 在 `skills/` 目录创建 `.md` 文件
2. 在 `loader.py` 添加匹配规则
3. 详见 `docs/skills-guide.md`

### 3.3 测试用例生成器（TestCase Generator）

#### Prompt 组装

```
system = base.md + 自动选中的 skills + testcase.md（输出格式要求）
user   = ApiEndpoint JSON + 深度级别
```

#### 深度级别

**quick（默认）：**
- 正常请求（必填参数都传，期望成功）
- 必填参数缺失（期望 400）
- 参数类型错误（期望 400）
- 关键边界值（空值、超长）
- 未授权访问（期望 401）

**full：**
- quick 的全部内容
- 完整边界值 + 特殊字符 + SQL 注入 / XSS
- 状态码全量验证
- 响应体结构和数据正确性验证
- 鉴权与权限（水平/垂直越权）
- 幂等性测试
- 性能基础验证（响应时间）

#### 输出格式

LLM 只返回不含编号的 JSON 数组。程序校验字段后全局分配 `TC-XXX`，再渲染为每接口一个章节的 Markdown 表格：

```markdown
## POST /api/users

| 编号 | 场景 | 输入 | 预期状态码 | 预期响应 | 优先级 |
|------|------|------|-----------|---------|--------|
| TC-001 | 正常创建用户 | {"name":"test","email":"a@b.com"} | 201 | 返回用户ID | P0 |
| TC-002 | 缺少必填字段 name | {"email":"a@b.com"} | 400 | 错误提示包含 name | P0 |
```

### 3.4 代码生成器（Code Generator）

支持两种架构模式，通过 `--arch` 参数切换。

#### 3.4.1 平铺模式（flat，默认）

```
output/
├── conftest.py            # 公共 fixtures
├── test_post_api_users.py # POST /api/users
├── test_get_api_users_by_id.py # GET /api/users/{id}
└── test_delete_api_users_by_id.py # DELETE /api/users/{id}
```

#### conftest.py 提供的公共能力

```python
import pytest
import os

@pytest.fixture
def base_url():
    return os.getenv("API_BASE_URL", "http://localhost:8080")

@pytest.fixture
def auth_headers():
    token = os.getenv("API_TOKEN", "")
    return {"Authorization": f"Bearer {token}"} if token else {}
```

#### 测试文件规范

```python
class TestCreateUser:
    """POST /api/users"""

    def test_create_user_success(self, base_url, auth_headers):
        """TC-001: 正常创建用户"""
        resp = requests.post(
            f"{base_url}/api/users",
            json={"name": "test", "email": "a@b.com"},
            headers=auth_headers
        )
        assert resp.status_code == 201
        assert "id" in resp.json()

    def test_missing_required_field(self, base_url, auth_headers):
        """TC-002: 缺少必填字段 name"""
        resp = requests.post(
            f"{base_url}/api/users",
            json={"email": "a@b.com"},
            headers=auth_headers
        )
        assert resp.status_code == 400
```

代码规范：
- 用例编号写在 docstring，方便与用例文档溯源
- 环境配置全部走环境变量，不硬编码
- 每条用例独立，不依赖执行顺序
- 一个接口一个文件，一个用例一个方法
- 文件名由 method + path 确定；规范化后碰撞时追加 endpoint 稳定哈希

#### 3.4.2 分层架构模式（layered）

按接口自动化标准分层组织，接口按 tag 分组：

```
output/
├── base/                    # 基础层
│   ├── config.py            # 环境配置（BASE_URL, TOKEN）
│   └── client.py            # HttpClient 轻量封装（requests.Session）
├── data/                    # 数据层（YAML，数据代码分离）
│   └── users.yaml           # 按 tag 一个文件
├── api/                     # 接口封装层
│   └── users_api.py         # 每个 tag 一个类，每个接口一个方法
├── services/                # 业务编排层
│   └── users_flow.py        # LLM 根据 CRUD 语义自动推断业务流程
├── tests/                   # 用例与执行层
│   ├── conftest.py          # fixtures（client + 各 tag 的 api 实例）
│   └── test_users.py        # 测试用例，调用 api 层，数据从 YAML 加载
└── requirements.txt         # 依赖
```

**生成策略：**

| 层 | 生成方式 | LLM 调用 |
|----|---------|---------|
| base/ | 代码模板 | 无 |
| api/ | LLM，按 tag 分组 | 每 tag 1 次 |
| data/ | LLM，基于测试用例 | 每 tag 1 次 |
| services/ | LLM，推断 CRUD 流程 | 每 tag 1 次 |
| tests/ | LLM，引用 api + data | 每 tag 1 次 |
| conftest, requirements | 代码模板 | 无 |

`LayeredCodeGenerator` 需要 `testcases_md` + `endpoints` 两个输入（endpoints 用于按 tag 分组和读取接口签名）。

用例章节按精确的 `(method, path)` 关联。tag 规范化碰撞时追加稳定哈希；各层文件名由程序指定，不读取 LLM 首行注释。

### 3.5 代码质量校验（Validator）

生成代码后自动执行质量校验，失败时将错误反馈给 LLM 重试（最多 2 次）。重试后仍失败则抛出错误，CLI 返回非零状态，不写入无效代码文件。

#### 校验项

| 校验 | 方式 | 检查内容 |
|------|------|---------|
| Python 语法 | `ast.parse(code)` | SyntaxError、缩进错误 |
| YAML 格式 | `yaml.safe_load(content)` | YAML 解析错误 |
| pytest collect | `pytest --collect-only` | import 缺失、fixture 名错误、类名不符合规范 |

#### 校验流程

```
generate() 生成文件
       ↓
  validate_files()
  ├── validate_python()  — ast.parse 检查所有 .py 文件
  ├── validate_yaml()    — yaml.safe_load 检查所有 .yaml 文件
  └── validate_collect() — 仅语法通过后执行 pytest --collect-only
       ↓
   通过？── 是 → 进入安全写盘
       │
      否（重试 ≤ 2 次）
       ↓
   错误反馈给 LLM，只重新生成出错的文件
       ↓
   再次 validate_files() → 循环
       ↓
   仍失败 → 非零退出，不写入无效代码
```

**关键设计点：**
- 只重新生成出错的文件，不重新生成整个项目
- pytest collect 需要临时目录（先将全部文件写入临时目录再执行）
- flat 和 layered 两种模式共用同一套校验逻辑
- pytest collect 使用当前 Python 解释器，并设置 30 秒超时
- 写盘前统一拒绝目录逃逸、符号链接逃逸和目标路径冲突

---

## 4. CLI 设计

### 4.1 命令

```bash
# 全流程：文档 → 用例 → 代码
api-test-agent run api-doc.yaml -o output/

# 只生成测试用例文档
api-test-agent gen-cases api-doc.yaml -o testcases.md

# 从已有用例文档生成代码
api-test-agent gen-code testcases.md -o output/
```

### 4.2 选项

```bash
--depth quick|full                    # 测试深度，默认 quick
--model claude-sonnet                 # 指定模型
--format swagger|postman|markdown|auto  # 文档格式，默认 auto
--filter "POST /api/*"               # 只处理匹配的接口
--append                             # 增量模式
--arch flat|layered                  # 代码架构风格，默认 flat
--doc <file>                         # API 文档路径（gen-code --arch layered 时必填）
```

### 4.3 配置方式

当前版本不读取项目级或用户级配置文件。模型和深度通过 CLI 参数指定，API key 通过对应供应商的环境变量提供。

---

## 5. 文档交付物

| 文档 | 内容 | 目的 |
|------|------|------|
| README.md | 快速上手、安装、基本用法 | 新用户 5 分钟跑起来 |
| docs/design.md | 本文档 | 理解系统为什么这样设计 |
| docs/development.md | 环境搭建、开发流程、如何调试 | 开发者如何参与开发 |
| docs/skills-guide.md | skill 格式、编写规范、示例 | 如何扩展测试知识 |

代码级文档：
- 每个模块有 docstring（职责、输入输出）
- 关键函数有类型注解
- pyproject.toml 完整（依赖、入口、版本）

---

## 6. 未来扩展（不在 v1 范围）

- Web UI 界面
- 自动运行生成的测试并分析失败原因（需要 agent 循环）
- 多接口业务链路测试自动编排
- 测试报告生成（HTML/PDF）
