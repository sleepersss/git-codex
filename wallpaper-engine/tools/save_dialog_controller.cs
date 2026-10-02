using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Runtime.InteropServices;
using System.Windows.Automation;

internal static class SaveDialogController
{
    private const string StateWaiting = "WAITING_FOR_DIALOG";
    private const string StateFound = "FOUND_SAVE_DIALOG";
    private const string StateVerifying = "VERIFYING_DIALOG";
    private const string StateFolder = "VERIFYING_FOLDER";
    private const string StateFilename = "VERIFYING_FILENAME";
    private const string StateButton = "FINDING_SAVE_BUTTON";
    private const string StateButtonVerify = "VERIFYING_SAVE_BUTTON";
    private const string StateInvoke = "INVOKING_SAVE";
    private const string StateClosed = "WAITING_FOR_DIALOG_CLOSE";
    private const string StateOutput = "WAITING_FOR_OUTPUT";
    private const string StateVerifyOutput = "VERIFYING_OUTPUT";
    private const string StateSuccess = "SUCCESS";
    private const string StateFailed = "FAILED";

    private static readonly string[] SaveNames =
        { "保存", "Save", "Save As", "另存为", "存储" };
    private static readonly string[] ReplaceNames =
        { "替换", "Replace", "Yes", "是", "确定", "OK" };

    private static string _outputDir = "";
    private static string _fileName = "";
    private static string _expectedPath = "";
    private static string _wrongPath = "";
    private static string _logPath = "";
    private static DateTime _startedAt;
    private static DateTime _invokeTime;
    private static bool _saveInvoked;
    private static long _lastObservedOutputLength = -1;
    private static DateTime _lastObservedOutputWriteTimeUtc = DateTime.MinValue;
    private static DateTime _outputStableSinceUtc = DateTime.MinValue;
    private static DateTime _lastOutputBusyLogUtc = DateTime.MinValue;

    private static class NativeWindow
    {
        internal delegate bool EnumWindowsProc(IntPtr hwnd, IntPtr lParam);

        [DllImport("user32.dll")]
        internal static extern bool IsWindow(IntPtr hwnd);

        [DllImport("user32.dll")]
        internal static extern bool IsWindowVisible(IntPtr hwnd);

        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        internal static extern int GetWindowText(
            IntPtr hwnd,
            StringBuilder text,
            int count);

        [DllImport("user32.dll", CharSet = CharSet.Unicode)]
        internal static extern int GetClassName(
            IntPtr hwnd,
            StringBuilder text,
            int count);

        [DllImport("user32.dll")]
        internal static extern bool EnumWindows(
            EnumWindowsProc callback,
            IntPtr lParam);

        [DllImport("user32.dll")]
        internal static extern uint GetWindowThreadProcessId(
            IntPtr hwnd,
            out uint processId);

        internal static IEnumerable<IntPtr> TopLevelWindows()
        {
            var handles = new List<IntPtr>();
            EnumWindows((hwnd, lParam) =>
            {
                if (IsWindowVisible(hwnd))
                    handles.Add(hwnd);
                return true;
            }, IntPtr.Zero);
            return handles;
        }
    }

    private static void Log(string message)
    {
        var line = DateTime.Now.ToString("o") + " " + message;
        Console.WriteLine(line);
        File.AppendAllText(_logPath, line + Environment.NewLine, Encoding.UTF8);
    }

    private static void State(string state, string detail = "")
    {
        Log("STATE=" + state + (string.IsNullOrWhiteSpace(detail) ? "" : " " + detail));
    }

    private static string Normalize(string value)
    {
        if (string.IsNullOrWhiteSpace(value)) return "";
        try
        {
            return Path.GetFullPath(value).TrimEnd('\\').ToLowerInvariant();
        }
        catch
        {
            return value.TrimEnd('\\').ToLowerInvariant();
        }
    }

    private static IEnumerable<AutomationElement> Descendants(AutomationElement root)
    {
        var all = root.FindAll(TreeScope.Descendants, Condition.TrueCondition);
        for (var i = 0; i < all.Count; i++) yield return all[i];
    }

