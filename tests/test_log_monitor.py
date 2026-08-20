from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

import log_monitor
from telegram_ui import split_text


class TaskResultChunkingTests(TestCase):
    def test_chunks_only_between_task_results(self):
        results = ["task-one", "task-two", "task-three"]

        chunks = log_monitor.chunk_task_results(results, max_chars=17, )

        self.assertEqual(chunks, ["task-one\ntask-two", "task-three"])
        self.assertEqual([line for chunk in chunks for line in chunk.splitlines()], results)

    def test_oversized_error_logs_split_on_lines(self):
        text = "[9] Fight Error\n\nfirst detail\nsecond detail\nthird detail"

        chunks = split_text(text, max_chars=24, )

        for line in ("[9] Fight Error", "first detail", "second detail", "third detail"):
            self.assertTrue(any(line in chunk.splitlines() for chunk in chunks))

    def test_single_oversized_log_line_is_hard_wrapped(self):
        chunks = split_text("[9] Fight Error\n" + ("x" * 31), max_chars=15, )

        self.assertEqual(chunks, ["[9] Fight Error", "x" * 15, "x" * 15, "x"])


class FullSessionReportingTests(IsolatedAsyncioTestCase):
    pid = 101
    name = "profile_a"

    def setUp(self):
        self.application = object()
        self.profile = SimpleNamespace(log="FULL", lang="en", chat_id=123)
        self.session_results: dict[int, list[str]] = {}

    async def report(self, taskchain: str, taskid: int, event: str, failure_lines: list[str] | None = None):
        task = log_monitor.ActiveTask(taskchain=taskchain, taskid=taskid, failure_lines=(failure_lines or []), )

        await log_monitor.report_finished_task(
            self.application,
            self.name,
            self.pid,
            task,
            event,
            self.session_results,
        )

    async def test_completed_tasks_flush_together_when_worker_exits(self):
        with (
                patch.object(log_monitor, "get_profile", return_value=self.profile),
                patch.object(log_monitor, "send_profile_preformatted", new_callable=AsyncMock) as send,
        ):
            await self.report("StartUp", 1, "TaskChainCompleted")
            await self.report("Fight", 2, "TaskChainCompleted")

            send.assert_not_awaited()

            pid_to_profile = {self.pid: self.name}
            await log_monitor.prune_stale_pids(
                self.application,
                pid_to_profile,
                {},
                self.session_results,
                set(),
            )

        send.assert_awaited_once()
        self.assertEqual(send.await_args.kwargs["text"], "[1] StartUp Completed\n[2] Fight Completed")
        self.assertNotIn(self.pid, pid_to_profile)
        self.assertNotIn(self.pid, self.session_results)

    async def test_stopped_task_flushes_with_prior_tasks(self):
        with (
                patch.object(log_monitor, "get_profile", return_value=self.profile),
                patch.object(log_monitor, "send_profile_preformatted", new_callable=AsyncMock) as send,
        ):
            await self.report("StartUp", 1, "TaskChainCompleted")
            await self.report("Fight", 2, "TaskChainStopped")

        send.assert_awaited_once()
        self.assertEqual(send.await_args.kwargs["text"], "[1] StartUp Completed\n[2] Fight Stopped")
        self.assertNotIn(self.pid, self.session_results)

    async def test_full_summary_continuations_keep_tasks_intact(self):
        first_result = "a" * 2000
        second_result = "b" * 1400

        with (
                patch.object(log_monitor, "get_profile", return_value=self.profile),
                patch.object(log_monitor, "send_profile_preformatted", new_callable=AsyncMock) as send,
        ):
            await log_monitor.send_full_session_results(
                self.application,
                self.name,
                [first_result, second_result],
            )

        self.assertEqual(send.await_count, 2)
        self.assertEqual(send.await_args_list[0].kwargs["text"], first_result)
        self.assertEqual(send.await_args_list[1].kwargs["text"], second_result)
        self.assertEqual(send.await_args_list[1].kwargs["title"], "📜 profile_a full run log (continued)")

    async def test_error_sends_prior_tasks_then_separate_failure(self):
        with (
                patch.object(log_monitor, "get_profile", return_value=self.profile),
                patch.object(log_monitor, "send_profile_preformatted", new_callable=AsyncMock) as send,
        ):
            await self.report("StartUp", 1, "TaskChainCompleted")
            await self.report("Fight", 2, "TaskChainError", ["SubTaskError details", "ADB failed"], )

        self.assertEqual(send.await_count, 2)
        summary_call, error_call = send.await_args_list
        self.assertEqual(summary_call.kwargs["text"], "[1] StartUp Completed")
        self.assertEqual(summary_call.kwargs["title"], "📜 profile_a full run log")
        self.assertEqual(error_call.kwargs["text"], "[2] Fight Error\n\nSubTaskError details\nADB failed")
        self.assertEqual(error_call.kwargs["title"], "⚠️ profile_a incomplete task log")
        self.assertNotIn(self.pid, self.session_results)

    async def test_error_without_prior_tasks_sends_only_failure(self):
        with (
                patch.object(log_monitor, "get_profile", return_value=self.profile),
                patch.object(log_monitor, "send_profile_preformatted", new_callable=AsyncMock) as send,
        ):
            await self.report("Fight", 2, "TaskChainError", ["ADB failed"], )

        send.assert_awaited_once()
        self.assertEqual(send.await_args.kwargs["text"], "[2] Fight Error\n\nADB failed")

    async def test_new_batch_starts_after_stopped_flush(self):
        with (
                patch.object(log_monitor, "get_profile", return_value=self.profile),
                patch.object(log_monitor, "send_profile_preformatted", new_callable=AsyncMock) as send,
        ):
            await self.report("StartUp", 1, "TaskChainStopped")
            await self.report("Fight", 2, "TaskChainCompleted")

            await log_monitor.prune_stale_pids(
                self.application,
                {self.pid: self.name},
                {},
                self.session_results,
                set(),
            )

        self.assertEqual(send.await_count, 2)
        self.assertEqual(send.await_args_list[0].kwargs["text"], "[1] StartUp Stopped")
        self.assertEqual(send.await_args_list[1].kwargs["text"], "[2] Fight Completed")

    async def test_on_completed_and_stopped_clear_silently(self):
        self.profile.log = "ON"

        with (
                patch.object(log_monitor, "get_profile", return_value=self.profile),
                patch.object(log_monitor, "send_profile_preformatted", new_callable=AsyncMock) as send,
        ):
            self.session_results[self.pid] = ["[1] StartUp Completed"]
            await self.report("Fight", 2, "TaskChainCompleted")

            send.assert_not_awaited()
            self.assertNotIn(self.pid, self.session_results)

            self.session_results[self.pid] = ["[2] Fight Completed"]
            await self.report("Mall", 3, "TaskChainStopped")

            send.assert_not_awaited()
            self.assertNotIn(self.pid, self.session_results)

    async def test_on_error_sends_only_failure(self):
        self.profile.log = "ON"
        self.session_results[self.pid] = ["[1] StartUp Completed"]

        with (
                patch.object(log_monitor, "get_profile", return_value=self.profile),
                patch.object(log_monitor, "send_profile_preformatted", new_callable=AsyncMock) as send,
        ):
            await self.report("Recruit", 4, "TaskChainError", ["OCR failed"], )

        send.assert_awaited_once()
        self.assertEqual(send.await_args.kwargs["text"], "[4] Recruit Error\n\nOCR failed")
        self.assertNotIn(self.pid, self.session_results)

    async def test_off_behavior_is_unchanged(self):
        self.profile.log = "OFF"
        self.session_results[self.pid] = ["[1] StartUp Completed"]

        with (
                patch.object(log_monitor, "get_profile", return_value=self.profile),
                patch.object(log_monitor, "send_profile_preformatted", new_callable=AsyncMock) as send,
        ):
            await self.report("Recruit", 2, "TaskChainError", ["OCR failed"], )

        send.assert_not_awaited()
        self.assertNotIn(self.pid, self.session_results)

    def test_mode_change_discards_pending_full_batch(self):
        self.profile.log = "OFF"
        self.session_results[self.pid] = ["[1] StartUp Completed"]

        with patch.object(log_monitor, "get_profile", return_value=self.profile):
            log_monitor.discard_inactive_session_results({self.pid: self.name}, self.session_results, )

        self.assertNotIn(self.pid, self.session_results)
