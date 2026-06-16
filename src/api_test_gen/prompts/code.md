# 代码生成要求

请根据测试用例文档生成 pytest + requests 自动化测试代码。

## 规则
- 每个接口生成一个独立的测试文件
- 文件名由调用方指定，不要自行决定或依赖首行注释
- 使用 class 组织测试，class 名格式：Test{Operation}
- 每个测试方法对应一条用例，docstring 包含用例编号
- 使用 fixtures：base_url, auth_headers（从 conftest.py 获取）
- 环境变量：API_BASE_URL, API_TOKEN
- 不硬编码任何 URL 或凭证
- assert 使用 resp.status_code 和 resp.json()

## 输出格式

只输出一个 `python` 代码块，不要任何解释。