    private static string ReadValue(AutomationElement element)
    {
        var values = new List<string>();
        try
        {
            if (element.TryGetCurrentPattern(ValuePattern.Pattern, out var raw))
                values.Add(((ValuePattern)raw).Current.Value ?? "");
        }
        catch { }
        try { values.Add(element.Current.Name ?? ""); } catch { }
        return string.Join(" || ", values.Where(x => !string.IsNullOrWhiteSpace(x)).Distinct());
    }

    private static bool IsWindow(AutomationElement element)
    {
        try
        {
            if (element.Current.ControlType != ControlType.Window)
                return false;

            var name = element.Current.Name ?? "";
            return name.IndexOf("\u53E6\u5B58\u4E3A", StringComparison.OrdinalIgnoreCase) >= 0 ||
                   name.IndexOf("Save", StringComparison.OrdinalIgnoreCase) >= 0;
        }
        catch { return false; }
    }

    private static IEnumerable<AutomationElement> SaveDialogs()
    {
        var result = new List<AutomationElement>();
        var handles = new HashSet<int>();
        var root = AutomationElement.RootElement;
        var windows = root.FindAll(TreeScope.Children,
            new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.Window));
        for (var i = 0; i < windows.Count; i++)
        {
            var window = windows[i];
            if (IsWindow(window))
            {
                var hwnd = window.Current.NativeWindowHandle;
                if (handles.Add(hwnd))
                    result.Add(window);
            }
        }

