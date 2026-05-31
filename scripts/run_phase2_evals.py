from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path


ARTIFACTS_DIR = Path("artifacts")
SECURITY_SCAN_IGNORED_VULNS = [
    # pip is a packaging tool in the CI environment rather than an application dependency.
    "CVE-2025-8869",
    "CVE-2026-1703",
    "CVE-2026-3219",
    "CVE-2026-6357",
]


def _run(name: str, command: list[str]) -> dict:
    result = subprocess.run(command, capture_output=True, text=True)
    return {
        "name": name,
        "command": command,
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
        "passed": result.returncode == 0,
    }


def _resolve_pip_audit_command() -> list[str] | None:
    executable = shutil.which("pip-audit")
    if executable:
        return [executable]
    if importlib.util.find_spec("pip_audit") is not None:
        return [sys.executable, "-m", "pip_audit"]
    return None


def main() -> int:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)

    checks = [
        _run(
            "core_tests",
            [
                sys.executable,
                "-m",
                "pytest",
                "tests/test_phase2_tenant_isolation.py",
                "tests/test_phase2_plan_persistence.py",
                "tests/test_phase2_supervisor.py",
                "tests/test_phase2_operations.py",
                "tests/test_phase2_workers.py",
            ],
        ),
        _run(
            "performance_benchmarks",
            [
                sys.executable,
                "scripts/benchmark_phase2.py",
                "--baseline",
                "evals/phase2_baseline.json",
                "--max-regression-pct",
                "5",
                "--output",
                "artifacts/phase2-benchmark.json",
            ],
        ),
    ]

    pip_audit_command = _resolve_pip_audit_command()
    if pip_audit_command:
        checks.append(
            _run(
                "security_scan",
                [
                    *pip_audit_command,
                    "--format",
                    "json",
                    "--output",
                    "artifacts/pip-audit.json",
                    *[
                        flag
                        for vuln_id in SECURITY_SCAN_IGNORED_VULNS
                        for flag in ("--ignore-vuln", vuln_id)
                    ],
                ],
            )
        )
    else:
        checks.append(
            {
                "name": "security_scan",
                "command": ["pip-audit"],
                "returncode": 1,
                "stdout": "",
                "stderr": "pip-audit is not installed",
                "passed": False,
            }
        )

    summary = {
        "checks": checks,
        "passed": all(check["passed"] for check in checks),
        "core_functionality_validation_pct": 100 if checks[0]["passed"] else 0,
    }
    (ARTIFACTS_DIR / "phase2-eval-summary.json").write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )

    for check in checks:
        print(f"[{check['name']}] {'PASS' if check['passed'] else 'FAIL'}")
        if check["stdout"]:
            print(check["stdout"])
        if check["stderr"]:
            print(check["stderr"], file=sys.stderr)

    return 0 if summary["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
