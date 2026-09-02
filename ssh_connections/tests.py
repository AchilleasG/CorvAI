from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase

from orchestration.crypto import decrypt_value
from orchestration.function_caller import FunctionCallOrchestrator
from orchestration.tools.ssh_connections import (
    run_command as run_ssh_tool_command,
    set_machine_notes,
)
from ssh_connections.models import SshCommandRecord, SshMachine
from ssh_connections.services import OpenSshSession, OpenTerminalSession, SshConnectionManager, key_fingerprint


TEST_SECRET_KEY = "MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDA="


class FakeStatefulChannel:
    def __init__(self):
        self.closed = False
        self.cwd = "/home/corv"
        self.buffer = b""

    def exit_status_ready(self):
        return False

    def send(self, payload):
        import re

        command = payload.splitlines()[0]
        token = re.search(r"__CORV_DONE_([a-f0-9]+)", payload).group(1)
        output = ""
        if command.startswith("cd "):
            self.cwd = command[3:].strip()
        elif command == "pwd":
            output = self.cwd + "\n"
        self.buffer += f"{output}\n__CORV_DONE_{token}:0:{self.cwd}\n".encode()

    def recv_ready(self):
        return bool(self.buffer)

    def recv(self, size):
        chunk, self.buffer = self.buffer[:size], self.buffer[size:]
        return chunk

    def close(self):
        self.closed = True


class FakeExecChannel:
    def __init__(self, stdout=b"", stderr=b"", exit_status=0, hangs=False):
        self.closed = False
        self.stdout = bytearray(stdout)
        self.stderr = bytearray(stderr)
        self.exit_status = exit_status
        self.hangs = hangs
        self.command = ""

    def exec_command(self, command):
        self.command = command

    def recv_ready(self):
        return bool(self.stdout)

    def recv(self, size):
        chunk, self.stdout = self.stdout[:size], self.stdout[size:]
        return bytes(chunk)

    def recv_stderr_ready(self):
        return bool(self.stderr)

    def recv_stderr(self, size):
        chunk, self.stderr = self.stderr[:size], self.stderr[size:]
        return bytes(chunk)

    def exit_status_ready(self):
        return not self.hangs and not self.stdout and not self.stderr

    def recv_exit_status(self):
        return self.exit_status

    def close(self):
        self.closed = True


