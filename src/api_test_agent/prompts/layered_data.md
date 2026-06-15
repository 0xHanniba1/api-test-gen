# 测试数据 YAML 生成

根据测试用例文档，为每个资源/tag 生成一个 YAML 数据文件。

## 规则
- 按接口操作分组（如 create_user, get_user）
- 每个操作下按场景命名（如 valid, missing_name, not_found）
- 每个场景包含：
  - body: 请求体（POST/PUT/PATCH 时）
  - params: 查询参数（GET 时）
  - path_params: 路径参数
  - expected_status: 预期状态码
- 文件名格式：{tag}.yaml
- 文件名由调用方指定，不要依赖首行注释

## 示例

```yaml
# users.yaml
create_user:
  valid:
    body:
      name: "test"
      email: "a@b.com"
    expected_status: 201
  missing_name:
    body:
      email: "a@b.com"
    expected_status: 400

get_user:
  valid:
    path_params:
      user_id: 1
    expected_status: 200
  not_found:
    path_params:
      user_id: 99999
    expected_status: 404
```

## 输出格式
只输出一个 ```yaml 代码块，不要任何解释。
