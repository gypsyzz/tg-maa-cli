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
log_monitor.py       基于 MaaCore TaskChain 回调的实时日志监控
alert_checker.py     复用 MAA updater 的单次未运行提醒检查
maa_config.py        路径和全局配置

install.sh           初次安装 / 更新 systemd 配置
uninstall.sh         删除本项目管理的 systemd 单元

systemd/
  maa-telegram-bot.service.template
  maa-profile.service.template
  maa-profile.timer.template
  maa-update.service.template
  maa-update.timer.template

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

配置静态聊天授权和运行时 Profile 状态保存在 `profiles.yaml`：

```yaml
profile_a:
  chat_id:
  schedule:
    enabled: false
    times:
      - "00:33"
      - "06:33"
      - "14:33"
      - "17:33"
  alert:
    enabled: false
    hours: 24
  log: "OFF"
  lang: "en"

profile_b:
  chat_id:
  schedule:
    enabled: false
    times:
      - "02:00"
      - "16:10"
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

### 从旧版本迁移

旧版本使用 `authorized_chats.yaml` 保存 `Profile 名称 -> chat_id`。升级后，请将每个
非空的 `chat_id` 手动复制到 `profiles.yaml` 中名称相同的 Profile 下：

```yaml
profile_a:
  chat_id: # 在这里填写 authorized_chats.yaml 中 profile_a 的真实整数值
  schedule:
    enabled: false
    times: []
  alert:
    enabled: false
    hours: 24
  log: "OFF"
  lang: "en"
```

每个 Profile 名称（忽略大小写后）和每个 `chat_id` 都必须唯一。完成迁移并确认安装
成功后，旧的 `authorized_chats.yaml` 不再被程序读取，可以自行归档或删除。


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

如果需要强制使用指定的 Python：

```bash
PYTHON=/home/ubuntu/Documents/.venv/bin/python ./install.sh
```

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


## 4. Telegram 命令
命令为 /主 <次> <参数> 结构，以维持主命令数量的简洁。次命令会有提示如何使用。

快速开始
```text
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
/lang
/run
/stop
/help
```

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
maa-update.service
maa-update.timer
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
- `~/.config/maa/`
- maa-cli Task
- maa-cli Profile
- 项目源代码
- Python 虚拟环境
