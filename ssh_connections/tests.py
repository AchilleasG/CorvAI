from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from orchestration.crypto import decrypt_value
from ssh_connections.models import SshCommandRecord, SshMachine
from ssh_connections.services import OpenTerminalSession, SshConnectionManager, key_fingerprint


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
