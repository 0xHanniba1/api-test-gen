# 用例与执行层代码生成

根据测试用例文档和已生成的 API 封装类、数据文件，生成 pytest 测试代码。

## 规则
- 每个 tag 生成一个测试文件
- 文件名格式：test_{tag}.py
- 使用 class 组织测试，一个接口操作对应一个 class
- 测试方法通过 fixture 获取 api 实例（如 users_api）
- 测试数据从 YAML 文件加载，不硬编码在测试中
- 每个测试方法的 docstring 包含用例编号（如 TC-001）
- 使用 assert resp.status_code == d["expected_status"] 断言
- 文件名由调用方固定为 `test_{tag}.py`，不要依赖首行注释

## 数据加载方式

```python
import yaml
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"

def load_data(resource: str) -> dict:
    with open(DATA_DIR / f"{resource}.yaml") as f:
        return yaml.safe_load(f)
```

## 示例

```python
# test_users.py
import yaml
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"


def load_data(resource: str) -> dict:
    with open(DATA_DIR / f"{resource}.yaml") as f:
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

## 输出格式
只输出一个 ```python 代码块，不要任何解释。
