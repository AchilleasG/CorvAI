"""Bounded headless-browser harness used by independent Codex QA turns."""
from __future__ import annotations

import argparse
import json
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as conditions
from selenium.webdriver.support.select import Select
from selenium.webdriver.support.ui import WebDriverWait


MAX_STEPS = 40
ALLOWED_KEYS = {name: getattr(Keys, name) for name in ("ENTER", "TAB", "ESCAPE", "ARROW_UP", "ARROW_DOWN", "SPACE")}


def _safe_name(value: str, fallback: str) -> str:
    clean = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value or "").strip("-.")
    return (clean or fallback)[:100]


def _element(driver, selector: str, timeout: float):
    return WebDriverWait(driver, timeout).until(
        conditions.presence_of_element_located((By.CSS_SELECTOR, selector))
    )


def _start_tunnel(spec: dict, timeout: float):
    tunnel = spec.get("ssh_tunnel")
    if not tunnel:
        return None
    if not isinstance(tunnel, dict):
        raise ValueError("ssh_tunnel must be an object")
    local_port = int(tunnel.get("local_port", 0))
    remote_port = int(tunnel.get("remote_port", 0))
    remote_host = str(tunnel.get("remote_host") or "127.0.0.1").strip()
    if not (1024 <= local_port <= 65535 and 1 <= remote_port <= 65535):
        raise ValueError("ssh_tunnel ports are invalid")
    if not re.fullmatch(r"[a-zA-Z0-9.:-]+", remote_host):
        raise ValueError("ssh_tunnel remote_host is invalid")
    wrapper = (Path.cwd() / "ssh-tunnel").resolve()
    if not wrapper.is_file():
        raise ValueError("The SSH tunnel wrapper is unavailable")
    forward = f"127.0.0.1:{local_port}:{remote_host}:{remote_port}"
    process = subprocess.Popen(
        [str(wrapper), forward],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            detail = process.stderr.read().strip() if process.stderr else ""
            raise RuntimeError(detail or "The SSH browser tunnel could not be opened")
        try:
            with socket.create_connection(("127.0.0.1", local_port), timeout=0.25):
                return process
        except OSError:
            time.sleep(0.15)
    process.terminate()
    raise RuntimeError("Timed out waiting for the SSH browser tunnel")


def run_spec(spec: dict, output_dir: Path) -> dict:
    steps = spec.get("steps") or []
    if not isinstance(steps, list) or len(steps) > MAX_STEPS:
        raise ValueError(f"Browser spec must contain at most {MAX_STEPS} steps")
    output_dir.mkdir(parents=True, exist_ok=True)
    timeout = min(max(float(spec.get("timeout_seconds", 15)), 1), 45)
    width = min(max(int(spec.get("viewport_width", 1440)), 320), 1920)
    height = min(max(int(spec.get("viewport_height", 900)), 320), 1080)

    options = webdriver.ChromeOptions()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--disable-background-networking")
    options.add_argument(f"--window-size={width},{height}")
    options.set_capability("goog:loggingPrefs", {"browser": "ALL"})

    report = {"success": True, "steps": [], "screenshots": [], "console": [], "final_url": ""}
    tunnel_process = None
    driver = None
    try:
        tunnel_process = _start_tunnel(spec, timeout)
        driver = webdriver.Chrome(options=options)
        driver.set_page_load_timeout(timeout)
        start_url = str(spec.get("start_url") or "").strip()
        if start_url:
            driver.get(start_url)
        for index, step in enumerate(steps, start=1):
            if not isinstance(step, dict):
                raise ValueError(f"Step {index} must be an object")
            action = str(step.get("action") or "").strip().lower()
            selector = str(step.get("selector") or "")
            result = {"index": index, "action": action, "ok": True}
            if action == "goto":
                driver.get(str(step["url"]))
            elif action == "click":
                WebDriverWait(driver, timeout).until(
                    conditions.element_to_be_clickable((By.CSS_SELECTOR, selector))
                ).click()
            elif action == "fill":
                element = _element(driver, selector, timeout)
                element.clear()
                element.send_keys(str(step.get("value") or ""))
            elif action == "press":
                key = str(step.get("key") or "ENTER").upper()
                if key not in ALLOWED_KEYS:
                    raise ValueError(f"Unsupported key: {key}")
                _element(driver, selector, timeout).send_keys(ALLOWED_KEYS[key])
            elif action == "select":
                Select(_element(driver, selector, timeout)).select_by_value(str(step.get("value") or ""))
            elif action == "wait_for":
                WebDriverWait(driver, timeout).until(
                    conditions.visibility_of_element_located((By.CSS_SELECTOR, selector))
                )
            elif action == "assert_visible":
                element = _element(driver, selector, timeout)
                if not element.is_displayed():
                    raise AssertionError(f"Element is not visible: {selector}")
            elif action == "assert_text":
                scope = _element(driver, selector, timeout) if selector else driver.find_element(By.TAG_NAME, "body")
                expected = str(step.get("text") or "")
                if expected not in scope.text:
                    raise AssertionError(f"Expected text was not found: {expected}")
            elif action == "assert_url_contains":
                expected = str(step.get("text") or step.get("value") or "")
                if expected not in driver.current_url:
                    raise AssertionError(f"URL does not contain: {expected}")
            elif action == "screenshot":
                filename = _safe_name(str(step.get("name") or ""), f"step-{index}") + ".png"
                path = output_dir / filename
                driver.save_screenshot(str(path))
                report["screenshots"].append(str(path.resolve()))
            elif action == "sleep":
                time.sleep(min(max(float(step.get("seconds", 1)), 0), 5))
            else:
                raise ValueError(f"Unsupported browser action: {action}")
            report["steps"].append(result)

        final_path = output_dir / "final.png"
        driver.save_screenshot(str(final_path))
        if str(final_path.resolve()) not in report["screenshots"]:
            report["screenshots"].append(str(final_path.resolve()))
        report["final_url"] = driver.current_url
        report["console"] = driver.get_log("browser")[-100:]
        return report
    except Exception as exc:
        report["success"] = False
        report["error"] = str(exc)
        failure_path = output_dir / "failure.png"
        try:
            if driver is None:
                raise RuntimeError("Browser did not start")
            driver.save_screenshot(str(failure_path))
            report["screenshots"].append(str(failure_path.resolve()))
            report["final_url"] = driver.current_url
            report["console"] = driver.get_log("browser")[-100:]
        except Exception:
            pass
        return report
    finally:
        if driver is not None:
            driver.quit()
        if tunnel_process is not None and tunnel_process.poll() is None:
            tunnel_process.terminate()
            try:
                tunnel_process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                tunnel_process.kill()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a bounded browser QA specification")
    parser.add_argument("spec", help="JSON browser specification")
    parser.add_argument("--output-dir", default="qa-evidence", help="Screenshot/report directory")
    args = parser.parse_args()
    spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
    output_dir = Path(args.output_dir).resolve()
    report = run_spec(spec, output_dir)
    report_path = output_dir / "report.json"
    report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0 if report["success"] else 1


if __name__ == "__main__":
    sys.exit(main())
