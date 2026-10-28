# MAA 电报控制 Bot

一个用于控制 `maa-cli` 的 Telegram Bot 控制层，支持：

- 仅授权的电报用户可以控制
- 用户独立 MAA 任务
- 用户级 systemd Service 和 Timer
- 持久化运行计划
- 实时日志监控
- 任务序列查看
- Fight 关卡添加 / 删除
- 中英文界面
- MAA 自动更新

注：不支持编辑基建等复杂任务，请自行提供json

## 项目结构

```text
maa_control.py       应用启动和生命周期管理
handlers.py          Telegram 命令和按钮回调处理
telegram_ui.py       状态文本、按钮、Telegram 格式化
profile_store.py     profiles.yaml 读写和聊天授权
i18n.py              英文 / 中文界面翻译
systemd_utils.py     用户级 Service / Timer / Journal 辅助功能
task_store.py        任务 JSON 和 Fight 编辑
templates/fight.json 无已有 Fight 任务时使用的只读安全模板
log_monitor.py       基于 MaaCore TaskChain 回调的实时日志监控
alert_checker.py     复用 MAA updater 的单次未运行提醒检查
schedule_health_checker.py  按 Profile 定时检查本机容器和 Windows MAA
maa_config.py        路径和全局配置

install.sh           初次安装 / 更新 systemd 配置
uninstall.sh         删除本项目管理的 systemd 单元

systemd/
  maa-telegram-bot.service.template
  maa-profile.service.template
  maa-profile.timer.template
  maa-schedule-check.service.template
  maa-update.service.template
  maa-update.timer.template
  maa-container-health.service.template
  maa-container-health.timer.template

tools/
  gui2cli.py         将 Windows上的 gui.new.json 转换为 maa-cli 任务 JSON
```


## 1. 配置

复制示例配置文件：

```bash
cp telegram_config.yaml.example telegram_config.yaml
cp profiles.yaml.example profiles.yaml
```

在 `telegram_config.yaml` 中填写 Telegram Bot Token。然后在 `profiles.yaml`
中为每个 Profile 填写真实的 Telegram `chat_id`。`chat_id` 必须是非零整数：
私聊通常使用正数，群组或超级群组可以使用负数。空值、布尔值、字符串以及重复
的 `chat_id` 都会导致配置验证失败。

向正在运行的 Bot 发送 `/chat_id` 即可获取当前聊天 ID，回复格式为 `chat_id: 123456789`。
此命令无需授权，也可用于尚未配置的聊天；在群组中返回群组 ID，而非发送者的用户 ID。
`/start` 和 `/status` 仍需授权，并保持原有控制面板行为。

配置静态聊天授权和运行时 Profile 状态保存在 `profiles.yaml`：

```yaml
profile_a:
  chat_id:
  admin: false
  schedule:
    run_enabled: false
    check_enabled: false
    times:
      - "00:33"
      - "06:33"
      - "14:33"
      - "17:33"
  schedule_check:
    container_name: ""
    windows_host: ""
    windows_user: ""
    ssh_identity: ""
    windows_process: "MAA"
    windows_executable: ""
    windows_start_task: ""
  alert:
    enabled: false
    hours: 24
  log: "OFF"
  lang: "en"

profile_b:
  chat_id:
  admin: false
  schedule:
    run_enabled: false
    check_enabled: true
    times:
      - "02:00"
      - "16:10"
  schedule_check:
    container_name: "redroid-profile-b"
    windows_host: "192.168.1.125"
    windows_user: "windows_user"
    ssh_identity: "~/.ssh/id_windows"
    windows_process: "MAA"
    windows_executable: 'C:\Users\windows_user\Documents\MAA\MAA.exe'
    windows_start_task: "MAA Telegram profile_b"
  alert:
    enabled: false
    hours: 24
  log: "OFF"
  lang: "zh"
```

手动编写 YAML 时，建议给 `ON` / `OFF` 加上引号，以避免被 YAML 解析为布尔值。

代码同时兼容 PyYAML 将未加引号的 `ON` / `OFF` 解析为布尔值的情况。

`alert` 保存每个 Profile 的游戏未运行提醒设置。`hours` 只接受正整数小时，默认 24。
提醒记录保存在 `~/.config/maa-tg-bot/alert_state.yaml`，同一次上次操作只会提醒一次。

`schedule_check` 创建独立于 MAA 自动运行的重复检查 Timer，但复用该 Profile 的
`schedule.times`。`schedule.run_enabled` 和 `schedule.check_enabled` 互斥，不能同时开启；
因此可以关闭前者、开启后者，只在同一组时间检查 Windows 上的 `MAA.exe` 是否打开，
并在 `container_name` 非空时检查该本机 Redroid 容器、Android 和 ADB 是否健康。留空会跳过容器检查。
检查失败时，每次 Timer 触发都会提醒；后续定时时间会重新检查，不使用跨次去重。

