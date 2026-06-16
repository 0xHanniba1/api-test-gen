# 生成代码质量校验设计

## 概述

在代码生成后自动执行质量校验（Python 语法、YAML 格式、pytest collect），失败时将错误反馈给 LLM 重试（最多 2 次）。

## 校验流程

```
generate() 生成文件
       ↓
  ┌─ validate() ─┐
  │  1. Python 语法检查（ast.parse）
  │  2. YAML 格式检查（yaml.safe_load）
  │  3. pytest collect 检查（pytest --collect-only）
  └───────────────┘
       ↓
   通过？──是──→ 输出文件
       │
      否
       ↓
   错误反馈给 LLM，重新生成出错的文件
       ↓
   再次 validate()
       ↓
   通过？──是──→ 输出文件
       │
      否（已重试 2 次）
       ↓
   抛出校验错误 + CLI 非零退出，不写入无效代码
```

## 校验项

| 校验 | 方式 | 检查内容 |
|------|------|---------|
| Python 语法 | `ast.parse(code)` | SyntaxError、缩进错误 |
| YAML 格式 | `yaml.safe_load(content)` | YAML 解析错误 |
| pytest collect | `pytest --collect-only` | import 缺失、fixture 名错误、类名不符合规范 |

## 关键设计点

- **只重新生成出错的文件** — 不重新生成整个项目，节省 LLM 调用
- **pytest collect 需要临时目录** — 先将全部文件写入临时目录，再执行 collect
- **flat 和 layered 两种模式都做校验** — 校验逻辑通用，不区分架构模式
- **重试时把错误信息拼入 prompt** — 例如 `"上次生成的代码有语法错误：SyntaxError at line 15。请修复并重新生成。"`
- **最多重试 2 次** — 避免无限循环，最终仍失败则抛出 `GenerationValidationError`
- **收集超时** — `pytest --collect-only` 使用当前 Python 解释器，30 秒后终止
- **写盘隔离** — 只有校验通过后才进入安全写盘，拒绝目录逃逸与路径冲突

## 代码改动范围

### 新增文件

| 文件 | 职责 |
|------|------|
| `src/api_test_gen/generator/validator.py` | `validate_python()`、`validate_yaml()`、`validate_collect()` |
| `src/api_test_gen/generator/common.py` | 两种生成器共用的校验重试与最终失败异常 |
| `src/api_test_gen/output.py` | 生成文件安全写盘 |
| `tests/test_validator.py` | 校验器单元测试 |

### 修改文件

| 文件 | 改动 |
|------|------|
| `src/api_test_gen/generator/code.py` | `generate()` 后调用校验，失败时重试 |
| `src/api_test_gen/generator/layered.py` | 同上 |
