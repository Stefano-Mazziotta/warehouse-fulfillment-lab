import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def port_is_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except OSError:
        return False


def wait_until(predicate, timeout_seconds: float, interval: float = 0.25) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


class Supervisor:
    """Starts host processes and stops exactly those, never anything matched by name.

    Each child is the real interpreter (`sys.executable`), so `Popen.pid` is the process to
    signal; going through `uv run` would make that PID a wrapper. stderr is appended to the
    log file Alloy tails; stdout is discarded because the apps log to stderr only.
    """

    def __init__(self, log_path: Path) -> None:
        self._log = open(log_path, "ab")
        self._children: list[tuple[str, subprocess.Popen]] = []

    def start(self, name: str, args: list[str], env: dict[str, str]) -> subprocess.Popen:
        child = subprocess.Popen(
            [sys.executable, *args], env=env, stdout=subprocess.DEVNULL, stderr=self._log)
        self._children.append((name, child))
        return child

    def stop(self, child: subprocess.Popen) -> None:
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        self._children = [(n, c) for n, c in self._children if c is not child]

    def stop_all(self) -> None:
        for _, child in reversed(list(self._children)):
            self.stop(child)
        self._log.close()

    def describe(self) -> list[str]:
        return [f"{name} (pid {child.pid})" for name, child in self._children]


def wait_for_health(base_url: str, child: subprocess.Popen, timeout_seconds: float = 30.0) -> None:
    def healthy() -> bool:
        if child.poll() is not None:
            raise RuntimeError(f"the API exited with code {child.returncode}; see logs/backend.log")
        try:
            with urllib.request.urlopen(f"{base_url}/health", timeout=1):
                return True
        except (urllib.error.URLError, OSError):
            return False

    if not wait_until(healthy, timeout_seconds):
        raise RuntimeError(f"the API at {base_url} did not become healthy in {timeout_seconds:.0f}s")
