# 分层架构代码生成设计

## 概述

为 `gen-code` 命令新增 `--arch layered` 参数，生成按接口自动化分层架构组织的代码，替代当前平铺模式。

```bash
# 现有行为不变（默认 --arch flat）
api-test-gen gen-code testcases.md -o output/

# 新：生成分层架构项目
api-test-gen gen-code testcases.md -o output/ --arch layered
```

## 输出目录结构

```
output/
├── base/                    # 基础层
│   ├── __init__.py
│   ├── client.py            # HttpClient 轻量封装
│   └── config.py            # 环境配置（base_url, token）
├── data/                    # 数据层（YAML）
│   └── users.yaml           # 按资源/tag 一个文件
├── api/                     # 接口封装层
│   ├── __init__.py
│   └── users_api.py         # 按资源/tag 一个类
├── services/                # 业务编排层
│   ├── __init__.py
│   └── user_flow.py         # LLM 推断的 CRUD 业务流程
├── tests/                   # 用例与执行层
│   ├── __init__.py
│   ├── conftest.py          # fixtures: client, api 实例
│   └── test_users.py        # 测试用例，调用 services/api 层
└── requirements.txt         # 依赖：requests, pytest, pyyaml
```

文件按 tag/资源分组。

## 各层详细设计

### 基础层 base/

**config.py** — 环境配置，通过环境变量读取：

```python
import os

BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8080")
API_TOKEN = os.getenv("API_TOKEN", "")
```

**client.py** — 轻量 HTTP 封装：

```python
import requests
from .config import BASE_URL, API_TOKEN

class HttpClient:
    def __init__(self, base_url=BASE_URL, token=API_TOKEN):
        self.session = requests.Session()
        self.base_url = base_url
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

    def get(self, path, **kwargs):
        return self.session.get(f"{self.base_url}{path}", **kwargs)

    def post(self, path, **kwargs):
        return self.session.post(f"{self.base_url}{path}", **kwargs)

    def put(self, path, **kwargs):
        return self.session.put(f"{self.base_url}{path}", **kwargs)

    def delete(self, path, **kwargs):
        return self.session.delete(f"{self.base_url}{path}", **kwargs)
```

### 接口封装层 api/

每个资源/tag 一个类，每个接口一个方法：

```python
# api/users_api.py
from base.client import HttpClient

class UsersApi:
    def __init__(self, client: HttpClient):
        self.client = client

    def create_user(self, body: dict):
        return self.client.post("/api/users", json=body)

    def get_user(self, user_id: int):
        return self.client.get(f"/api/users/{user_id}")

    def update_user(self, user_id: int, body: dict):
        return self.client.put(f"/api/users/{user_id}", json=body)

    def delete_user(self, user_id: int):
        return self.client.delete(f"/api/users/{user_id}")
```

### 数据层 data/

YAML 文件，按测试场景组织，数据代码分离：

```yaml
# data/users.yaml
create_user:
  valid:
    body: { "name": "test", "email": "a@b.com" }
    expected_status: 201
  missing_name:
    body: { "email": "a@b.com" }
    expected_status: 400

get_user:
  valid:
    path_params: { "user_id": 1 }
    expected_status: 200
  not_found:
    path_params: { "user_id": 99999 }
    expected_status: 404
```

### 业务编排层 services/

LLM 根据 CRUD 关系自动推断生成：

```python
# services/user_flow.py
from api.users_api import UsersApi

class UserFlow:
    def __init__(self, api: UsersApi):
        self.api = api

    def create_and_get(self, body: dict):
        resp = self.api.create_user(body)
        user_id = resp.json()["id"]
        return self.api.get_user(user_id)

    def full_lifecycle(self, create_body: dict, update_body: dict):
        resp = self.api.create_user(create_body)
        user_id = resp.json()["id"]
        self.api.update_user(user_id, update_body)
        self.api.delete_user(user_id)
        return self.api.get_user(user_id)
```

### 用例与执行层 tests/

调用上层，不直接调用 requests：

