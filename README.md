# MAA Telegram Control Bot

A Telegram control layer for `maa-cli` with:

- one Telegram chat -> one named MAA profile/task (`profile_a`, `profile_b`, ...)
- user-level systemd services and timers
- persistent schedules
- persistent log modes (`OFF`, `ON`, `FULL`)
- task sequence display
- Fight stage add/remove support
- automatic invocation-specific MAA log handling

## Repository layout

```text
maa_control.py       application startup/lifecycle
handlers.py          Telegram commands and callback handlers
telegram_ui.py       status text, buttons, Telegram formatting
profile_store.py     profiles.yaml read/write
i18n.py              English/Chinese UI translations
systemd_utils.py     user services/timers/journal helpers
task_store.py        task JSON + Fight editing
log_monitor.py       per-InvocationID automatic log monitoring
maa_config.py        paths/config/authorization

install.sh           initial/update systemd setup
uninstall.sh         remove project-owned systemd units

systemd/
  maa-telegram-bot.service.template
  maa-profile.service.template

tools/
  gui2cli.py         convert Windows gui.new.json to a maa-cli task JSON
```

## 1. Configuration

Copy the examples:

```bash
cp telegram_config.yaml.example telegram_config.yaml
cp authorized_chats.yaml.example authorized_chats.yaml
cp profiles.yaml.example profiles.yaml
```

Set your Telegram token in `telegram_config.yaml`.

Set static chat authorization:

```yaml
profile_a: 123456789
profile_b: 987654321
```

Runtime profile state is stored in `profiles.yaml`:

```yaml
profile_a:
  schedule:
    enabled: false
    times:
      - "00:33"
      - "06:33"
      - "14:33"
      - "17:33"
  log: "OFF"
  lang: "en"

profile_b:
  schedule:
    enabled: false
    times:
      - "02:00"
      - "16:10"
  log: "OFF"
  lang: "zh"
```

Quote `ON`/`OFF` in hand-written YAML for clarity. The code also accepts
PyYAML boolean interpretations of unquoted `ON`/`OFF`.

## 2. MAA profiles/tasks

For each identity, the systemd worker runs:

```text
profile_a -> maa run profile_a -p profile_a
profile_b -> maa run profile_b -p profile_b
```

Therefore create matching maa-cli connection profiles and task JSONs, e.g.:

```text
~/.config/maa/profiles/profile_a.json
~/.config/maa/profiles/profile_b.json

~/.config/maa/tasks/profile_a.json
~/.config/maa/tasks/profile_b.json
```

The profile JSONs can be copies of `default.json` with only
`.connection.address` changed for each ADB endpoint.

## 3. Install / update

Run:

```bash
./install.sh
```

If no Python virtual environment is active, the installer creates `.venv`
inside the repository. To force a specific Python:

```bash
PYTHON=/home/ubuntu/Documents/.venv/bin/python ./install.sh
```

The installer is idempotent. Rerun it after adding/removing authorized profile
names or after changing the systemd setup.

For user services and timers to run at boot even before login:

```bash
sudo loginctl enable-linger "$USER"
```

This is a one-time host setting.

## 4. Telegram commands

```text
/start
/status

/schedule
/schedule set 00:33 06:33 14:33 17:33
/schedule add 12:00
/schedule remove 12:00
/schedule on
/schedule off

/task
/task long

/fight
/fight add 1-7
/fight add 1-7 0
/fight remove 5

/log
/log ON
/log OFF
/log FULL

/lang
/lang en
/lang zh

/run
/stop
/help
```

### Fight insertion position

`/fight add STAGE` appends after the last existing Fight task.

`/fight add STAGE 0` inserts before all existing Fight tasks.

`/fight add STAGE 1` inserts after the first existing Fight, etc.

`/fight remove INDEX` uses the overall task-sequence index and rejects the
operation if that task is not a Fight.

## 5. Log modes

`OFF`
: Send no automatic run logs.

`ON`
: Inspect only MAA subtask summary lines that were actually emitted. Send a
Telegram message only for summary statuses other than `Completed`. Missing
later tasks and systemd exit state are deliberately ignored, so manual stops
are not inferred to be failures.

`FULL`
: Send the complete systemd journal for every MAA invocation.

The inline Log button toggles `OFF <-> ON`. If currently `FULL`, clicking the
button changes it to `OFF`. Enter FULL explicitly with `/log FULL`.

Logs are filtered using the current systemd `InvocationID`, so previous runs
are excluded.


## UI language

Language is persistent per profile in `profiles.yaml`:

```yaml
profile_a:
  lang: "en"

profile_b:
  lang: "zh"
```

Change it from Telegram:

```text
/lang
/lang en
/lang zh
```

`/status` is an alias of `/start`.

When `lang: "zh"` is selected, the bot's normal UI text, buttons, command
descriptions, schedule/status pages, confirmations, and automatic log titles
are shown in Chinese. Raw MAA/systemd log content and MAA task type/stage names
are not translated.

## 6. Windows GUI conversion

Copy Windows:

```text
<MAA folder>\config\gui.new.json
```

to Linux, then:

```bash
python tools/gui2cli.py gui.new.json \
  "$(maa dir config)/tasks/profile_a.json"
```

The converter uses positional arguments:

```text
gui2cli.py INPUT OUTPUT
```

## 7. Service management

```bash
systemctl --user status maa-telegram-bot.service
systemctl --user restart maa-telegram-bot.service

systemctl --user status maa-profile_a.service
systemctl --user status maa-profile_b.service

systemctl --user list-timers 'maa-*.timer' --all
```

Bot daemon output:

```bash
journalctl --user \
  -u maa-telegram-bot.service \
  -n 100 --no-pager
```

## 8. Uninstall systemd setup

```bash
./uninstall.sh
```

This removes only the systemd units managed by this project. It deliberately
preserves your YAML configuration, maa-cli configuration/tasks/profiles, and
project files.
