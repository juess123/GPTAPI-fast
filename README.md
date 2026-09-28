# 报价表（极速版）

将图片、规格文档、文本和已有 Excel 表上传给 GPT，按材料整理内容并生成一个可下载的 Excel 工作簿。项目只保留 Excel 生成链路。

## 工作流程

```text
上传的图片 / 文本 / 规格 / Excel + 补充提示词
                    ↓
              GPT 阅读输入材料
                    ↓
        生成 make_xlsx.py 工作簿脚本
                    ↓
       本机 Python 执行并检查 Excel 文件
                    ↓
             final_quote.xlsx
```

模型生成的脚本在本机执行，因此最终交付是有效的 `.xlsx` 文件。脚本输出仅限于本次任务目录。

## 环境准备

Windows PowerShell 中首次运行或依赖变更后执行：

```powershell
Set-Location E:\GPTAPI-fast
& .\setup_environment.ps1
```

项目使用 `.venv/` 隔离 Python 依赖。基础依赖锁定在 `requirements.txt`，只包含 Web 服务、Excel 读写、图片处理和依赖管理所需的包。GPT 如需其他 PyPI 包，可在响应中声明，项目会将它们安装到当前任务独立的 Python 工具目录。

在 `.env` 配置模型网关：

| 变量 | 说明 |
| --- | --- |
| `CNXMAI_API_KEY` | 网关密钥 |
| `CNXMAI_BASE_URL` | 网关 API 根地址 |
| `CNXMAI_CHAT_URL` | Chat Completions 接口 |
| `CNXMAI_MODEL` | 使用的模型名称 |
| `CNXMAI_MAX_TOKENS` | 单次回复最大 Token 数 |
| `CNXMAI_TIMEOUT` | 请求超时，例如 `40m` |
| `WEBAPP_HOST` / `WEBAPP_PORT` | Web 监听地址和端口；默认 `0.0.0.0:8000` |

## 启动 Web 界面

```powershell
$env:WEBAPP_HOST="127.0.0.1"
$env:WEBAPP_PORT="9000"
& .\.venv\Scripts\python.exe webapp\server.py
```

浏览器打开 `http://127.0.0.1:9000`。若 9000 已占用，可更改 `WEBAPP_PORT`。服务只监听本机时使用 `127.0.0.1`；需要局域网访问时设置 `WEBAPP_HOST="0.0.0.0"`，并仅在可信网络中开放端口。当前 Web 界面没有登录认证。

页面支持拖放、点击选择和 `Ctrl+V` 粘贴文件/截图。可选格式包括常见图片、`.md`、`.txt`、`.json`、`.csv`、`.yaml`、`.ini`、`.log`、`.xlsx` 和 `.xlsm`。Excel 输入会在本机提取可读单元格文本后随请求发送；图片作为多模态图片附件发送。文本提示可以补充工作簿的格式和内容要求。

生成完成后页面提供 `final_quote.xlsx` 下载。每个任务的输入、脚本、日志和结果都保存在 `webapp/workspaces/<任务号>/`；服务重启后历史任务仍可查看。

## 命令行流程

`input/` 目录下放置输入材料，然后执行：

```powershell
& .\.venv\Scripts\python.exe pipeline\ask_model.py --dry-run
& .\.venv\Scripts\python.exe pipeline\fast_workflow.py --input-dir input --gen-dir pipeline\generated --out-dir output --task-packages pipeline\task_packages
```

第一条只预览即将发给模型的提示词，不发起请求。Web 模式会为每个任务分别指定输入、脚本、输出和依赖目录。

每次运行会在输出根目录下创建时间戳子目录，内含 `final_quote.xlsx` 及必要的诊断文件；成功时 `LATEST_RUN.txt` 指向最新成品。

## 验证与排错

- `pipeline/build.py` 执行 GPT 生成的脚本，并用 `openpyxl` 确认工作簿可以打开且至少包含一个工作表。
- 运行失败会保留诊断报告；流水线可请求 GPT 对脚本进行有限次数的局部修复。
- 可以使用 `webapp/tools/verify_out.py <工作簿路径>` 独立检查 Excel 的工作表、公式和结构。
- `webapp/tools/test_sse.py` 用于检查 Web 进度事件流。

除模型网关请求外，上传材料和任务产物保存在本机工作区。