```python
# tests/conftest.py
import pytest
from base.client import HttpClient
from api.users_api import UsersApi

@pytest.fixture
def client():
    return HttpClient()

@pytest.fixture
def users_api(client):
    return UsersApi(client)

# tests/test_users.py
import yaml

def load_data(resource):
    with open(f"data/{resource}.yaml") as f:
        return yaml.safe_load(f)

class TestCreateUser:
    """POST /api/users"""
    data = load_data("users")["create_user"]

    def test_success(self, users_api):
        """TC-001: 正常创建用户"""
        d = self.data["valid"]
        resp = users_api.create_user(d["body"])
        assert resp.status_code == d["expected_status"]

    def test_missing_name(self, users_api):
        """TC-002: 缺少必填字段 name"""
        d = self.data["missing_name"]
        resp = users_api.create_user(d["body"])
        assert resp.status_code == d["expected_status"]
```

## 代码生成策略

### 生成顺序

| 步骤 | 生成内容 | 方式 |
|------|---------|------|
| 1 | `base/config.py` | 模板生成，无需 LLM |
| 2 | `base/client.py` | 模板生成，无需 LLM |
| 3 | `api/*.py` 接口封装 | LLM 生成，按 tag 分组，每组一次调用 |
| 4 | `data/*.yaml` 测试数据 | LLM 生成，基于 testcases.md 提取数据 |
| 5 | `services/*.py` 业务编排 | LLM 生成，基于同 tag 下的接口推断 CRUD 流程 |
| 6 | `tests/conftest.py` | 模板生成，根据 tag 列表生成 fixtures |
| 7 | `tests/test_*.py` 用例 | LLM 生成，按 tag 分组，引用 api/data/services 层 |
| 8 | `requirements.txt` | 模板生成 |

### 设计要点

- 步骤 1、2、6、8 用代码模板直接生成，不消耗 LLM 调用，输出稳定可控
- 步骤 3-5、7 由 LLM 生成，prompt 中注入已生成的上层代码作为上下文
- 按 tag 分组而非按单个 endpoint，减少 LLM 调用次数

### LLM 调用次数

- flat 模式：1（conftest）+ N（每 endpoint 一次）= N+1 次
- layered 模式：T×3（每 tag 生成 api + data + test）+ T（services）= T×4 次（T = tag 数量）

## 代码改动范围

### 修改的文件

| 文件 | 改动 |
|------|------|
| `src/api_test_gen/cli.py` | `gen-code` 和 `run` 命令增加 `--arch` 参数 |
| `src/api_test_gen/generator/code.py` | 重构：抽取现有逻辑为 `FlatCodeGenerator` |

### 新增的文件

| 文件 | 职责 |
|------|------|
| `src/api_test_gen/generator/layered.py` | `LayeredCodeGenerator` 核心生成逻辑 |
| `src/api_test_gen/generator/templates/` | 模板文件（config、client、conftest、requirements） |
| `src/api_test_gen/prompts/layered_api.md` | 接口封装层 prompt |
| `src/api_test_gen/prompts/layered_data.md` | 数据层 YAML 生成 prompt |
| `src/api_test_gen/prompts/layered_services.md` | 业务编排层 prompt |
| `src/api_test_gen/prompts/layered_tests.md` | 用例层 prompt |
| `tests/test_layered_generator.py` | 单元测试 |

### 不变的文件

- 所有 parser（swagger/postman/markdown）
- TestCaseGenerator
- skills 系统
- llm.py

### 生成器接口

```python
# generator/code.py（现有，重命名）
class FlatCodeGenerator:
    def generate(self, testcases_md: str) -> dict[str, str]: ...

# generator/layered.py（新增）
class LayeredCodeGenerator:
    def generate(self, testcases_md: str, endpoints: list[ApiEndpoint]) -> dict[str, str]: ...
```

两者都返回 `dict[str, str]`（文件路径 → 内容），CLI 层统一写入磁盘。`LayeredCodeGenerator` 额外需要 `endpoints` 参数用于按 tag 分组和读取接口签名。
