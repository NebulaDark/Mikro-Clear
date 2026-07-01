import importlib.util
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch


SERVER_PATH = Path(__file__).resolve().parents[1] / "services" / "mcp-server" / "server.py"


def load_server():
    spec = importlib.util.spec_from_file_location("mikroclear_mcp_server", SERVER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class McpServerSshTests(TestCase):
    def test_run_ssh_uses_configured_ssh_command(self):
        server = load_server()

        with patch.object(server.subprocess, "run") as run:
            run.return_value.stdout = "ok\n"
            run.return_value.stderr = ""
            run.return_value.returncode = 0

            output = server.run_ssh("systemctl is-active mikrocataTZSP0.service", 20)

        self.assertEqual(output, "ok")
        self.assertEqual(
            run.call_args.args[0],
            [
                "ssh",
                "-F",
                "/home/mgm/.ssh/config",
                "-o",
                "StrictHostKeyChecking=accept-new",
                "selks",
                "systemctl is-active mikrocataTZSP0.service",
            ],
        )
        self.assertEqual(run.call_args.kwargs["timeout"], 20)

    def test_restart_requires_explicit_confirmation(self):
        server = load_server()

        with patch.object(server, "run_ssh") as run_ssh:
            output = server.restart_mikrocata()

        self.assertIn("confirm=True", output)
        run_ssh.assert_not_called()

    def test_syntax_check_does_not_write_pycache(self):
        server = load_server()

        with patch.object(server, "run_ssh") as run_ssh:
            server.check_mikrocata_syntax()

        self.assertIn("compile(open(", run_ssh.call_args.args[0])
        self.assertNotIn("py_compile", run_ssh.call_args.args[0])
