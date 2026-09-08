"""Integration tests: real deny checks under sandbox-exec (macOS only) and a negative control.

These are the only tests that touch the network. They are skipped, not failed, when the
platform lacks sandbox-exec or the host has no working network.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SANDBOX = ROOT / "sandbox"
PYTHON = sys.executable
SANDBOX_EXEC = shutil.which("sandbox-exec") or "/usr/bin/sandbox-exec"
IS_DARWIN = sys.platform == "darwin" and os.path.exists(SANDBOX_EXEC)


def _host_has_network() -> bool:
    try:
        with socket.create_connection(("1.1.1.1", 443), timeout=3):
            pass
        socket.getaddrinfo("example.com", 443)
    except OSError:
        return False
    return True


def _run_sandboxed(
    args: list[str], write_dir: Path, port: str = "18599"
) -> subprocess.CompletedProcess[str]:
    cmd = [
        SANDBOX_EXEC,
        "-f",
        str(SANDBOX / "macos-dev.sb"),
        "-D",
        f"service_port={port}",
        "-D",
        f"write_dir={write_dir}",
        PYTHON,
        *args,
    ]
    env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8"}
    return subprocess.run(cmd, check=False, capture_output=True, text=True, env=env, timeout=120)


@pytest.mark.skipif(not IS_DARWIN, reason="sandbox-exec integration test only runs on macOS")
def test_deny_check_under_sandbox_exec_denies_every_probe(tmp_path: Path) -> None:
    out = tmp_path / "deny-check.json"
    proc = _run_sandboxed(
        [
            str(SANDBOX / "deny_check.py"),
            "--backend",
            "sandbox-exec",
            "--instance-id",
            "test-inst",
            "--policy",
            str(SANDBOX / "macos-dev.sb"),
            "--timeout",
            "5",
            "--output",
            str(out),
        ],
        tmp_path,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    evidence = json.loads(out.read_text())
    outcomes = {p["name"]: p["outcome"] for p in evidence["probes"]}
    assert set(outcomes) == {
        "https_well_known",
        "tcp_direct_ip",
        "dns_resolve",
        "udp_dns_query",
        "proxy_env_bogus_loopback",
        "proxy_env_cleared_direct_ip",
    }
    assert all(o == "denied" for o in outcomes.values()), outcomes
    assert evidence["summary"]["all_expected"] is True
    assert evidence["negative_control"] is False
    # Every denial was immediate: the profile refuses, nothing waited on a dead network.
    assert all(p["duration_ms"] < 2000 for p in evidence["probes"])
    assert (out.stat().st_mode & 0o777) == 0o600


@pytest.mark.skipif(not IS_DARWIN, reason="sandbox-exec integration test only runs on macOS")
def test_sandbox_exec_profile_blocks_writes_outside_runtime_dir(tmp_path: Path) -> None:
    outside = tmp_path.parent / f"{tmp_path.name}-outside.txt"
    proc = _run_sandboxed(["-c", f"open({str(outside)!r}, 'w').write('x')"], tmp_path)
    assert proc.returncode != 0
    assert not outside.exists()
    inside = tmp_path / "inside.txt"
    proc = _run_sandboxed(["-c", f"open({str(inside)!r}, 'w').write('x')"], tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert inside.exists()


@pytest.mark.skipif(
    not _host_has_network(), reason="host has no working network; negative control needs one"
)
def test_negative_control_unsandboxed_succeeds(tmp_path: Path) -> None:
    out = tmp_path / "negative-control.json"
    proc = subprocess.run(
        [
            PYTHON,
            str(SANDBOX / "deny_check.py"),
            "--negative-control",
            "--timeout",
            "8",
            "--output",
            str(out),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    evidence = json.loads(out.read_text())
    assert evidence["negative_control"] is True
    assert all(p["outcome"] == "succeeded" for p in evidence["probes"]), evidence["probes"]
    reasons = {p["name"]: p["reason"] for p in evidence["probes"]}
    assert reasons["proxy_env_bogus_loopback"] == "PROXY_ENV_HONORED"


@pytest.mark.skipif(not IS_DARWIN, reason="launcher integration only runs on macOS")
def test_start_stop_launcher_with_mock_service(tmp_path: Path) -> None:
    """start.sh --mock under sandbox-exec: evidence is produced, bound to the instance, then
    invalidated by stop.sh. The mock never becomes ready (mode=mock) regardless of evidence."""
    port = "18597"
    runtime = tmp_path / "rt"
    env = {**os.environ, "PLVA_PR_PORT": port}
    skip = [] if _host_has_network() else ["--skip-negative-control"]
    proc = subprocess.run(
        [
            str(SANDBOX / "start.sh"),
            "--backend",
            "macos-dev",
            "--mock",
            "--runtime-dir",
            str(runtime),
            *skip,
        ],
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=180,
        cwd=ROOT,
    )
    try:
        assert proc.returncode == 0, proc.stdout + proc.stderr
        iso = json.loads((runtime / "isolation-evidence.json").read_text())
        assert iso["isolation"] == "verified"
        cred = (runtime / "credential").read_text().strip()
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/v1/readiness", headers={"Authorization": f"Bearer {cred}"}
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            readiness = json.loads(resp.read())
        assert readiness["instance_id"] == iso["instance_id"]
        assert readiness["ready_for_private_values"] is False  # mock stays unready
    finally:
        subprocess.run(
            [str(SANDBOX / "stop.sh"), "--backend", "macos-dev", "--runtime-dir", str(runtime)],
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
    assert not (runtime / "isolation-evidence.json").exists()
    assert not (runtime / "credential").exists()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", int(port)), timeout=0.5):
                time.sleep(0.25)
        except OSError:
            break
    else:
        pytest.fail("service still listening after stop.sh")
