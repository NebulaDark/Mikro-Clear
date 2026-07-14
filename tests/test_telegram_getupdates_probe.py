import importlib.util
import json
from contextlib import contextmanager
from importlib.machinery import SourceFileLoader
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch


PROBE_PATH = (
    Path(__file__).resolve().parents[1]
    / "deploy"
    / "bin"
    / "mikroclear-telegram-getupdates-probe"
)


def load_probe():
    loader = SourceFileLoader("mikroclear_telegram_probe", str(PROBE_PATH))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class TelegramGetUpdatesProbeTests(TestCase):
    def test_service_start_inhibitor_masks_and_unmasks_runtime_unit(self):
        probe = load_probe()
        calls = []

        def run(command, **kwargs):
            calls.append(command)
            return SimpleNamespace(returncode=0, stdout="enabled\n", stderr="")

        with TemporaryDirectory() as tmp:
            marker = Path(tmp) / "mask-owned"
            with (
                patch.object(probe, "MASK_MARKER", marker),
                patch.object(
                    probe,
                    "current_runtime_mask_identity",
                    return_value="helper-mask",
                ),
                patch.object(probe.subprocess, "run", side_effect=run),
            ):
                with self.assertRaisesRegex(RuntimeError, "body failed"):
                    with probe.inhibit_service_start():
                        raise RuntimeError("body failed")

        self.assertEqual(
            calls,
            [
                [
                    "/usr/bin/systemctl",
                    "is-enabled",
                    "mikroclear.service",
                ],
                [
                    "/usr/bin/systemctl",
                    "mask",
                    "--runtime",
                    "mikroclear.service",
                ],
                [
                    "/usr/bin/systemctl",
                    "unmask",
                    "--runtime",
                    "mikroclear.service",
                ],
            ],
        )

    def test_service_start_inhibitor_preserves_preexisting_runtime_mask(self):
        probe = load_probe()
        run = Mock(
            return_value=SimpleNamespace(
                returncode=1,
                stdout="masked-runtime\n",
                stderr="",
            )
        )

        with TemporaryDirectory() as tmp:
            marker = Path(tmp) / "mask-owned"
            with (
                patch.object(probe, "MASK_MARKER", marker),
                patch.object(probe.subprocess, "run", run),
            ):
                with probe.inhibit_service_start():
                    pass

        run.assert_called_once_with(
            ["/usr/bin/systemctl", "is-enabled", "mikroclear.service"],
            text=True,
            capture_output=True,
            check=False,
        )

    def test_service_start_inhibitor_rejects_concurrent_reset(self):
        probe = load_probe()

        with TemporaryDirectory() as tmp:
            marker = Path(tmp) / "mask-owned"
            with (
                patch.object(probe, "MASK_MARKER", marker),
                patch.object(
                    probe.fcntl,
                    "flock",
                    side_effect=BlockingIOError("locked"),
                ),
                patch.object(probe.subprocess, "run") as run,
            ):
                with self.assertRaisesRegex(RuntimeError, "already in progress"):
                    with probe.inhibit_service_start():
                        pass

        run.assert_not_called()

    def test_service_start_inhibitor_does_not_remove_mismatched_stale_marker(self):
        probe = load_probe()
        run = Mock(
            return_value=SimpleNamespace(
                returncode=1,
                stdout="masked-runtime\n",
                stderr="",
            )
        )

        with TemporaryDirectory() as tmp:
            marker = Path(tmp) / "mask-owned"
            marker.write_text('{"mask_identity": "old-mask"}', encoding="utf-8")
            with (
                patch.object(probe, "MASK_MARKER", marker),
                patch.object(
                    probe,
                    "current_runtime_mask_identity",
                    return_value="operator-mask",
                ),
                patch.object(probe.subprocess, "run", run),
            ):
                with probe.inhibit_service_start():
                    pass

        run.assert_called_once()

    def test_service_start_inhibitor_leaves_recovery_for_failed_cleanup(self):
        probe = load_probe()
        responses = [
            SimpleNamespace(returncode=0, stdout="enabled\n", stderr=""),
            SimpleNamespace(returncode=0, stdout="", stderr=""),
            SimpleNamespace(returncode=1, stdout="", stderr="busy"),
            SimpleNamespace(returncode=1, stdout="", stderr="busy"),
            SimpleNamespace(returncode=1, stdout="", stderr="busy"),
        ]

        with TemporaryDirectory() as tmp:
            marker = Path(tmp) / "mask-owned"
            with (
                patch.object(probe, "MASK_MARKER", marker),
                patch.object(
                    probe,
                    "current_runtime_mask_identity",
                    return_value="helper-mask",
                ),
                patch.object(probe.subprocess, "run", side_effect=responses),
                patch.object(probe, "sleep") as sleep,
            ):
                with self.assertRaisesRegex(
                    RuntimeError,
                    "systemctl unmask --runtime mikroclear.service",
                ):
                    with probe.inhibit_service_start():
                        pass
                self.assertTrue(marker.exists())

        self.assertEqual(sleep.call_count, 2)

    def test_service_start_inhibitor_cleans_partial_mask_after_interrupt(self):
        probe = load_probe()
        calls = []
        responses = iter(
            [
                SimpleNamespace(returncode=0, stdout="enabled\n", stderr=""),
                InterruptedError("signal during mask"),
                SimpleNamespace(
                    returncode=1,
                    stdout="masked-runtime\n",
                    stderr="",
                ),
                SimpleNamespace(returncode=0, stdout="", stderr=""),
            ]
        )

        def run(command, **kwargs):
            calls.append(command)
            result = next(responses)
            if isinstance(result, BaseException):
                raise result
            return result

        with TemporaryDirectory() as tmp:
            marker = Path(tmp) / "mask-owned"
            with (
                patch.object(probe, "MASK_MARKER", marker),
                patch.object(probe.subprocess, "run", side_effect=run),
                patch.object(probe.signal, "pthread_sigmask", return_value=set()),
            ):
                with self.assertRaisesRegex(InterruptedError, "signal during mask"):
                    with probe.inhibit_service_start():
                        pass

        self.assertEqual(
            calls,
            [
                ["/usr/bin/systemctl", "is-enabled", "mikroclear.service"],
                ["/usr/bin/systemctl", "mask", "--runtime", "mikroclear.service"],
                ["/usr/bin/systemctl", "is-enabled", "mikroclear.service"],
                ["/usr/bin/systemctl", "unmask", "--runtime", "mikroclear.service"],
            ],
        )

    def test_service_state_check_fails_closed_on_systemctl_error(self):
        probe = load_probe()

        with patch.object(
            probe.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=1),
        ):
            with self.assertRaisesRegex(RuntimeError, "cannot verify"):
                probe.is_service_active()

    def test_read_only_probe_never_calls_get_updates_or_exposes_token(self):
        probe = load_probe()
        calls = []

        def request(method, token, params=None):
            calls.append((method, token, params))
            if method == "getMe":
                return {"ok": True, "result": {"id": 7, "username": "mikroclear_bot"}}
            return {
                "ok": True,
                "result": {
                    "url": "",
                    "pending_update_count": 0,
                    "allowed_updates": ["message", "callback_query"],
                },
            }

        result = probe.run_probe(
            ["probe"],
            env={"MIKROCLEAR_TELEGRAM_TOKEN": "token-a"},
            runtime_token="token-a",
            request=request,
            service_active=lambda: True,
        )

        self.assertEqual([call[0] for call in calls], ["getMe", "getWebhookInfo"])
        self.assertNotIn("getUpdates", [call[0] for call in calls])
        self.assertNotIn("token-a", json.dumps(result))
        self.assertTrue(result["tokens_match"])

    def test_read_only_probe_does_not_expose_webhook_url(self):
        probe = load_probe()
        webhook_url = "https://example.invalid/token-a/private-hook"

        def request(method, token, params=None):
            if method == "getMe":
                return {"ok": True, "result": {"id": 7, "username": "bot"}}
            return {
                "ok": True,
                "result": {
                    "url": webhook_url,
                    "pending_update_count": 0,
                    "allowed_updates": ["message"],
                },
            }

        result = probe.run_probe(
            ["probe"],
            env={"MIKROCLEAR_TELEGRAM_TOKEN": "token-a"},
            runtime_token="token-a",
            request=request,
            service_active=lambda: True,
        )

        serialized = json.dumps(result)
        self.assertNotIn(webhook_url, serialized)
        self.assertNotIn("private-hook", serialized)
        self.assertTrue(result["identities"]["config"]["webhook"]["url_configured"])

    def test_reset_refuses_while_service_is_active(self):
        probe = load_probe()

        with self.assertRaisesRegex(RuntimeError, "must be stopped"):
            probe.run_probe(
                ["probe", "--reset-allowed-updates"],
                env={"MIKROCLEAR_TELEGRAM_TOKEN": "token-a"},
                runtime_token="token-a",
                request=lambda method, token, params=None: {},
                service_active=lambda: True,
            )

    def test_reset_holds_service_inhibitor_for_all_api_calls(self):
        probe = load_probe()
        inhibited = []

        @contextmanager
        def inhibitor():
            inhibited.append(True)
            try:
                yield
            finally:
                inhibited.pop()

        def request(method, token, params=None):
            self.assertEqual(inhibited, [True])
            if method == "getUpdates":
                return {"ok": True, "result": []}
            return {
                "ok": True,
                "result": {
                    "url": "",
                    "pending_update_count": 0,
                    "allowed_updates": (
                        ["message", "callback_query"]
                        if method == "getWebhookInfo" and request.calls > 1
                        else ["callback_query"]
                    ),
                },
            }

        request.calls = 0

        def counted_request(method, token, params=None):
            request.calls += 1
            return request(method, token, params)

        probe.run_probe(
            ["probe", "--reset-allowed-updates"],
            env={"MIKROCLEAR_TELEGRAM_TOKEN": "token-a"},
            runtime_token=None,
            request=counted_request,
            service_active=lambda: False,
            service_inhibitor=inhibitor,
        )

        self.assertEqual(inhibited, [])

    def test_reset_rechecks_service_state_immediately_before_get_updates(self):
        probe = load_probe()
        states = iter([False, True])
        calls = []

        def request(method, token, params=None):
            calls.append(method)
            return {
                "ok": True,
                "result": {
                    "url": "",
                    "pending_update_count": 0,
                    "allowed_updates": ["callback_query"],
                },
            }

        with self.assertRaisesRegex(RuntimeError, "must remain stopped"):
            probe.run_probe(
                ["probe", "--reset-allowed-updates"],
                env={"MIKROCLEAR_TELEGRAM_TOKEN": "token-a"},
                runtime_token=None,
                request=request,
                service_active=lambda: next(states),
            )

        self.assertEqual(calls, ["getWebhookInfo"])

    def test_reset_rejects_failed_get_updates_response(self):
        probe = load_probe()

        def request(method, token, params=None):
            if method == "getUpdates":
                return {"ok": False, "description": "Conflict"}
            return {
                "ok": True,
                "result": {
                    "url": "",
                    "pending_update_count": 0,
                    "allowed_updates": ["callback_query"],
                },
            }

        with self.assertRaisesRegex(RuntimeError, "getUpdates failed"):
            probe.run_probe(
                ["probe", "--reset-allowed-updates"],
                env={"MIKROCLEAR_TELEGRAM_TOKEN": "token-a"},
                runtime_token=None,
                request=request,
                service_active=lambda: False,
            )

    def test_reset_rejects_unchanged_post_state(self):
        probe = load_probe()

        def request(method, token, params=None):
            if method == "getUpdates":
                return {"ok": True, "result": []}
            return {
                "ok": True,
                "result": {
                    "url": "",
                    "pending_update_count": 0,
                    "allowed_updates": ["callback_query"],
                },
            }

        with self.assertRaisesRegex(RuntimeError, "did not establish"):
            probe.run_probe(
                ["probe", "--reset-allowed-updates"],
                env={"MIKROCLEAR_TELEGRAM_TOKEN": "token-a"},
                runtime_token=None,
                request=request,
                service_active=lambda: False,
            )

    def test_reset_records_post_state_without_update_payload(self):
        probe = load_probe()
        calls = []

        def request(method, token, params=None):
            calls.append((method, params))
            if method == "getUpdates":
                return {
                    "ok": True,
                    "result": [
                        {
                            "update_id": 100,
                            "message": {
                                "text": "/status secret payload",
                                "chat": {"id": 42},
                            },
                        }
                    ],
                }
            allowed_updates = (
                ["callback_query"]
                if len([call for call in calls if call[0] == "getWebhookInfo"]) == 1
                else ["message", "callback_query"]
            )
            return {
                "ok": True,
                "result": {
                    "url": "",
                    "pending_update_count": 0,
                    "allowed_updates": allowed_updates,
                },
            }

        result = probe.run_probe(
            ["probe", "--reset-allowed-updates"],
            env={"MIKROCLEAR_TELEGRAM_TOKEN": "token-a"},
            runtime_token=None,
            request=request,
            service_active=lambda: False,
        )

        self.assertEqual(
            [call[0] for call in calls],
            ["getWebhookInfo", "getUpdates", "getWebhookInfo"],
        )
        self.assertEqual(result["webhook_before"]["allowed_updates"], ["callback_query"])
        self.assertEqual(
            result["webhook_after"]["allowed_updates"],
            ["message", "callback_query"],
        )
        self.assertEqual(
            result["updates"],
            {
                "ok": True,
                "count": 1,
                "updates": [{"update_id": 100, "type": "message"}],
            },
        )
        self.assertNotIn("secret payload", json.dumps(result))

    def test_fingerprints_distinguish_config_and_runtime_tokens(self):
        probe = load_probe()

        def request(method, token, params=None):
            if method == "getMe":
                return {"ok": True, "result": {"id": len(token), "username": "bot"}}
            return {"ok": True, "result": {"url": "", "pending_update_count": 0}}

        result = probe.run_probe(
            ["probe"],
            env={"MIKROCLEAR_TELEGRAM_TOKEN": "config-token"},
            runtime_token="runtime-token",
            request=request,
            service_active=lambda: True,
        )

        self.assertFalse(result["tokens_match"])
        self.assertNotEqual(
            result["config_token_fingerprint"],
            result["runtime_token_fingerprint"],
        )
        serialized = json.dumps(result)
        self.assertNotIn("config-token", serialized)
        self.assertNotIn("runtime-token", serialized)
