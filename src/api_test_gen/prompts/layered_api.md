# 接口封装层代码生成

根据 API 接口定义，为每个资源/tag 生成一个封装类。

## 规则
- 每个 tag 生成一个类，类名格式：{Tag}Api（如 UsersApi, PetsApi）
- 每个接口生成一个方法，方法名用 snake_case 描述操作（如 create_user, get_pet_by_id）
- 方法参数：path 参数作为方法参数，request body 作为 body: dict 参数，query 参数作为 params: dict 参数
- 构造函数接收 HttpClient 实例
- 方法调用 self.client 的 get/post/put/delete/patch 方法
- 不在方法内做任何断言或数据处理，只负责发送请求并返回 response
- 文件名由调用方固定为 `{tag}_api.py`，不要依赖首行注释

## 示例

```python
# users_api.py
from base.client import HttpClient


class UsersApi:
    def __init__(self, client: HttpClient):
        self.client = client

    def create_user(self, body: dict):
        return self.client.post("/api/users", json=body)

    def get_user(self, user_id: int):
        return self.client.get(f"/api/users/{user_id}")
```

## 输出格式
只输出一个 ```python 代码块，不要任何解释。
