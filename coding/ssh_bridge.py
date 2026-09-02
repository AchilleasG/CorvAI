"""Workspace CLI that forwards Codex SSH requests to Corv's local broker."""
from __future__ import annotations

import argparse
import json
import socket
import sys
import threading


def _request(socket_path: str, payload: dict) -> dict:
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.connect(socket_path)
    connection.sendall(json.dumps(payload).encode("utf-8") + b"\n")
    connection.shutdown(socket.SHUT_WR)
    response = bytearray()
    while True:
        chunk = connection.recv(65536)
        if not chunk:
            break
        response.extend(chunk)
    connection.close()
    return json.loads(response.decode("utf-8"))


def run_command(socket_path: str, arguments: list[str]) -> int:
    # OpenSSH joins remote command arguments with spaces. Preserve that behavior
    # so existing Codex-generated ./ssh-target invocations remain compatible.
    command = " ".join(arguments)
    try:
        result = _request(socket_path, {"operation": "command", "command": command})
    except Exception as exc:
        print(f"Corv SSH broker unavailable: {exc}", file=sys.stderr)
        return 255
    if not result.get("ok"):
        print(str(result.get("error") or "Corv SSH command failed"), file=sys.stderr)
        return 255
    sys.stdout.write(str(result.get("stdout") or ""))
    sys.stderr.write(str(result.get("stderr") or ""))
    if result.get("truncated"):
        print("\n[Corv SSH output truncated]", file=sys.stderr)
    return int(result.get("exit_status", 1))


def _read_response_line(connection: socket.socket) -> dict:
    response = bytearray()
    while not response.endswith(b"\n"):
        chunk = connection.recv(1)
        if not chunk:
            raise RuntimeError("Corv SSH broker closed the tunnel request")
        response.extend(chunk)
    return json.loads(response.decode("utf-8"))


def _serve_tunnel_client(client: socket.socket, socket_path: str, host: str, port: int) -> None:
    broker = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        broker.connect(socket_path)
        broker.sendall(
            json.dumps(
                {"operation": "tunnel", "remote_host": host, "remote_port": port}
            ).encode("utf-8")
            + b"\n"
        )
        response = _read_response_line(broker)
        if not response.get("ok"):
            raise RuntimeError(str(response.get("error") or "SSH tunnel failed"))

        def copy(source: socket.socket, destination: socket.socket) -> None:
            try:
                while True:
                    data = source.recv(65536)
                    if not data:
                        break
                    destination.sendall(data)
            except OSError:
                pass
            finally:
                try:
                    destination.shutdown(socket.SHUT_WR)
                except OSError:
                    pass

        upstream = threading.Thread(target=copy, args=(client, broker), daemon=True)
        upstream.start()
        copy(broker, client)
        upstream.join(timeout=1)
    except Exception as exc:
        print(f"Corv SSH tunnel failed: {exc}", file=sys.stderr)
    finally:
        client.close()
        broker.close()


def run_tunnel(socket_path: str, forward: str) -> int:
    try:
        bind_host, local_port_text, destination = forward.split(":", 2)
        remote_host, remote_port_text = destination.rsplit(":", 1)
        local_port = int(local_port_text)
        remote_port = int(remote_port_text)
    except (ValueError, TypeError):
        print("Invalid Corv SSH tunnel forwarding specification", file=sys.stderr)
        return 2
    if bind_host not in {"127.0.0.1", "localhost"}:
        print("Corv SSH tunnels may only bind to localhost", file=sys.stderr)
        return 2
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        listener.bind(("127.0.0.1", local_port))
        listener.listen(32)
        while True:
            client, _address = listener.accept()
            threading.Thread(
                target=_serve_tunnel_client,
                args=(client, socket_path, remote_host, remote_port),
                daemon=True,
            ).start()
    except KeyboardInterrupt:
        return 0
    finally:
        listener.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=["command", "tunnel"])
    parser.add_argument("--socket", required=True)
    parser.add_argument("arguments", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    arguments = args.arguments[1:] if args.arguments[:1] == ["--"] else args.arguments
    if args.operation == "command":
        return run_command(args.socket, arguments)
    if len(arguments) != 1:
        parser.error("tunnel requires one forwarding specification")
    return run_tunnel(args.socket, arguments[0])


if __name__ == "__main__":
    raise SystemExit(main())