class SshMachineTests(SimpleTestCase):
    def test_credentials_are_encrypted_and_not_exposed_as_fields(self):
        machine = SshMachine(
            name="server",
            host="server.example",
            username="corv",
            auth_type=SshMachine.AUTH_PASSWORD,
        )
        with patch("orchestration.crypto.settings.module_secret_key", TEST_SECRET_KEY):
            machine.set_credentials(password="secret-password")
            encrypted = machine.credential_encrypted
            self.assertNotIn("secret-password", encrypted)
            self.assertIn("secret-password", decrypt_value(encrypted, TEST_SECRET_KEY))

    def test_assistant_commands_require_explicit_machine_permission(self):
        machine = SshMachine(
            name="locked-server",
            host="localhost",
            username="corv",
            auth_type=SshMachine.AUTH_AGENT,
            allow_ai_commands=False,
        )
        with self.assertRaises(PermissionError):
            SshConnectionManager.run_command(
                machine,
                "uptime",
                source=SshCommandRecord.SOURCE_ASSISTANT,
            )

    @patch("orchestration.tools.ssh_connections.SshConnectionManager.run_exec_command")
    @patch("orchestration.tools.ssh_connections.SshConnectionManager.get_or_create_named_terminal")
    @patch("orchestration.tools.ssh_connections._machine")
    def test_assistant_sudo_commands_use_isolated_exec_channel(self, get_machine, get_terminal, run_exec):
        machine = MagicMock(allow_ai_commands=True)
        get_machine.return_value = machine
        run_exec.return_value = {"exit_status": 0, "stdout": "0\\n"}

        result = run_ssh_tool_command("Animus Server", "sudo -n id -u", timeout_seconds=10)

        self.assertEqual(result["stdout"], "0\\n")
        run_exec.assert_called_once_with(
            machine,
            "sudo -n id -u",
            source=SshCommandRecord.SOURCE_ASSISTANT,
            timeout_seconds=10,
        )
        get_terminal.assert_not_called()

    def test_sha256_host_key_fingerprint(self):
        key = MagicMock()
        key.asbytes.return_value = b"server-key"
        self.assertTrue(key_fingerprint(key).startswith("SHA256:"))

    @patch("ssh_connections.services.SshCommandRecord.objects.create")
    def test_terminal_session_preserves_working_directory(self, create_record):
        machine = SshMachine(
            id="3d22775c-a980-4add-a94e-12ddbd75777c",
            name="stateful-server",
            host="localhost",
            username="corv",
            auth_type=SshMachine.AUTH_AGENT,
        )
        terminal = OpenTerminalSession(
            id="cbb78989-a09d-481d-92f7-590fd761882b",
            machine_key=str(machine.pk),
            name="work",
            channel=FakeStatefulChannel(),
            created_at=1,
            last_used_at=1,
        )
        SshConnectionManager._terminals[terminal.id] = terminal
        try:
            first = SshConnectionManager.run_terminal_command(machine, terminal.id, "cd /tmp")
            second = SshConnectionManager.run_terminal_command(machine, terminal.id, "pwd")
        finally:
            SshConnectionManager._terminals.pop(terminal.id, None)
        self.assertEqual(first["cwd"], "/tmp")
        self.assertEqual(second["cwd"], "/tmp")
        self.assertIn("/tmp", second["stdout"])
        self.assertEqual(create_record.call_count, 2)

    @patch("ssh_connections.services.SshCommandRecord.objects.create")
    def test_exec_commands_use_separate_channels_on_one_transport(self, create_record):
        machine = SshMachine(
            id="3d22775c-a980-4add-a94e-12ddbd75777c",
            name="persistent-server",
            host="localhost",
            username="corv",
            auth_type=SshMachine.AUTH_AGENT,
            allow_ai_commands=True,
        )
        first_channel = FakeExecChannel(stdout=b"first\n")
        second_channel = FakeExecChannel(stdout=b"second\n")
        transport = MagicMock()
        transport.is_active.return_value = True
        transport.open_session.side_effect = [first_channel, second_channel]
        client = MagicMock()
        client.get_transport.return_value = transport
        key = str(machine.pk)
        SshConnectionManager._sessions[key] = OpenSshSession(client, 1, 1)
        try:
            with patch.object(SshConnectionManager, "is_connected", return_value=True):
                first = SshConnectionManager.run_exec_command(machine, "echo first")
                second = SshConnectionManager.run_exec_command(machine, "echo second")
        finally:
            SshConnectionManager._sessions.pop(key, None)

        self.assertEqual(first["stdout"], "first\n")
        self.assertEqual(second["stdout"], "second\n")
        self.assertEqual(transport.open_session.call_count, 2)
        self.assertTrue(first_channel.closed)
        self.assertTrue(second_channel.closed)
        self.assertEqual(create_record.call_count, 2)

    @patch("ssh_connections.services.SshCommandRecord.objects.create")
    def test_timed_out_exec_channel_does_not_poison_next_command(self, create_record):
        machine = SshMachine(
            id="3d22775c-a980-4add-a94e-12ddbd75777c",
            name="persistent-server",
            host="localhost",
            username="corv",
            auth_type=SshMachine.AUTH_AGENT,
            allow_ai_commands=True,
        )
        hung_channel = FakeExecChannel(hangs=True)
        healthy_channel = FakeExecChannel(stdout=b"recovered\n")
        transport = MagicMock()
        transport.is_active.return_value = True
        transport.open_session.side_effect = [hung_channel, healthy_channel]
        client = MagicMock()
        client.get_transport.return_value = transport
        key = str(machine.pk)
        SshConnectionManager._sessions[key] = OpenSshSession(client, 1, 1)
        try:
            with patch.object(SshConnectionManager, "is_connected", return_value=True):
                with self.assertRaisesRegex(
                    TimeoutError,
                    "SSH command timed out.*persistent-server.*shared SSH connection remains usable",
                ):
                    SshConnectionManager.run_exec_command(
                        machine, "long-running-build", timeout_seconds=0.001
                    )
                result = SshConnectionManager.run_exec_command(machine, "echo recovered")
        finally:
            SshConnectionManager._sessions.pop(key, None)

        self.assertTrue(hung_channel.closed)
        self.assertEqual(result["stdout"], "recovered\n")
        self.assertTrue(healthy_channel.closed)
        self.assertEqual(transport.open_session.call_count, 2)