Telegram 使用 `/winmaa` 查看 systemd Timer、本机容器和 Windows MAA 的实时状态。
`/winmaa check` 立即检查已配置的容器和 Windows MAA；
`/winmaa monitor` 查看检查 Timer 状态，`/winmaa monitor on|off` 控制重复检查；
`/winmaa app` 查看 Windows MAA 状态，`/winmaa app on|off` 通过 Windows 的交互式
Scheduled Task 启动 MAA，或只停止 `windows_executable` 指定的 MAA。

`windows_start_task` 必须是 Windows 上已经建立的任务名称，任务应设置为“仅当用户登录时
运行”，以便 MAA GUI 出现在当前桌面。SSH 服务会话直接启动 GUI 时，进程可能出现在不可见
的服务会话中，因此 `/winmaa app on` 只触发该交互式任务。

Windows 检查使用批处理 SSH 公钥认证，密钥不能要求交互输入。

使用 `/container restart` 重启当前 Profile 的 `schedule_check.container_name` 指定的本机
Redroid 容器。命令不接受容器名称参数，不需要配置 Windows SSH 或启用定时检查。
重启会中断容器内正在进行的任务；Bot 随后等待 Android 启动（约 120 秒超时），并关闭
蓝牙以避免模拟蓝牙服务崩溃。Docker 重启、启动检查或关闭蓝牙失败时会返回错误。
Bot 的运行用户需要拥有 Docker 访问权限。
`/container health` 检查容器运行状态、Android 启动状态，并通过容器 `5555/tcp` 映射的
本机端口执行 ADB Android ID 读取，避免将 Docker 运行中但 ADB 离线误报为健康。
检查会先通过 `adb connect` 连接映射的本机地址，再读取 Android ID；即使容器在本机，
也需要建立 ADB 连接，`adb -s` 只选择设备。检查不会重启容器、断开已有连接或重启 ADB 服务，
Android ID 不会显示在回复中；主机需安装 `adb`。
`/status`、`/start` 和状态刷新按钮会显示同一健康检查的结果；`/winmaa`、
`/winmaa check` 和重复检查 Timer 也使用该检查，不再只判断 Docker 是否运行。

将私聊 Profile 设置为 `admin: true` 后，该 Profile 可以代表其他 Profile 执行受限命令：

```text
/sudo lun fight add 1-7
/sudo lun schedule add 12:00
/sudo lun winmaa app on
/sudo lun container restart
/sudo lun container health
/sudo lun run
/sudo lun stop
```

委托命令仅允许 `fight`、`schedule`、`winmaa`、`container`、`run` 和 `stop`；子命令和参数会原样转发，容器重启只使用目标 Profile 配置的容器名称。管理员校验同时要求消息的 Telegram
`user_id` 与管理员 Profile 的 `chat_id` 完全相同，因此群聊 Profile 即使误设 `admin: true`
也无法取得管理员权限。

## 2. MAA Profile / Task

对于每个身份，systemd Worker 会运行：

```text
profile_a -> maa run profile_a -p profile_a
profile_b -> maa run profile_b -p profile_b
```

因此需要创建名称一致的 maa-cli 连接 Profile 和任务 JSON，例如：

```text
~/.config/maa/profiles/profile_a.json
~/.config/maa/profiles/profile_b.json

~/.config/maa/tasks/profile_a.json
~/.config/maa/tasks/profile_b.json
```

Profile JSON 可以从 `default.json` 复制，然后只修改每个 Profile 对应的：

```text
.connection.address
```

以连接不同的 ADB 地址。


## 3. 安装 / 更新

运行：

```bash
./install.sh
```

如果当前没有激活 Python 虚拟环境，安装程序会在项目目录中自动创建：

```text
.venv
```

如果需要指定用于创建项目虚拟环境的基础 Python：

```bash
PYTHON=/usr/bin/python3 ./install.sh
```

无论当前是否已激活其他虚拟环境，依赖和 systemd Service 都只使用本项目的 `.venv`。

安装脚本支持重复执行。

当增加 / 删除授权 Profile，或者修改 systemd 配置后，可以重新运行：

```bash
./install.sh
```

如果希望用户级 Service 和 Timer 在系统启动后、用户尚未登录时也能运行，请执行一次：

```bash
sudo loginctl enable-linger "$USER"
```

这是主机级的一次性设置。


### 全局 MAA 自动更新

安装程序会创建一组全局 updater：

```text
maa-update.service
maa-update.timer
```

