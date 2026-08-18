from __future__ import annotations

import asyncio
import re

from telegram.ext import Application

from i18n import text_for
from maa_config import (
    AUTHORIZED_BY_NAME,
    service_unit_for,
)
from profile_store import (
    get_profile,
)
from systemd_utils import (
    invocation_log,
    systemctl_value,
    unit_is_active,
)
from telegram_ui import (
    send_profile_preformatted,
)

ANSI_RE = re.compile(
    r"\x1b\[[0-?]*[ -/]*[@-~]"
)

SUBTASK_SUMMARY_RE = re.compile(
    r"^\[(?P<task>[^\]]+)\]\s+"
    r"\d{2}:\d{2}:\d{2}\s+-\s+"
    r"\d{2}:\d{2}:\d{2}\s+"
    r"\([^)]+\)\s+"
    r"(?P<status>.+?)\s*$"
)


def strip_ansi(
    text: str,
) -> str:
    return ANSI_RE.sub(
        "",
        text,
    )


def incomplete_subtask_summaries(
    log_text: str,
) -> list[str]:
    incomplete: list[str] = []

    for raw_line in log_text.splitlines():
        line = strip_ansi(
            raw_line
        ).strip()

        match = SUBTASK_SUMMARY_RE.match(
            line
        )

        if not match:
            continue

        status = match.group(
            "status"
        ).strip()

        if status.casefold() != "completed":
            incomplete.append(
                line
            )

    return incomplete


async def process_finished_invocation(
    application: Application,
    name: str,
    invocation_id: str,
) -> None:
    profile = get_profile(name)
    mode = profile.log
    lang = profile.lang

    if mode == "OFF":
        return

    await asyncio.sleep(
        0.75
    )

    log_text = await invocation_log(
        invocation_id
    )

    if mode == "FULL":
        await send_profile_preformatted(
            application,
            name=name,
            title=text_for(
                lang,
                "full_log_title",
                name=name,
            ),
            text=log_text,
        )
        return

    incomplete = (
        incomplete_subtask_summaries(
            log_text
        )
    )

    if not incomplete:
        return

    await send_profile_preformatted(
        application,
        name=name,
        title=text_for(
            lang,
            "incomplete_log_title",
            name=name,
        ),
        text="\n".join(incomplete),
    )


async def log_monitor_loop(
    application: Application,
) -> None:
    active_invocations: dict[
        str,
        str,
    ] = {}

    try:
        while True:
            for name in AUTHORIZED_BY_NAME:
                unit = service_unit_for(
                    name
                )

                try:
                    active = await unit_is_active(
                        unit
                    )

                    if active:
                        invocation_id = await systemctl_value(
                            unit,
                            "InvocationID",
                        )

                        if invocation_id:
                            active_invocations[
                                name
                            ] = invocation_id

                        continue

                    invocation_id = (
                        active_invocations.pop(
                            name,
                            None,
                        )
                    )

                    if invocation_id:
                        try:
                            await process_finished_invocation(
                                application,
                                name,
                                invocation_id,
                            )
                        except Exception:
                            pass

                except Exception:
                    continue

            await asyncio.sleep(
                1
            )

    except asyncio.CancelledError:
        return
