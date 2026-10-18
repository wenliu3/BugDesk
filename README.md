# BugDesk · Bug 提交助手

把测试现场的 Bug 文件夹，整理成可核对、可提交的缺陷报告。

BugDesk 是面向 Windows 测试人员的本地工作台：每个子文件夹对应一条 Bug，自动关联截图和视频，再填写前置条件、复现步骤、实际结果与预期结果。可以离线整理和导出，也可以连接禅道，在人工审核后提交。

**Python 3.11+ · 标准库运行 · 无前端构建 · 浅色 / 深色模式 · MIT**

## 下载 1.0.0

软件与 WorkBuddy 技能从 **1.0.0** 开始作为首个正式版本发布。

前往 [GitHub Releases](https://github.com/wenliu3/BugDesk/releases/latest) 下载：

| 文件 | 用途 |
| --- | --- |
| `BugDesk-Windows-1.0.0.zip` | 推荐。解压后双击 `BugDesk.exe`，草稿保存在旁边的 `BugDesk-data`。无需安装 Python。 |
| `BugDesk-1.0.0-Windows-x64.exe` | 单独的 Windows 64 位程序，双击运行；默认在 Windows 本地应用数据目录保存草稿。 |
| `BugDesk-WorkBuddy-Skill-1.0.0.zip` | 可选，导入 WorkBuddy 的配套技能包；不需要解压后再压缩。 |
| `SHA256SUMS.txt` | 下载文件的 SHA-256 校验值。 |

## 界面预览

以下截图全部使用合成示例，不包含真实项目、人员、账号或内网地址。WorkBuddy 画面展示技能选择和任务输入，不代表任务已发送或执行完成。

### 整理 Bug：清单与编辑区分别滚动

![浅色工作台](docs/screenshots/workbench-light.png)

### 深色模式：一键切换并记住选择

![深色工作台](docs/screenshots/workbench-dark.png)

### WorkBuddy：核对用例，再导入草稿

![WorkBuddy 用例核对](docs/screenshots/workbuddy-review.png)

### 在 WorkBuddy 中选择技能并输入任务

![WorkBuddy 调用 BugDesk 技能](web/help/workbuddy-3-workbuddy.png)

### 提交预览：检查公共信息与完整描述

![提交预览](docs/screenshots/submission-preview.png)

## 可以做什么

- **扫描文件夹**：子文件夹名称作为初始标题，自动收集其中的图片、视频和其他附件，保留原始文件。
- **整理测试事实**：编辑四项描述，自动保存；支持图片、视频预览和附件排除。
- **复用公共配置**：产品、版本、指派人、反馈者等整批复用；个别 Bug 可在「本条设置」中单独覆盖。
- **粘贴用例**：读取 HTML 表格、TSV 和多行单元格，核对字段与关联后填入草稿。
- **可选 WorkBuddy 整理**：配套技能整理失败用例，提出关联建议；人工核对后导入，不自动审核或提交。
- **审核与提交**：查看完整报告，审核后连接禅道提交；首次实际提交限制为一条。
- **导出与迁移**：导出 Markdown、CSV 或 JSON 备份，支持重新导入。

## 快速开始

源码运行需要 **Windows、Python 3.11 或更新版本，以及现代浏览器**。日常运行只使用 Python 标准库，无需安装额外依赖。

```powershell
git clone git@github.com:wenliu3/BugDesk.git
cd BugDesk
python app.py
```

也可以双击仓库中的 **启动开发版.cmd**。它优先使用指定的解释器，再尝试 Windows Python Launcher 和 PATH 中的 Python，草稿保存在项目的 `.local` 目录。

首次打开时点击 **先试试示例数据**，即可体验完整界面。示例数据不能提交到禅道。

如果 `python` 不是 3.11 或更新版本，请选择正确的解释器；Windows Python Launcher 用户可使用 `py -3.11 app.py`。

## 日常使用

建议按日期整理附件目录：

```text
Bug 附件/
└─ 2026-10-18/
   ├─ 搜索无结果时未显示空状态/
   │  └─ 截图.png
   └─ 保存失败后丢失已填内容/
      ├─ 截图.png
      └─ 录屏.mp4
```

1. 选择日期文件夹，点击「扫描 Bug」。
2. 填写公共设置，补齐每条 Bug 的测试事实；需要时通过「更多」粘贴用例。
3. 检查图片、视频和「提交预览」，确认事实正确后审核。
4. 导出报告，或连接自己的禅道并提交已审核条目。

右上角月亮 / 太阳按钮切换主题；「更多」中提供 WorkBuddy 使用说明、导出、备份和关闭工具等操作。

| 快捷键 | 操作 |
| --- | --- |
| `Ctrl + S` | 立即保存 |
| `Ctrl + Enter` | 审核当前 Bug |
| `Alt + ↑ / ↓` | 切换相邻 Bug |

## 可选：接入 WorkBuddy

从 [Releases](https://github.com/wenliu3/BugDesk/releases/latest) 下载 `BugDesk-WorkBuddy-Skill-1.0.0.zip`，按 WorkBuddy 客户端的技能导入流程安装。技能源码位于 [integrations/bugdesk-workbuddy](integrations/bugdesk-workbuddy)，`SKILL.md`、`scripts` 和 `references` 位于技能 ZIP 根目录。

在 BugDesk 扫描 Bug 后，开启「WorkBuddy 整理」中的本机连接，复制当次任务并附上失败用例。等建议回传后，逐条核对来源用例和四项事实，再导入草稿。

连接最长有效 60 分钟；技能只能读取受限上下文并暂存建议。是否把测试资料发送给 AI 服务，由你和所使用的客户端决定。使用前请确认资料允许发送到相应服务。

详细步骤见 [WorkBuddy 接入说明](WorkBuddy接入说明.txt)。

## 禅道兼容范围

连接器基于禅道 **18.11 经典页面接口**实现，包含登录、菜单读取、附件上传以及创建后核验，并使用本地模拟服务测试。

不同部署的单点登录、验证码、定制字段、权限和附件限制可能需要适配；本项目不保证所有禅道版本直接兼容。首次提交仅允许一条，确认编号和附件后再继续批量操作。结果不确定的条目需要人工核对，避免重复创建。

## 数据与隐私

- 服务仅监听 `127.0.0.1`，整理、预览和导出可离线完成。
- 扫描不会移动、删除或改写原始 Bug 证据文件。
- 源码开发启动器使用项目 `.local`；直接运行默认使用 Windows 本地应用数据目录。
- 自行打包的便携版在 `portable.flag` 同目录的 `BugDesk-data` 保存草稿和配置。
- 禅道密码与登录会话仅保存在当前进程内存；AI 整理不需要禅道账号。
- 本机草稿、连接文件、导出报告、IDE 配置、缓存和打包产物均不应提交到仓库，已设置相应忽略规则。

## 开发与检查

```powershell
python -m unittest discover -s tests -v
node tests/test_web_behavior.js
```

Python 测试使用本地文件和模拟服务，不连接真实公司系统。前端检查需要 Node.js，运行程序本身不需要 Node.js。

修改 `web` 后刷新浏览器即可；修改 Python 后需要重新启动程序。详见 [开发运行说明](开发运行说明.md) 和 [接口与行为约定](CONTRACT.md)。

## 自行打包 Windows 程序

```powershell
python -m pip install -r requirements-build.txt
python build_windows.py --release 1.0.0
```

产物生成在 `release` 目录，包含便携版 ZIP、单独的 EXE、配套技能 ZIP 和校验值。脚本会核对软件与技能版本，并只收集明确列出的交付文件。生成的 EXE、用户数据和发布压缩包不纳入源码提交。

## 许可证

本项目采用 [MIT License](LICENSE)。
