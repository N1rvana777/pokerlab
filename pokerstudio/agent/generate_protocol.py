"""Regenerate this machine's experimental schema into ignored runtime data."""
from pathlib import Path
import subprocess
from .app_server import codex_command


def main():
    output = Path(__file__).resolve().parents[1] / ".data/protocol-schema"
    subprocess.run(codex_command() + ["app-server", "generate-json-schema", "--experimental", "--out", str(output)], check=True)
    print(str(output))


if __name__ == "__main__":
    main()
