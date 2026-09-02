from typing import Optional

from ninja import Schema


class SshMachineIn(Schema):
    name: str
    host: str
    port: int = 22
    username: str
    auth_type: str = "private_key"
    password: str = ""
    private_key: str = ""
    passphrase: str = ""
    allow_ai_commands: bool = False
    is_default: bool = False
    connect_timeout_seconds: int = 15
    command_timeout_seconds: int = 120
    keepalive_seconds: int = 30
    notes: str = ""


class SshMachineUpdate(Schema):
    name: Optional[str] = None
    host: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    auth_type: Optional[str] = None
    password: Optional[str] = None
    private_key: Optional[str] = None
    passphrase: Optional[str] = None
    allow_ai_commands: Optional[bool] = None
    is_default: Optional[bool] = None
    connect_timeout_seconds: Optional[int] = None
    command_timeout_seconds: Optional[int] = None
    keepalive_seconds: Optional[int] = None
    notes: Optional[str] = None
    reset_host_key: bool = False


class SshCommandIn(Schema):
    command: str
    timeout_seconds: Optional[int] = None


class SshTerminalSessionIn(Schema):
    name: str = "Terminal"
