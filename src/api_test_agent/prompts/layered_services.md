# 业务编排层代码生成

根据同一 tag 下的接口列表，推断 CRUD 业务流程并生成编排类。

## 规则
- 每个 tag 生成一个编排类，类名格式：{Tag}Flow（如 UserFlow, PetFlow）
- 构造函数接收对应的 Api 类实例
- 根据接口的 CRUD 语义自动推断常见业务流程：
  - create_and_get: 创建资源后立即查询验证
  - full_lifecycle: 创建 → 查询 → 更新 → 删除 → 验证删除
  - batch_create: 批量创建（如果有 list 接口）
- 方法内部调用 Api 类的方法，通过响应数据串联各步骤
- 只推断合理的流程，不要凭空编造不存在的接口调用
- 文件名由调用方固定为 `{tag}_flow.py`，不要自行决定或依赖首行注释

## 示例

```python
# user_flow.py
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

## 输出格式
只输出一个 ```python 代码块，不要任何解释。
