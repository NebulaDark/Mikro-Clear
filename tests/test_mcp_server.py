import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
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

            output = server.run_ssh("systemctl is-active mikroclear.service", 20)

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
                "systemctl is-active mikroclear.service",
            ],
        )
        self.assertEqual(run.call_args.kwargs["timeout"], 20)

    def test_restart_requires_explicit_confirmation(self):
        server = load_server()

        with patch.object(server, "run_ssh") as run_ssh:
            output = server.restart_mikroclear()

        self.assertIn("confirm=True", output)
        run_ssh.assert_not_called()

    def test_start_requires_explicit_confirmation(self):
        server = load_server()

        with patch.object(server, "run_ssh") as run_ssh:
            output = server.start_mikroclear()

        self.assertIn("confirm=True", output)
        run_ssh.assert_not_called()

    def test_stop_requires_explicit_confirmation(self):
        server = load_server()

        with patch.object(server, "run_ssh") as run_ssh:
            output = server.stop_mikroclear()

        self.assertIn("confirm=True", output)
        run_ssh.assert_not_called()

    def test_syntax_check_is_package_import_compatibility_alias(self):
        server = load_server()

        with patch.object(server, "check_mikroclear_import") as check_import:
            check_import.return_value = "import-ok"
            output = server.check_mikroclear_syntax()

        self.assertEqual(output, "import-ok")
        check_import.assert_called_once_with()

    def test_import_check_uses_package_entrypoint_without_runtime_loop(self):
        server = load_server()

        with patch.object(server, "run_ssh") as run_ssh:
            server.check_mikroclear_import()

        command = run_ssh.call_args.args[0]
        self.assertIn("import mikroclear.app as app", command)
        self.assertIn("app.build_service()", command)
        self.assertNotIn("app.main()", command)
        self.assertNotIn("compile(open(", command)

    def test_upload_wheel_candidate_streams_b64_wheel_to_private_staging_dir(self):
        server = load_server()

        with TemporaryDirectory() as tmpdir:
            wheel_path = Path(tmpdir) / "mikro_clear-0.1.0-py3-none-any.whl"
            wheel_path.write_bytes(b"fake-wheel")

            with patch.object(server, "LOCAL_WHEEL", wheel_path), patch.object(server, "run_ssh") as run_ssh:
                run_ssh.return_value = "wheel-uploaded"
                result = server.upload_wheel_candidate()

        self.assertEqual(result, "wheel-uploaded")
        self.assertEqual(server.CANDIDATE_WHEEL, "/var/tmp/mikroclear-deploy/mikro_clear-0.1.0-py3-none-any.whl")
        command = run_ssh.call_args.args[0]
        self.assertIn("/usr/bin/install -d -m 700 /var/tmp/mikroclear-deploy", command)
        self.assertIn("base64 -d", command)
        self.assertIn("chmod 600 /var/tmp/mikroclear-deploy/mikro_clear-0.1.0-py3-none-any.whl", command)
        self.assertIn("sha256sum /var/tmp/mikroclear-deploy/mikro_clear-0.1.0-py3-none-any.whl", command)
        self.assertIsInstance(run_ssh.call_args.kwargs["stdin"], str)

    def test_deploy_wheel_candidate_requires_confirmation(self):
        server = load_server()

        with patch.object(server, "run_ssh") as run_ssh:
            output = server.deploy_wheel_candidate()

        self.assertIn("confirm=True", output)
        run_ssh.assert_not_called()

    def test_deploy_wheel_candidate_installs_package_restarts_and_verifies(self):
        server = load_server()

        with patch.object(server, "run_ssh") as run_ssh:
            run_ssh.return_value = "wheel-deployed"
            output = server.deploy_wheel_candidate(confirm=True)

        self.assertEqual(output, "wheel-deployed")
        command = run_ssh.call_args.args[0]
        self.assertIn("sudo -n /opt/mikroclear-venv/bin/python -m pip install --no-deps --force-reinstall", command)
        self.assertIn("/var/tmp/mikroclear-deploy/mikro_clear-0.1.0-py3-none-any.whl", command)
        self.assertIn("import mikroclear.app as app", command)
        self.assertIn("sudo -n /usr/bin/systemctl restart mikroclear.service", command)
        self.assertIn("systemctl show mikroclear.service --property=ActiveState,SubState,ExecStart,NRestarts --no-pager", command)

    def test_compare_production_reports_match(self):
        server = load_server()

        with patch.object(server, "run_ssh") as run_ssh:
            run_ssh.return_value = server.LOCAL_SCRIPT.read_text(encoding="utf-8")
            result = server.compare_production_script()

        self.assertEqual(result["matches"], True)
        self.assertEqual(result["diff"], "")
        self.assertEqual(run_ssh.call_args.args[0], f"cat {server.REMOTE_SCRIPT}")

    def test_upload_candidate_streams_local_script_to_private_staging_dir(self):
        server = load_server()

        with patch.object(server, "run_ssh") as run_ssh:
            run_ssh.return_value = "OK"
            result = server.upload_candidate_script()

        self.assertEqual(result, "OK")
        self.assertEqual(server.CANDIDATE_DIR, "/var/tmp/mikroclear-deploy")
        self.assertEqual(server.CANDIDATE_SCRIPT, "/var/tmp/mikroclear-deploy/mikroclear.py.codex-candidate")
        self.assertIn("/usr/bin/install -d -m 700 /var/tmp/mikroclear-deploy", run_ssh.call_args.args[0])
        self.assertIn("cat > /var/tmp/mikroclear-deploy/mikroclear.py.codex-candidate", run_ssh.call_args.args[0])
        self.assertIn("chmod 600 /var/tmp/mikroclear-deploy/mikroclear.py.codex-candidate", run_ssh.call_args.args[0])
        self.assertNotIn("cat > /tmp/", run_ssh.call_args.args[0])
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
        self.assertIn("if [ -f /usr/local/bin/mikroclear.py ]; then", command)
        self.assertIn("sudo -n cp /usr/local/bin/mikroclear.py", command)
        self.assertIn("elif [ -f /usr/local/bin/mikrocataTZSP0.py ]; then", command)
        self.assertIn("sudo -n cp /usr/local/bin/mikrocataTZSP0.py", command)
        self.assertIn("sudo -n install -o root -g root -m 755", command)
        self.assertIn("compile(open(", command)

    def test_upload_unit_candidate_streams_local_unit_to_private_staging_dir(self):
        server = load_server()

        with patch.object(server, "run_ssh") as run_ssh:
            run_ssh.return_value = "unit-ok"
            result = server.upload_unit_candidate()

        self.assertEqual(result, "unit-ok")
        self.assertEqual(server.CANDIDATE_UNIT, "/var/tmp/mikroclear-deploy/mikroclear-codex.service")
        self.assertIn("/usr/bin/install -d -m 700 /var/tmp/mikroclear-deploy", run_ssh.call_args.args[0])
        self.assertIn("cat > /var/tmp/mikroclear-deploy/mikroclear-codex.service", run_ssh.call_args.args[0])
        self.assertIn("chmod 600 /var/tmp/mikroclear-deploy/mikroclear-codex.service", run_ssh.call_args.args[0])
        self.assertNotIn("cat > /tmp/", run_ssh.call_args.args[0])
        self.assertEqual(run_ssh.call_args.kwargs["stdin"], server.LOCAL_UNIT.read_text(encoding="utf-8"))

    def test_log_tail_uses_fixed_sudoers_sizes(self):
        server = load_server()

        with patch.object(server, "run_ssh") as run_ssh:
            server.tail_mikroclear_logs(42)
            command_100 = run_ssh.call_args.args[0]
            server.tail_mikroclear_logs(250)
            command_300 = run_ssh.call_args.args[0]
            server.tail_mikroclear_logs(999)
            command_500 = run_ssh.call_args.args[0]

        self.assertEqual(command_100, "sudo -n journalctl -u mikroclear.service -n 100 --no-pager")
        self.assertEqual(command_300, "sudo -n journalctl -u mikroclear.service -n 300 --no-pager")
        self.assertEqual(command_500, "sudo -n journalctl -u mikroclear.service -n 500 --no-pager")

    def test_suricata_tail_uses_fixed_sudoers_sizes(self):
        server = load_server()

        with patch.object(server, "run_ssh") as run_ssh:
            server.tail_suricata_eve(7)
            command_20 = run_ssh.call_args.args[0]
            server.tail_suricata_eve(40)
            command_50 = run_ssh.call_args.args[0]
            server.tail_suricata_eve(99)
            command_100 = run_ssh.call_args.args[0]

        self.assertIn("sudo -n tail -n 20 ", command_20)
        self.assertIn("sudo -n tail -n 50 ", command_50)
        self.assertIn("sudo -n tail -n 100 ", command_100)

    def test_verify_systemd_unit_uses_sudo_systemd_analyze(self):
        server = load_server()

        with patch.object(server, "run_ssh") as run_ssh:
            server.verify_systemd_unit()

        self.assertEqual(
            run_ssh.call_args.args[0],
            "sudo -n /usr/bin/systemd-analyze verify /etc/systemd/system/mikroclear.service",
        )

    def test_read_mikroclear_env_reads_primary_env_only(self):
        server = load_server()

        with patch.object(server, "run_ssh") as run_ssh:
            run_ssh.return_value = "masked-primary"
            output = server.read_mikroclear_env()

        self.assertEqual(output, "masked-primary")
        self.assertEqual(
            run_ssh.call_args.args[0],
            "sudo -n /usr/local/sbin/mikroclear-mask-env /etc/mikroclear/mikroclear.env",
        )

    def test_read_mikrocata_env_reads_legacy_env_explicitly(self):
        server = load_server()

        with patch.object(server, "run_ssh") as run_ssh:
            run_ssh.return_value = "masked-legacy"
            output = server.read_mikrocata_env()

        self.assertEqual(output, "masked-legacy")
        self.assertEqual(
            run_ssh.call_args.args[0],
            "sudo -n /usr/local/sbin/mikroclear-mask-env /etc/mikrocata/mikrocataTZSP0.env",
        )

    def test_show_mikroclear_startup_reports_runtime_shape(self):
        server = load_server()

        with patch.object(server, "run_ssh") as run_ssh:
            server.show_mikroclear_startup()

        self.assertEqual(
            run_ssh.call_args.args[0],
            "systemctl show mikroclear.service --property=MainPID,ExecStart,EnvironmentFiles,FragmentPath,DropInPaths,ActiveState,SubState --no-pager",
        )

    def test_read_mikroclear_runtime_env_uses_helper(self):
        server = load_server()

        with patch.object(server, "run_ssh") as run_ssh:
            run_ssh.return_value = "runtime-env"
            output = server.read_mikroclear_runtime_env()

        self.assertEqual(output, "runtime-env")
        self.assertEqual(run_ssh.call_args.args[0], "sudo -n /usr/local/sbin/mikroclear-service-env")

    def test_probe_mikroclear_telegram_updates_uses_helper(self):
        server = load_server()

        with patch.object(server, "run_ssh") as run_ssh:
            run_ssh.return_value = "telegram-probe"
            output = server.probe_mikroclear_telegram_updates()

        self.assertEqual(output, "telegram-probe")
        self.assertEqual(run_ssh.call_args.args[0], "sudo -n /usr/local/sbin/mikroclear-telegram-getupdates-probe")

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
        self.assertNotIn("mikrocataTZSP0.service", command)
        self.assertIn("sudo -n /usr/bin/systemctl enable mikroclear.service", command)
        self.assertIn("sudo -n /usr/bin/systemctl restart mikroclear.service", command)
        self.assertIn("sudo -n /usr/bin/systemd-analyze verify", command)

    def test_legacy_tool_names_delegate_to_mikroclear_tools(self):
        server = load_server()

        with patch.object(server, "status_mikroclear") as status:
            status.return_value = "active"
            self.assertEqual(server.status_mikrocata(), "active")

        with patch.object(server, "restart_mikroclear") as restart:
            restart.return_value = "restarted"
            self.assertEqual(server.restart_mikrocata(confirm=True), "restarted")
            restart.assert_called_once_with(True)

        with patch.object(server, "tail_mikroclear_logs") as tail:
            tail.return_value = "logs"
            self.assertEqual(server.tail_mikrocata_logs(50), "logs")
            tail.assert_called_once_with(50)

        with patch.object(server, "check_mikroclear_syntax") as syntax:
            syntax.return_value = "OK"
            self.assertEqual(server.check_mikrocata_syntax(), "OK")

        with patch.object(server, "run_ssh") as run_ssh:
            run_ssh.return_value = "masked-legacy"
            self.assertEqual(server.read_mikrocata_env(), "masked-legacy")
            self.assertIn("/etc/mikrocata/mikrocataTZSP0.env", run_ssh.call_args.args[0])
