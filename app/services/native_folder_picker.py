"""The operating system's own folder dialog, opened by the server on this machine (the
backup folder, and the Obsidian vault to import)."""

from __future__ import annotations

import shutil
import subprocess
import sys


def _run_native_folder_picker_command(*, command: list[str]) -> str | None:
    if not isinstance(command, list) or len(command) == 0:
        raise TypeError("command must be a non-empty list")
    completed = subprocess.run(
        command,
        capture_output=True,
        check=False,
        text=True,
    )
    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    if completed.returncode == 0:
        if stdout == "":
            return None
        return stdout
    if completed.returncode == 1 and (stderr == "" or "User canceled" in stderr or "(-128)" in stderr):
        return None
    raise RuntimeError(
        f"Native folder picker failed: exit={completed.returncode} stdout={stdout!r} stderr={stderr!r}"
    )


def pick_folder(*, prompt: str) -> str | None:
    """The folder the user picks in the operating system's own folder dialog, titled
    prompt (a plain sentence, no quotes), or None when they cancel."""
    if not isinstance(prompt, str) or prompt == "" or "'" in prompt or '"' in prompt:
        raise ValueError(f"prompt must be a plain sentence without quotes, got {prompt!r}")
    if sys.platform == "darwin":
        osascript_path = shutil.which("osascript")
        if osascript_path is None:
            raise RuntimeError("`osascript` is required for the macOS folder picker")
        return _run_native_folder_picker_command(
            command=[
                osascript_path,
                "-e",
                f'POSIX path of (choose folder with prompt "{prompt}")',
            ]
        )

    if sys.platform.startswith("linux"):
        zenity_path = shutil.which("zenity")
        if zenity_path is not None:
            return _run_native_folder_picker_command(
                command=[
                    zenity_path,
                    "--file-selection",
                    "--directory",
                    f"--title={prompt}",
                ]
            )
        kdialog_path = shutil.which("kdialog")
        if kdialog_path is not None:
            return _run_native_folder_picker_command(
                command=[
                    kdialog_path,
                    "--getexistingdirectory",
                    "",
                    "--title",
                    prompt,
                ]
            )
        raise RuntimeError("No supported Linux folder picker was found (`zenity` or `kdialog`)")

    if sys.platform == "win32":
        powershell_path = shutil.which("powershell")
        if powershell_path is None:
            powershell_path = shutil.which("pwsh")
        if powershell_path is None:
            raise RuntimeError("PowerShell is required for the Windows folder picker")
        script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog; "
            f"$dialog.Description = '{prompt}'; "
            "$dialog.ShowNewFolderButton = $true; "
            "if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) { "
            "Write-Output $dialog.SelectedPath; exit 0 }; "
            "exit 1"
        )
        return _run_native_folder_picker_command(
            command=[powershell_path, "-NoProfile", "-Command", script]
        )

    raise RuntimeError(f"Native folder picker is not supported on platform: {sys.platform}")
