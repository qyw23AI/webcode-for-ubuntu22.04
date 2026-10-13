# WebCodex 使用与后续配置

已安装 WebCodex v0.4.6。Server、Runner 和 Tunnel 保持原有配置。
安装目录：`~/WebCodex`。应用菜单搜索 **WebCodex**，或双击桌面图标，打开本机图形窗口。窗口左侧管理项目，右侧嵌入 WebCodex Runtime 页面。右侧顶部的 **在浏览器打开** 可用系统浏览器打开完整页面；**刷新页面** 只重载嵌入的页面。

已添加一个项目，ChatGPT 连接器也已由你创建。下一步是在 ChatGPT 中启用 WebCodex，验证能读取该项目。

## 1. 添加你的代码项目

在 WebCodex 窗口左上角点击 **选择文件夹添加项目**，在系统文件夹选择器中找到代码目录，检查确认框中的完整路径，然后点击 **添加项目**。左侧项目列表会刷新；需要多个项目时可重复操作。不必使用命令行，也不要把整个主目录作为项目。

需要查看或修改 Server 使用的 Tunnel 凭据时，点击窗口顶部 **Tunnel 设置**。这里会显示当前 Tunnel ID；API key 默认隐藏，可勾选 **显示 API key** 在本机查看。输入新值后点 **保存并检查连接**，确认后窗口会保存私有配置、重启 Tunnel 并检查是否就绪；失败时尝试恢复旧配置。修改期间 ChatGPT 会短暂断线。若更换 Tunnel ID，还须在 ChatGPT 网页版连接器中改选新 ID；本机 Tunnel 就绪不等于 ChatGPT 已经完成连接。不要将 API key 发到聊天或提交到 Git。

这是为当前 Ubuntu 安装提供的本地图形入口：添加操作由已安装的 WebCodex CLI 完成，右侧仍是原有 Runtime 页面。官方 v0.4.6 尚未发布 Linux Desktop 包。图形入口只在当前电脑运行，不会把文件夹选择器暴露到 ChatGPT 或网络。

本机窗口首次打开右侧 Runtime 页面时，会用现有的本机用户凭据进入“项目”视图。点击页面内的锁定/退出后不会自动重新登录。使用 **在浏览器打开** 打开的外部浏览器有独立会话；若它要求登录，使用 `~/WebCodex/installed/environment/webcodex-user-token` 文件中的用户凭据，仅在本机页面填写，不要提交 Git 或发到聊天里。

如果项目已出现在左侧、右侧仍未显示，点击 **刷新页面**，确认右侧停留在“项目”视图且没有搜索或 Runner 筛选。嵌入式 Runtime 直接连接本机 `127.0.0.1`，不会经过桌面代理；外部浏览器若使用代理，需确保本机地址不经过代理。

## 2. 确认 OpenAI Secure Tunnel 已就绪

本机 OpenAI Tunnel 凭据已配置，Tunnel 服务当前运行中，MCP 本地绑定已就绪。此安装使用持久化 Runtime 的 systemd 用户服务；没有安装 WebCodex Desktop。Desktop 文档中的“自动启动”设置不适用于此服务，由 systemd 管理启停。打开 WebCodex 管理页也不会重启已停止的 Tunnel。

检查状态：

```bash
cd ~/WebCodex
./webcodex environment tunnel-status chatgpt \
  --environment-dir /home/qyw/WebCodex/installed/environment
```

应看到 Tunnel running、Tunnel ready 和 local MCP ready。**这些状态只表示 Tunnel 已准备好供 ChatGPT 连接，不代表 ChatGPT 已连接，也不代表端到端调用已成功。** Tunnel ID 可以从 OpenAI Tunnel 页面复制；此处不需要也不应把 API key 粘贴到 ChatGPT。

如果 Tunnel 未就绪，先确认 Tunnel ID 和 API key 都已配置，并检查 OpenAI Tunnel 页面上的连接/权限状态，再重启服务：

```bash
./webcodex environment restart tunnel --profile chatgpt \
  --environment-dir /home/qyw/WebCodex/installed/environment
```

## 3. 在 ChatGPT 网页版添加连接器

1. 打开 [ChatGPT 账户安全设置](https://chatgpt.com/#settings/Security)，在“账户安全与登录”中开启**开发人员模式**。请先阅读 ChatGPT 显示的风险提示；开发人员模式允许添加可能修改或删除数据的连接器。
2. 打开 [ChatGPT 插件页面](https://chatgpt.com/plugins)，创建新插件/连接器，连接方式选择 **Tunnel**。
3. 在 **Available tunnels** 中选择 WebCodex 对应 Tunnel，并核对完整 Tunnel ID。若列表未刷新，可选 **Use tunnel ID instead** 手动填入 Tunnel ID。
4. Authentication 选择 **No Auth / None / No authentication**，阅读风险提示并确认信任此本机 WebCodex，再点击 **Create** 和 **Connect**。

不要把 API key 填入 ChatGPT。若 Tunnel 不显示或被拒绝，检查它是否关联到目标 ChatGPT workspace，以及当前 OpenAI Platform 身份是否有该 Tunnel 的 **Tunnels: Read + Use** 权限。开发人员模式与 Tunnel 权限是两项独立设置。可对照 OpenAI Tunnels 页面上的完整 ID。

连接器保存成功后，回到 ChatGPT 并启用 WebCodex。保存连接器本身不证明连接已建立。当前 WebCodex Runtime 状态页可能仍显示“等待 ChatGPT”；不要把 Tunnel ready 或 Tunnel ID 已复制当作 ChatGPT 已连接的证据。

## 4. 确认配置成功

```bash
cd ~/WebCodex
./webcodex environment status \
  --environment-dir /home/qyw/WebCodex/installed/environment --json
```

确认 `server_reachable`、`authenticated`、`runner_online` 为 `true`，且 `projects_visible` 出现你添加的项目。
然后在 AI 客户端启用 WebCodex，先尝试：“列出可用项目，读取指定项目的 README，不修改文件。”实际读取成功才表示端到端连接已完成。

## 常用维护

```bash
# 查看服务
systemctl --user status webcodex.service webcodex-runner-1000.service
# 停止服务
systemctl --user stop webcodex-runner-1000.service webcodex.service
# 启动服务（点击图标也会启动）
systemctl --user start webcodex.service webcodex-runner-1000.service
```

WebCodex 提供本机文件、Git、命令和测试工具；AI 模型来自客户端。项目的依赖和编译器需自行安装。文件内容与命令结果可能返回 AI 客户端；Runner 执行命令具有 qyw 账户权限，项目目录限制不等于系统沙箱。

多台电脑意味着每台持有代码的电脑各运行 Runner，并连接同一个 Server；它不会自动同步代码或合并 Git。

更详细的安装记录见 [部署说明.md](部署说明.md)。Tunnel 已配置且运行正常，本机已有一个登记项目；ChatGPT 侧的实际读取仍需在网页版验证。
