#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shobjidl.h>
#include <objbase.h>
#include <strsafe.h>
#include <tlhelp32.h>

#include <atomic>
#include <cstdarg>
#include <cstring>
#include <vector>
#include <string>

namespace {

using CoCreateInstanceFn = HRESULT(WINAPI*)(
    REFCLSID,
    LPUNKNOWN,
    DWORD,
    REFIID,
    LPVOID*);

constexpr CLSID kFileSaveDialogClsid =
    {0xC0B4E2F3, 0xBA21, 0x4773,
     {0x8D, 0xBA, 0x33, 0x5E, 0xC9, 0x46, 0xEB, 0x8B}};

// Keep the hook state process-local and one-shot.
std::atomic<bool> g_installed{false};
struct IatPatch {
    void** slot = nullptr;
    void* original = nullptr;
};
std::vector<IatPatch> g_patches;
CoCreateInstanceFn g_originalCoCreateInstance = nullptr;
std::wstring g_outputDir;
std::wstring g_fileName;
HANDLE g_logFile = INVALID_HANDLE_VALUE;
constexpr wchar_t kConfigPath[] =
    L"D:\\7_Video\\20_Wallpaper Engine\\temp\\logs\\native_save_dialog_hook.ini";
void Log(const wchar_t* format, ...);

bool ReadSetting(const wchar_t* environmentName,
                 const wchar_t* iniName,
                 std::wstring* value) {
    wchar_t buffer[4096]{};
    const DWORD environmentLength = GetEnvironmentVariableW(
        environmentName, buffer, ARRAYSIZE(buffer));
    if (environmentLength && environmentLength < ARRAYSIZE(buffer)) {
        value->assign(buffer, environmentLength);
        return true;
    }
    const DWORD iniLength = GetPrivateProfileStringW(
        L"save", iniName, L"", buffer, ARRAYSIZE(buffer), kConfigPath);
    if (iniLength) {
        value->assign(buffer, iniLength);
        return true;
    }
    return false;
}

void Log(const wchar_t* format, ...) {
    if (g_logFile == INVALID_HANDLE_VALUE) {
        return;
    }
    wchar_t buffer[2048]{};
    va_list args;
    va_start(args, format);
    StringCchVPrintfW(buffer, ARRAYSIZE(buffer), format, args);
    va_end(args);
    StringCchCatW(buffer, ARRAYSIZE(buffer), L"\r\n");
    DWORD written = 0;
    WriteFile(g_logFile, buffer,
        static_cast<DWORD>(wcslen(buffer) * sizeof(wchar_t)), &written, nullptr);
}

bool IsFileSaveDialog(REFCLSID clsid) {
    return IsEqualCLSID(clsid, kFileSaveDialogClsid) != FALSE;
}

HRESULT WINAPI HookedCoCreateInstance(
    REFCLSID clsid,
    LPUNKNOWN outer,
    DWORD context,
    REFIID iid,
    LPVOID* result) {
    Log(L"CoCreateInstance intercepted");
    CoCreateInstanceFn original = g_originalCoCreateInstance;
    if (!original) {
        return E_UNEXPECTED;
    }
    const HRESULT hr = original(clsid, outer, context, iid, result);
    const bool clsidMatch = IsFileSaveDialog(clsid);
    const bool iidMatch =
        IsEqualIID(iid, __uuidof(IFileSaveDialog)) ||
        IsEqualIID(iid, __uuidof(IFileDialog));
    Log(L"CoCreateInstance result hr=0x%08lx clsidMatch=%d iidMatch=%d result=%p",
        static_cast<unsigned long>(hr), clsidMatch ? 1 : 0,
        iidMatch ? 1 : 0, result ? *result : nullptr);
    if (FAILED(hr) || !result || !*result || !clsidMatch) {
        return hr;
    }

    if (!iidMatch) {
        return hr;
    }

    IFileDialog* dialog = nullptr;
    auto* returnedUnknown = reinterpret_cast<IUnknown*>(*result);
    const HRESULT queryResult = returnedUnknown->QueryInterface(
        IID_PPV_ARGS(&dialog));
    if (FAILED(queryResult) || !dialog) {
        Log(L"QueryInterface(IFileDialog) hr=0x%08lx",
            static_cast<unsigned long>(queryResult));
        return hr;
    }

    IShellItem* folder = nullptr;
    const HRESULT folderParse = SHCreateItemFromParsingName(
        g_outputDir.c_str(), nullptr, IID_PPV_ARGS(&folder));
    if (SUCCEEDED(folderParse) && folder) {
        const HRESULT setFolder = dialog->SetFolder(folder);
        Log(L"SetFolder path='%ls' hr=0x%08lx",
            g_outputDir.c_str(), static_cast<unsigned long>(setFolder));
        folder->Release();
    } else {
        Log(L"SHParseDisplayName path='%ls' hr=0x%08lx",
            g_outputDir.c_str(), static_cast<unsigned long>(folderParse));
    }

    const HRESULT setName = dialog->SetFileName(g_fileName.c_str());
    Log(L"SetFileName name='%ls' hr=0x%08lx",
        g_fileName.c_str(), static_cast<unsigned long>(setName));
    dialog->Release();
    return hr;
}

bool IsAlreadyPatched(void** slot) {
    for (const auto& patch : g_patches) {
        if (patch.slot == slot) {
            return true;
        }
    }
    return false;
}

bool PatchImportTable(HMODULE module) {
    if (!module) {
        return false;
    }

    auto* base = reinterpret_cast<BYTE*>(module);
    auto* dos = reinterpret_cast<IMAGE_DOS_HEADER*>(base);
    if (dos->e_magic != IMAGE_DOS_SIGNATURE) {
        return false;
    }
    auto* nt = reinterpret_cast<IMAGE_NT_HEADERS*>(base + dos->e_lfanew);
    if (nt->Signature != IMAGE_NT_SIGNATURE) {
        return false;
    }
    const auto& directory = nt->OptionalHeader.DataDirectory[
        IMAGE_DIRECTORY_ENTRY_IMPORT];
    if (!directory.VirtualAddress || !directory.Size) {
        return false;
    }

    bool patched = false;
    auto* imports = reinterpret_cast<IMAGE_IMPORT_DESCRIPTOR*>(
        base + directory.VirtualAddress);
    for (; imports->Name; ++imports) {
        const char* importedName =
            reinterpret_cast<const char*>(base + imports->Name);
        if (_stricmp(importedName, "ole32.dll") != 0 &&
            _stricmp(importedName, "combase.dll") != 0) {
            continue;
        }

        if (!imports->OriginalFirstThunk || !imports->FirstThunk) {
            continue;
        }
        auto* names = reinterpret_cast<IMAGE_THUNK_DATA*>(
            base + imports->OriginalFirstThunk);
        auto* address = reinterpret_cast<IMAGE_THUNK_DATA*>(
            base + imports->FirstThunk);
        for (; names->u1.AddressOfData; ++names, ++address) {
            if (IMAGE_SNAP_BY_ORDINAL(names->u1.Ordinal)) {
                continue;
            }
            auto* importByName = reinterpret_cast<IMAGE_IMPORT_BY_NAME*>(
                base + names->u1.AddressOfData);
            if (strcmp(reinterpret_cast<const char*>(importByName->Name),
                       "CoCreateInstance") != 0) {
                continue;
            }

            void** slot = reinterpret_cast<void**>(&address->u1.Function);
            if (IsAlreadyPatched(slot)) {
                continue;
            }
            void* original = reinterpret_cast<void*>(address->u1.Function);
            if (!original) {
                continue;
            }
            if (!g_originalCoCreateInstance) {
                g_originalCoCreateInstance =
                    reinterpret_cast<CoCreateInstanceFn>(original);
            }
            DWORD oldProtect = 0;
            if (!VirtualProtect(slot, sizeof(void*),
                                PAGE_READWRITE, &oldProtect)) {
                Log(L"IAT protect failed module=%p slot=%p error=%lu",
                    module, slot, GetLastError());
                continue;
            }
            address->u1.Function =
                reinterpret_cast<ULONGLONG>(&HookedCoCreateInstance);
            DWORD ignored = 0;
            VirtualProtect(slot, sizeof(void*), oldProtect, &ignored);
            g_patches.push_back({slot, original});
            patched = true;
            Log(L"IAT patched module=%p imported='%hs' slot=%p original=%p",
                module, importedName, slot, original);
        }
    }
    return patched;
}

bool InstallHook() {
    HANDLE snapshot = CreateToolhelp32Snapshot(
        TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, GetCurrentProcessId());
    if (snapshot == INVALID_HANDLE_VALUE) {
        Log(L"CreateToolhelp32Snapshot failed error=%lu", GetLastError());
        return false;
    }

    MODULEENTRY32W entry{sizeof(entry)};
    bool patched = false;
    if (Module32FirstW(snapshot, &entry)) {
        do {
            patched = PatchImportTable(entry.hModule) || patched;
        } while (Module32NextW(snapshot, &entry));
    }
    CloseHandle(snapshot);
    g_installed.store(!g_patches.empty());
    if (patched) {
        Log(L"IAT scan patched entries=%zu", g_patches.size());
        Log(L"HOOK_READY pid=%lu", GetCurrentProcessId());
    }
    return patched;
}

DWORD WINAPI Worker(void*) {
    if (!ReadSetting(L"CODEX_SAVE_DIALOG_OUTPUT_DIR", L"output_dir",
                     &g_outputDir)) {
        return 0;
    }
    if (!ReadSetting(L"CODEX_SAVE_DIALOG_FILE_NAME", L"file_name",
                     &g_fileName)) {
        return 0;
    }

    wchar_t logPath[MAX_PATH]{};
    const DWORD logLength = GetEnvironmentVariableW(
        L"CODEX_SAVE_DIALOG_LOG", logPath, ARRAYSIZE(logPath));
    if (logLength && logLength < ARRAYSIZE(logPath)) {
        g_logFile = CreateFileW(logPath, FILE_APPEND_DATA,
            FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_ALWAYS,
            FILE_ATTRIBUTE_NORMAL, nullptr);
    } else {
        std::wstring configuredLogPath;
        if (ReadSetting(L"CODEX_SAVE_DIALOG_LOG", L"log_path",
                        &configuredLogPath)) {
            g_logFile = CreateFileW(configuredLogPath.c_str(), FILE_APPEND_DATA,
                FILE_SHARE_READ | FILE_SHARE_WRITE, nullptr, OPEN_ALWAYS,
                FILE_ATTRIBUTE_NORMAL, nullptr);
        }
    }
    if (g_logFile != INVALID_HANDLE_VALUE) {
        Log(L"config source env-or-ini='%ls'", kConfigPath);
    }
    if (g_logFile != INVALID_HANDLE_VALUE) {
        Log(L"hook_process pid=%lu", GetCurrentProcessId());
        Log(L"worker output='%ls' filename='%ls'",
            g_outputDir.c_str(), g_fileName.c_str());
    }
    for (int attempt = 0; attempt < 120; ++attempt) {
        InstallHook();
        Sleep(250);
    }
    return 0;
}

}  // namespace

BOOL APIENTRY DllMain(HMODULE module, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(module);
        HANDLE thread = CreateThread(nullptr, 0, Worker, nullptr, 0, nullptr);
        if (thread) {
            CloseHandle(thread);
        }
    } else if (reason == DLL_PROCESS_DETACH) {
        if (g_installed.load()) {
            for (const auto& patch : g_patches) {
                if (!patch.slot) {
                    continue;
                }
                DWORD oldProtect = 0;
                if (VirtualProtect(patch.slot, sizeof(void*),
                                   PAGE_READWRITE, &oldProtect)) {
                    *patch.slot = patch.original;
                    DWORD ignored = 0;
                    VirtualProtect(patch.slot, sizeof(void*), oldProtect, &ignored);
                }
            }
        }
        if (g_logFile != INVALID_HANDLE_VALUE) {
            CloseHandle(g_logFile);
            g_logFile = INVALID_HANDLE_VALUE;
        }
    }
    return TRUE;
}