Updater Service 会执行：

```text
maa self update
maa update
检查已开启的游戏提醒
```

三个步骤会按顺序执行；任一步失败时，后续步骤不会执行，并且 Service 会标记为失败。
游戏提醒与 MAA updater 一样频繁地检查，不会创建额外的 Service 或 Timer。

Timer 每小时运行一次：

```ini
OnCalendar=hourly
```

检查一次更新。

### 每小时容器健康提醒

`maa-container-health.timer` 每小时整点独立运行一次，与 MAA updater 和各 Profile 的
定时任务开关无关。它检查 `redroid13-houdini-1`、`redroid13-houdini-2`、
`redroid13-houdini-3` 的 Docker、Android 和 ADB 健康状态。
每个故障容器会单独向 `YAN` Profile 配置的聊天发送原因；全部健康时不发消息。
同一容器的持续故障只提醒一次；检查到它恢复健康后，再次故障才会重新提醒。
记录持久化在 `~/.config/maa-tg-bot/container_health_state.yaml`，重启 Bot 或主机不会重复提醒。
不会自动重启容器；主机恢复后会补跑错过的检查。`--no-notify` 不修改提醒记录。

接收人和容器清单在 `systemd/maa-container-health.service.template` 中指定；安装前需有
有效的 `YAN` Profile。`install.sh` 安装该 timer，并保留手动禁用状态，`uninstall.sh` 会移除它。
手动只检查、不发送通知：

```bash
.venv/bin/python schedule_health_checker.py --profile YAN \
  --containers redroid13-houdini-1 redroid13-houdini-2 redroid13-houdini-3 --no-notify
```

任一检查失败时进程返回非零退出码（即使提醒已发送），方便从 systemd 查看故障。


## 4. Telegram 命令
命令为 /主 <次> <参数> 结构，以维持主命令数量的简洁。次命令会有提示如何使用。

快速开始
```text
/chat_id
/start
/status
```

其他主命令
```text
/schedule
/task
/fight
/log
/alert
/winmaa
/container restart
/container health
/lang
/run
/stop
/help
```

`/fight add` 会静默将全角或其他 Unicode 横线规范为 ASCII `-`。不含横线的关卡名只要以
`anni` 开头（忽略大小写），就会规范为 `Annihilation`。关卡名还会与已安装 MAA 资源中的
关卡代码及导航名称进行不区分大小写的匹配：唯一匹配会自动改为标准大小写；未知名称会给出
相近建议；多个仅大小写不同的匹配会要求用户明确填写标准名称。

自动日志模式：

- `OFF`：不自动发送任务或进程结果。
- `ON`：仅发送 MaaCore 任务错误，以及 MAA Profile Service 的非成功退出。
- `FULL`：发送所有 MaaCore 任务结果，并发送 MAA Profile Service 的非成功退出。

进程级错误通知包含 systemd 结果、进程状态，以及数量受限的相关 MaaCore 或 journal
错误行。同一次运行已经发送 `TaskChainError` 时，不会再重复发送进程退出通知。

游戏未运行提醒：

```text
/alert
/alert on
/alert off
/alert time 24
```

`/alert time` 只接受正整数小时。达到设定时限后只发送一次简短提醒；关闭再开启或
修改时限不会重复提醒同一次上次操作，只有 MAA Profile Service 的上次操作时间变化后
才会允许下一次提醒。提醒检查与现有 MAA updater 一样频繁。

## 5. Windows GUI 配置转换

从 Windows 复制：

```text
<MAA folder>\config\gui.new.json
```

到 Linux，然后执行：

```bash
python tools/gui2cli.py gui.new.json \
  "$(maa dir config)/tasks/profile_a.json"
```

转换工具使用位置参数：

```text
gui2cli.py INPUT OUTPUT
```


## 6. Service / Timer 管理

查看所有 MAA 定时服务：

```bash
systemctl --user list-timers 'maa-*.timer' --all
```

本项目管理的 systemd 单元
```bash
maa-telegram-bot.service
maa-<profile>.service
maa-<profile>.timer
maa-<profile>-schedule-check.service
maa-<profile>-schedule-check.timer
maa-update.service
maa-update.timer
maa-container-health.service
maa-container-health.timer
```

## 7. 卸载 systemd 配置

运行：

```bash
./uninstall.sh
```

以下内容会被保留：

- `telegram_config.yaml`
- `profiles.yaml`
- `~/.config/maa-tg-bot/alert_state.yaml`
- `~/.config/maa-tg-bot/container_health_state.yaml`
- `~/.config/maa/`
- maa-cli Task
- maa-cli Profile
- 项目源代码
- Python 虚拟环境
