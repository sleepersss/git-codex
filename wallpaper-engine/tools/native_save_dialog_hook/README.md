# Native Save Dialog Hook

This directory contains a small, reversible test hook for the Wallpaper Engine
`wallpaperui.exe` process.

The hook uses an import address table (IAT) replacement. It does not overwrite
the prologue of a Windows system function and does not build a trampoline.
The old inline trampoline experiment is recorded as failed.
Attempts to auto-close `IFileDialog::Show` through vtable replacement,
`IFileDialogEvents`, and same-apartment timers failed in isolated probes and
are not used.

The hook targets:

```text
ole32!CoCreateInstance
```

When the created COM class is:

```text
CLSID_FileSaveDialog
```

and the returned interface is `IFileSaveDialog`, the hook calls:

```text
SetFolder(OutputDir)
SetFileName(FileName)
```

`FileName` is deliberately a basename only.

For processes that do not inherit the caller environment, configuration is
read from:

```text
temp\logs\native_save_dialog_hook.ini
```

The helper `tools\inject_native_save_dialog_hook.ps1` waits for a new
`wallpaperui.exe` process and injects only that process.

The component is not part of the production export flow yet. It must be
compiled, inspected, and then tested with only Workshop ID `2803091109`.
It does not modify `scripts.js`, Wallpaper Engine binaries, the database,
Workshop files, or the formal archive.
