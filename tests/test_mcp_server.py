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

    def test_compare_production_reports_match(self):
        server = load_server()

        with patch.object(server, "run_ssh") as run_ssh:
            run_ssh.return_value = server.LOCAL_SCRIPT.read_text(encoding="utf-8")
            result = server.compare_production_script()

        self.assertEqual(result["matches"], True)
        self.assertEqual(result["diff"], "")
        self.assertEqual(run_ssh.call_args.args[0], f"cat {server.REMOTE_SCRIPT}")

    def test_upload_candidate_streams_local_script_to_tmp(self):
        server = load_server()

        with patch.object(server, "run_ssh") as run_ssh:
            run_ssh.return_value = "OK"
            result = server.upload_candidate_script()

        self.assertEqual(result, "OK")
        self.assertIn("cat > /tmp/mikrocataTZSP0.py.codex-candidate", run_ssh.call_args.args[0])
        self.assertEqual(run_ssh.call_args.kwargs["stdin"], server.LOCAL_SCRIPT.read_text(encoding="utf-8"))

    def test_deploy_candidate_requires_confirmation(self):
        server = load_server()

        with patch.object(server, "run_ssh") as run_ssh:
            output = server.deploy_candidate_script()

        self.assertIn("confirm=True", output)
        run_ssh.assert_not_called()

    def test_deploy_candidate_backs_up_installs_and_verifies(self):
        server = load_server()

        with patch.object(server, "run_ssh") as run_ssh:
            run_ssh.return_value = "deployed"
            output = server.deploy_candidate_script(confirm=True)

        self.assertEqual(output, "deployed")
        command = run_ssh.call_args.args[0]
        self.assertIn("sudo -n cp /usr/local/bin/mikrocataTZSP0.py", command)
        self.assertIn("sudo -n install -o root -g root -m 755", command)
        self.assertIn("compile(open(", command)

    def test_upload_unit_candidate_streams_local_unit_to_tmp(self):
        server = load_server()

        with patch.object(server, "run_ssh") as run_ssh:
            run_ssh.return_value = "unit-ok"
            result = server.upload_unit_candidate()

        self.assertEqual(result, "unit-ok")
        self.assertIn("cat > /tmp/mikrocataTZSP0-codex.service", run_ssh.call_args.args[0])
        self.assertEqual(run_ssh.call_args.kwargs["stdin"], server.LOCAL_UNIT.read_text(encoding="utf-8"))

    def test_verify_systemd_unit_uses_sudo_systemd_analyze(self):
        server = load_server()

        with patch.object(server, "run_ssh") as run_ssh:
            server.verify_systemd_unit()

        self.assertEqual(
            run_ssh.call_args.args[0],
            "sudo -n /usr/bin/systemd-analyze verify /etc/systemd/system/mikrocataTZSP0.service",
        )

    def test_daemon_reload_requires_confirmation(self):
        server = load_server()

        with patch.object(server, "run_ssh") as run_ssh:
            output = server.daemon_reload()

        self.assertIn("confirm=True", output)
        run_ssh.assert_not_called()

    def test_deploy_unit_candidate_requires_confirmation(self):
        server = load_server()

        with patch.object(server, "run_ssh") as run_ssh:
            output = server.deploy_unit_candidate()

        self.assertIn("confirm=True", output)
        run_ssh.assert_not_called()

    def test_deploy_unit_candidate_installs_reloads_restarts_and_verifies(self):
        server = load_server()

        with patch.object(server, "run_ssh") as run_ssh:
            run_ssh.return_value = "unit-deployed"
            output = server.deploy_unit_candidate(confirm=True)

        self.assertEqual(output, "unit-deployed")
        command = run_ssh.call_args.args[0]
        self.assertIn("sudo -n /usr/bin/install -o root -g root -m 644", command)
        self.assertIn("sudo -n /usr/bin/systemctl daemon-reload", command)
        self.assertIn("sudo -n /usr/bin/systemctl restart mikrocataTZSP0.service", command)
        self.assertIn("sudo -n /usr/bin/systemd-analyze verify", command)
