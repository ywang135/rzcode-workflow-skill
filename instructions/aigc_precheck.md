# AIGC 检查流程

用于在上传源代码文档后，通过软宝宝进行 AIGC 预检，并下载预检报告。可循环执行：上传文档 → AIGC 检查 → 更新文档 → 重新上传检查。

## 前置条件

- 项目中已上传源代码文件，且为 `.docx` 格式。
- 账户积分不少于 3.6，不足时提示用户前往 https://rzcode.vip/purchase 充值。
- 已完成 SKILL.md 的 Step 1（rzcode-mcp 可用）。

## Step 1. 确定项目

按软件名与项目名匹配，或使用用户已确认的上下文；如无合适项目，调用 `rzcode_create_project` 创建本地（local）项目。需与用户确认 project_id。

## Step 2. 上传源代码

调用本 skill 的脚本上传源代码 `.docx`：

```bash
python scripts/upload_file.py --project-id {project_id} --file-type source_code /path/to/源代码.docx
```

- 接口：`POST /api/projects/{project_id}/upload/source_code`（X-API-Key 认证）。
- 新上传的文件会覆盖原有源代码文件。

## Step 3. 开启检查并等待完成

1. 调用 `rzcode_create_or_get_ongoing_task`，参数 `task_type=PRECHECK_SOURCE_CODE_AIGC`。
2. 记录返回的 `task_id`，告知用户可在网页端查看进度：`https://rzcode.vip/home/projects/{project_id}/?task_id={task_id}`。
3. 每 **60 秒** 调用一次 `rzcode_get_project_status` 轮询，直到 `task_status` 变为 `completed` 或 `failed`。
4. 若返回 `created: false` 且存在其他进行中的任务，向用户说明原因，等待其完成后再重试。
5. 若 `failed`，向用户返回失败信息，并引导其修正后重试。

## Step 4. 下载报告

任务 `completed` 后，下载 AIGC 预检报告：

- `https://rzcode.vip/api/projects/{project_id}/download/aigc_precheck`（需 X-API-Key 请求头，或已登录浏览器）。
- 输出文件名：`{project_name}_AIGC预检报告{后缀}`（后缀与服务端保存的报告文件一致）。

## 循环

根据报告修改源代码文档后，从 Step 2 重新执行。

## 提示

- 每次检查消耗 3.6 积分。
- 上传与检查前，应与用户确认待检查的文件路径。