        foreach (var hwnd in NativeWindow.TopLevelWindows())
        {
            try
            {
                var titleBuilder = new StringBuilder(512);
                var classBuilder = new StringBuilder(256);
                NativeWindow.GetWindowText(hwnd, titleBuilder, titleBuilder.Capacity);
                NativeWindow.GetClassName(hwnd, classBuilder, classBuilder.Capacity);
                var title = titleBuilder.ToString();
                if (title.IndexOf("\u53E6\u5B58\u4E3A", StringComparison.OrdinalIgnoreCase) < 0 &&
                    title.IndexOf("Save", StringComparison.OrdinalIgnoreCase) < 0)
                    continue;

                var window = AutomationElement.FromHandle(hwnd);
                if (IsWindow(window) && handles.Add(window.Current.NativeWindowHandle))
                {
                    Log("WIN32_SAVE_WINDOW hwnd=" + hwnd.ToInt64() +
                        " title='" + title + "' class='" + classBuilder + "'");
                    result.Add(window);
                }
            }
            catch
            {
                // The window may close while UI Automation is attaching.
            }
        }
        return result;
    }

    private static bool IsUsable(AutomationElement element)
    {
        try { return element.Current.IsEnabled && !element.Current.IsOffscreen; }
        catch { return false; }
    }

    private static bool ContainsTarget(string text, string target)
    {
        if (string.IsNullOrWhiteSpace(text)) return false;
        var normalizedText = text.Replace('/', '\\').ToLowerInvariant();
        var normalizedTarget = Normalize(target);
        return Normalize(text) == normalizedTarget ||
               normalizedText.Contains(normalizedTarget);
    }

    private static bool VerifyFolder(AutomationElement dialog)
    {
        var matches = new List<string>();
        foreach (var element in Descendants(dialog))
        {
            string value;
            try { value = ReadValue(element); } catch { continue; }
            if (ContainsTarget(value, _outputDir)) matches.Add(value);
        }
        Log("FOLDER_VERIFY target='" + _outputDir + "' result=" + (matches.Count > 0) +
            " values='" + string.Join(" || ", matches.Distinct()) + "'");
        return matches.Count > 0;
    }

    private static AutomationElement FindFilenameEditor(AutomationElement dialog)
    {
        var candidates = Descendants(dialog).Where(e =>
        {
            try
            {
                return e.Current.ControlType == ControlType.Edit && IsUsable(e);
            }
            catch { return false; }
        }).ToList();

        foreach (var candidate in candidates)
        {
            var value = ReadValue(candidate);
            if (value.IndexOf(_fileName, StringComparison.OrdinalIgnoreCase) >= 0)
                return candidate;
        }

        var named = candidates.FirstOrDefault(e =>
            ReadValue(e).IndexOf("文件名", StringComparison.OrdinalIgnoreCase) >= 0 ||
            ReadValue(e).IndexOf("File name", StringComparison.OrdinalIgnoreCase) >= 0);
        return named ?? candidates.LastOrDefault();
    }

    private static bool VerifyFilename(AutomationElement dialog)
    {
        var editor = FindFilenameEditor(dialog);
        var actual = editor == null ? "" : ReadValue(editor);
        Log("FILENAME_VERIFY expected='" + _fileName + "' actual='" + actual + "'");
        var values = actual.Split(new[] { " || " }, StringSplitOptions.None)
            .Select(x => x.Trim())
            .ToList();
        var exact = values.Any(x =>
            string.Equals(x, _fileName, StringComparison.OrdinalIgnoreCase));
        var stem = Path.GetFileNameWithoutExtension(_fileName);
        var extension = Path.GetExtension(_fileName);
        var extensionOmitted = !string.IsNullOrEmpty(extension) && values.Any(x =>
            string.Equals(x, stem, StringComparison.OrdinalIgnoreCase));
        Log("FILENAME_VERIFY exact=" + exact +
            " extensionOmitted=" + extensionOmitted +
            " expectedStem='" + stem + "' expectedExtension='" + extension + "'");
        return exact || extensionOmitted;
    }

    private static AutomationElement FindButton(AutomationElement dialog, IEnumerable<string> names)
    {
        var buttons = Descendants(dialog).Where(e =>
        {
            try
            {
                return (e.Current.ControlType == ControlType.Button ||
                        e.Current.ControlType == ControlType.Pane) &&
                       IsUsable(e);
            }
            catch { return false; }
        });

        foreach (var button in buttons)
        {
            var name = "";
            var automationId = "";
            try { name = button.Current.Name ?? ""; } catch { }
            try { automationId = button.Current.AutomationId ?? ""; } catch { }
            var normalizedName = name.Replace("&", "").Trim();
            var isSaveName =
                names.Any(x => string.Equals(x, normalizedName, StringComparison.OrdinalIgnoreCase)) ||
                normalizedName.StartsWith("Save", StringComparison.OrdinalIgnoreCase) ||
                normalizedName.StartsWith("\u4FDD\u5B58", StringComparison.OrdinalIgnoreCase);
            if (isSaveName)
            {
                Log("SAVE_BUTTON_CANDIDATE Name='" + name +
                    "' AutomationId='" + automationId +
                    "' ControlType='" + button.Current.ControlType.ProgrammaticName + "'");
                return button;
            }
        }
        return null;
    }

    private static bool InvokeSave(AutomationElement dialog, AutomationElement button)
    {
        if (_saveInvoked) return false;
        if (!VerifyFolder(dialog) || !VerifyFilename(dialog))
        {
            Log("PRE_INVOKE_REVALIDATION_FAILED");
            return false;
        }

        string automationId = "";
        string name = "";
        string controlType = "";
        bool isEnabled = false;
        try
        {
            automationId = button.Current.AutomationId ?? "";
            name = button.Current.Name ?? "";
            controlType = button.Current.ControlType.ProgrammaticName ?? "";
            isEnabled = button.Current.IsEnabled;
        }
        catch (Exception ex)
        {
            Log("SAVE_BUTTON_PROPERTY_READ_FAILED type='" + ex.GetType().FullName +
                "' message='" + ex.Message.Replace("'", "\"") + "'");
            return false;
        }

        object rawPattern;
        bool hasInvokePattern = button.TryGetCurrentPattern(
            InvokePattern.Pattern, out rawPattern);
        Log("SAVE_BUTTON AutomationId='" + automationId + "' Name='" + name +
            "' ControlType='" + controlType + "' IsEnabled=" + isEnabled +
            " InvokePatternAvailable=" + hasInvokePattern);
        State(StateButtonVerify, "enabled=" + isEnabled +
              " invokePattern=" + hasInvokePattern);
        if (!isEnabled || !hasInvokePattern)
        {
            Log("SAVE_BUTTON_NOT_INVOKABLE");
            return false;
        }

        _saveInvoked = true;
        _invokeTime = DateTime.Now;
        State(StateInvoke, "time='" + _invokeTime.ToString("o") + "'");
        try
        {
            ((InvokePattern)rawPattern).Invoke();
            Log("SAVE_INVOKE result=RETURNED time='" + _invokeTime.ToString("o") + "'");
            return true;
        }
        catch (Exception ex)
        {
            Log("SAVE_INVOKE result=EXCEPTION type='" + ex.GetType().FullName +
                "' message='" + ex.Message.Replace("'", "\"") +
                "' time='" + _invokeTime.ToString("o") + "'");
            return false;
        }
    }

    private static bool WaitDialogClosed(AutomationElement dialog, TimeSpan timeout)
    {
        var deadline = DateTime.UtcNow + timeout;
        while (DateTime.UtcNow < deadline)
        {
            try
            {
                var hwnd = new IntPtr(dialog.Current.NativeWindowHandle);
                if (!NativeWindow.IsWindow(hwnd))
                {
                    Log("SAVE_DIALOG_CLOSED hwnd=" + hwnd.ToInt64() +
                        " time='" + DateTime.Now.ToString("o") + "'");
                    return true;
                }
            }
            catch (ElementNotAvailableException)
            {
                Log("SAVE_DIALOG_CLOSED elementUnavailable=true time='" +
                    DateTime.Now.ToString("o") + "'");
                return true;
            }
            Thread.Sleep(200);
        }
        Log("SAVE_DIALOG_CLOSE_TIMEOUT time='" + DateTime.Now.ToString("o") + "'");
        return false;
    }

    private static bool VerifyOutput()
    {
        var info = new FileInfo(_expectedPath);
        if (!info.Exists || info.Length <= 0) return false;
        var full = Path.GetFullPath(info.FullName);
        if (!string.Equals(full, _expectedPath, StringComparison.OrdinalIgnoreCase)) return false;
        if (info.LastWriteTime <= _startedAt)
        {
            Log("OUTPUT_NOT_FRESH lastWrite='" + info.LastWriteTime.ToString("o") +
                "' started='" + _startedAt.ToString("o") + "'");
            return false;
        }

        var observedWriteTimeUtc = info.LastWriteTimeUtc;
        if (_lastObservedOutputLength != info.Length ||
            _lastObservedOutputWriteTimeUtc != observedWriteTimeUtc)
        {
            _lastObservedOutputLength = info.Length;
            _lastObservedOutputWriteTimeUtc = observedWriteTimeUtc;
            _outputStableSinceUtc = DateTime.UtcNow;
            Log("OUTPUT_STABILIZING size=" + info.Length +
                " lastWriteUtc='" + observedWriteTimeUtc.ToString("o") + "'");
            return false;
        }

        if (DateTime.UtcNow - _outputStableSinceUtc < TimeSpan.FromSeconds(3))
            return false;

        try
        {
            string hash;
            long readLength;
            using (var sha = SHA256.Create())
            using (var stream = new FileStream(
                full,
                FileMode.Open,
                FileAccess.Read,
                FileShare.ReadWrite | FileShare.Delete))
            {
                readLength = stream.Length;
                if (readLength != info.Length) return false;
                hash = BitConverter.ToString(sha.ComputeHash(stream)).Replace("-", "");
            }

            var after = new FileInfo(full);
            after.Refresh();
            if (!after.Exists ||
                after.Length != info.Length ||
                after.LastWriteTimeUtc != observedWriteTimeUtc ||
                readLength != after.Length)
            {
                _lastObservedOutputLength = -1;
                _lastObservedOutputWriteTimeUtc = DateTime.MinValue;
                _outputStableSinceUtc = DateTime.MinValue;
                Log("OUTPUT_CHANGED_DURING_VERIFY path='" + full + "'");
                return false;
            }

            Log("OUTPUT fullName='" + full + "' size=" + after.Length +
                " creation='" + after.CreationTime.ToString("o") +
                "' lastWrite='" + after.LastWriteTime.ToString("o") +
                "' sha256='" + hash + "' invokeTime='" + _invokeTime.ToString("o") + "'");
        }
        catch (IOException ex)
        {
            if (DateTime.UtcNow - _lastOutputBusyLogUtc >= TimeSpan.FromSeconds(5))
            {
                Log("OUTPUT_BUSY retry=true reason='" + ex.Message.Replace("'", "\"") + "'");
                _lastOutputBusyLogUtc = DateTime.UtcNow;
            }
            return false;
        }

        return true;
    }

    private static void LogWrongLocation()
    {
        var info = new FileInfo(_wrongPath);
        if (!info.Exists || info.Length <= 0) return;
        Log("WRONG_LOCATION path='" + info.FullName + "' size=" + info.Length +
            " creation='" + info.CreationTime.ToString("o") +
            "' lastWrite='" + info.LastWriteTime.ToString("o") + "'");
    }

    private static int Main(string[] args)
    {
        try
        {
            if (args.Length < 3)
                throw new ArgumentException("usage: save_dialog_controller.exe <output-dir> <filename> <log-path> [timeout-seconds]");

            _outputDir = Path.GetFullPath(args[0]).TrimEnd('\\');
            _fileName = args[1];
            _logPath = Path.GetFullPath(args[2]);
            var timeout = args.Length >= 4 ? int.Parse(args[3]) : 180;
            if (string.IsNullOrWhiteSpace(_fileName) ||
                _fileName.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0 ||
                _fileName != Path.GetFileName(_fileName))
                throw new ArgumentException("filename must be a pure basename");

            Directory.CreateDirectory(_outputDir);
            Directory.CreateDirectory(Path.GetDirectoryName(_logPath));
            _expectedPath = Path.GetFullPath(Path.Combine(_outputDir, _fileName));
            _wrongPath = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.MyDocuments), _fileName);
            _startedAt = DateTime.Now;
            File.WriteAllText(_logPath, "", Encoding.UTF8);
            State(StateWaiting, "target='" + _expectedPath + "'");

            var initial = new HashSet<int>(SaveDialogs()
                .Select(x => x.Current.NativeWindowHandle));
            var deadline = DateTime.UtcNow.AddSeconds(timeout);
            while (DateTime.UtcNow < deadline)
            {
                var dialog = SaveDialogs().FirstOrDefault(x =>
                {
                    try
                    {
                        var hwnd = x.Current.NativeWindowHandle;
                        return !initial.Contains(hwnd) ||
                               VerifyFolder(x) ||
                               VerifyFilename(x);
                    }
                    catch { return false; }
                });
                if (dialog == null)
                {
                    Thread.Sleep(250);
                    continue;
                }

                var hwnd = dialog.Current.NativeWindowHandle;
                uint ownerProcessId = 0;
                NativeWindow.GetWindowThreadProcessId(
                    new IntPtr(hwnd),
                    out ownerProcessId);
                State(StateFound,
                    "hwnd=" + hwnd +
                    " owner_pid=" + ownerProcessId +
                    " title='" + dialog.Current.Name + "'");
                Log("SAVE_DIALOG_OWNER hwnd=" + hwnd +
                    " pid=" + ownerProcessId);
                State(StateVerifying, "controlType='" + dialog.Current.ControlType.ProgrammaticName +
                      "' class='" + dialog.Current.ClassName + "'");
                if (!VerifyFolder(dialog))
                    throw new InvalidOperationException("folder could not be confirmed");
                State(StateFolder, "result=true");
                if (!VerifyFilename(dialog))
                    throw new InvalidOperationException("filename could not be confirmed");
                State(StateFilename, "result=true");
                State(StateButton);
                var saveButton = FindButton(dialog, SaveNames);
                if (saveButton == null)
                    throw new InvalidOperationException("enabled Save button not found");
                if (!InvokeSave(dialog, saveButton))
                    throw new InvalidOperationException("SaveButton.Invoke failed");
                State(StateClosed);
                if (!WaitDialogClosed(dialog, TimeSpan.FromSeconds(10)))
                    throw new InvalidOperationException("SAVE_INVOKE_NO_CLOSE");
                State(StateOutput, "expected='" + _expectedPath + "'");

                var outputDeadline = DateTime.UtcNow.AddSeconds(timeout);
                while (DateTime.UtcNow < outputDeadline)
                {
                    if (VerifyOutput())
                    {
                        State(StateVerifyOutput, "result=true");
                        State(StateSuccess, "path='" + _expectedPath + "'");
                        return 0;
                    }
                    LogWrongLocation();
                    Thread.Sleep(500);
                }
                throw new FileNotFoundException("target output was not created", _expectedPath);
            }

            throw new TimeoutException("Save As dialog timeout");
        }
        catch (Exception ex)
        {
            State(StateFailed, "reason='" + ex.Message.Replace("'", "\"") + "'");
            Log(ex.ToString());
            return 2;
        }
    }
}