class DefaultSshMachineTests(TestCase):
    def setUp(self):
        self.first = SshMachine.objects.create(
            name="First",
            host="first.example",
            username="developer",
            auth_type=SshMachine.AUTH_AGENT,
            allow_ai_commands=True,
        )
        self.second = SshMachine.objects.create(
            name="Second",
            host="second.example",
            username="developer",
            auth_type=SshMachine.AUTH_AGENT,
            allow_ai_commands=True,
        )

    def test_api_can_switch_the_single_default_machine(self):
        response = self.client.patch(
            f"/api/ssh/machines/{self.first.pk}",
            data='{"is_default": true}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(response.json()["is_default"])

        response = self.client.patch(
            f"/api/ssh/machines/{self.second.pk}",
            data='{"is_default": true}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.first.refresh_from_db()
        self.second.refresh_from_db()
        self.assertFalse(self.first.is_default)
        self.assertTrue(self.second.is_default)

        listed = self.client.get("/api/ssh/machines").json()["machines"]
        self.assertEqual([item["name"] for item in listed if item["is_default"]], ["Second"])

    def test_disabling_corv_access_clears_default(self):
        self.first.is_default = True
        self.first.save(update_fields=["is_default"])
        response = self.client.patch(
            f"/api/ssh/machines/{self.first.pk}",
            data='{"allow_ai_commands": false}',
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200, response.content)
        self.first.refresh_from_db()
        self.assertFalse(self.first.allow_ai_commands)
        self.assertFalse(self.first.is_default)

    @patch("orchestration.tools.ssh_connections.SshConnectionManager.run_terminal_command")
    @patch("orchestration.tools.ssh_connections.SshConnectionManager.get_or_create_named_terminal")
    def test_command_tool_uses_default_when_machine_is_omitted(self, get_terminal, run_terminal):
        self.second.is_default = True
        self.second.save(update_fields=["is_default"])
        terminal = MagicMock(id="terminal")
        get_terminal.return_value = terminal
        run_terminal.return_value = {"stdout": "42", "exit_status": 0}

        result = run_ssh_tool_command(command="python3 -c 'print(6*7)'")

        self.assertEqual(result["stdout"], "42")
        self.assertEqual(get_terminal.call_args.args[0], self.second)
        run_terminal.assert_called_once()


class MachineNotesContextTests(TestCase):
    def setUp(self):
        self.machine = SshMachine.objects.create(
            name="PDF worker",
            host="pdf.example",
            username="root",
            auth_type=SshMachine.AUTH_AGENT,
            allow_ai_commands=True,
            is_default=True,
            notes="Runs as root; sudo is not installed. Use apt-get directly.",
        )

    def test_corv_can_append_and_replace_machine_notes(self):
        appended = set_machine_notes("PDF worker", "ps2pdf is installed.")
        self.assertIn("sudo is not installed", appended["notes"])
        self.assertIn("ps2pdf is installed", appended["notes"])

        replaced = set_machine_notes("PDF worker", "Use for document generation.", mode="replace")
        self.assertEqual(replaced["notes"], "Use for document generation.")
        self.machine.refresh_from_db()
        self.assertEqual(self.machine.notes, "Use for document generation.")

    @patch("orchestration.function_caller.PersonaService.build_persona_prompt", return_value="")
    @patch("orchestration.function_caller.get_client")
    @patch("orchestration.function_caller.resolve_provider", return_value="openai")
    def test_planner_automatically_receives_machine_notes(self, _provider, get_client, _persona):
        client = MagicMock()
        client.responses.create.return_value = SimpleNamespace(
            output_text='{"done": true, "summary": "ok"}', usage=None
        )
        get_client.return_value = client
        FunctionCallOrchestrator._plan_next_action(
            user_request="Install a PDF package",
            tool_catalog=[{
                "manifest_id": "ssh_connections.run_command",
                "module": "ssh_connections",
                "description": "Run command",
                "params_schema": {"properties": {"command": {"type": "string"}}},
            }],
            prior_results=[],
        )
        prompt = client.responses.create.call_args.kwargs["input"][0]["content"][0]["text"]
        self.assertIn("PDF worker", prompt)
        self.assertIn("sudo is not installed. Use apt-get directly.", prompt)
        self.assertIn("default=yes", prompt)
        self.assertIn("Never omit machine merely because a different machine is marked default", prompt)
        self.assertIn("call ssh_connections.list_machines first", prompt)
