import subprocess
import sys


def test_cli_help():
    res = subprocess.run([sys.executable, "-m", "relaypulse.cli", "--help"], capture_output=True, text=True)
    assert res.returncode == 0
    assert "RelayPulse" in res.stdout or "relaypulse" in res.stdout


def test_cli_verify_sig():
    res = subprocess.run(
        [
            sys.executable, "-m", "relaypulse.cli", "verify-sig",
            "--payload", '{"test": 1}',
            "--signature", "t=1729471200,v1=invalidsignature",
            "--secret", "my_secret"
        ],
        capture_output=True,
        text=True
    )
    # Verification of invalid signature returns exit code 1
    assert res.returncode == 1
    assert "failed" in res.stdout.lower() or "failed" in res.stderr.lower()
