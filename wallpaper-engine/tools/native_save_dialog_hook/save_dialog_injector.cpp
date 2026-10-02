#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <tlhelp32.h>

#include <cstdio>
#include <string>

namespace {

void PrintWin32Error(const wchar_t* stage) {
    fwprintf(stderr, L"%ls failed error=%lu\n", stage, GetLastError());
}

DWORD FindProcessId(const wchar_t* imageName) {
    HANDLE snapshot = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snapshot == INVALID_HANDLE_VALUE) {
        return 0;
    }
    PROCESSENTRY32W entry{sizeof(entry)};
    DWORD result = 0;
    if (Process32FirstW(snapshot, &entry)) {
        do {
            if (_wcsicmp(entry.szExeFile, imageName) == 0) {
                result = entry.th32ProcessID;
                break;
            }
        } while (Process32NextW(snapshot, &entry));
    }
    CloseHandle(snapshot);
    return result;
}

bool Inject(DWORD pid, const std::wstring& dllPath) {
    HANDLE process = OpenProcess(
        PROCESS_CREATE_THREAD | PROCESS_QUERY_INFORMATION |
        PROCESS_VM_OPERATION | PROCESS_VM_WRITE | PROCESS_VM_READ,
        FALSE, pid);
    if (!process) {
        PrintWin32Error(L"OpenProcess");
        return false;
    }

    const SIZE_T bytes = (dllPath.size() + 1) * sizeof(wchar_t);
    void* remote = VirtualAllocEx(process, nullptr, bytes,
        MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if (!remote) {
        PrintWin32Error(L"VirtualAllocEx");
        CloseHandle(process);
        return false;
    }

    bool ok = false;
    SIZE_T written = 0;
    if (WriteProcessMemory(process, remote, dllPath.c_str(), bytes, &written)) {
        auto loadLibrary = reinterpret_cast<LPTHREAD_START_ROUTINE>(
            GetProcAddress(GetModuleHandleW(L"kernel32.dll"), "LoadLibraryW"));
        if (!loadLibrary) {
            PrintWin32Error(L"GetProcAddress(LoadLibraryW)");
        }
        HANDLE thread = CreateRemoteThread(
            process, nullptr, 0, loadLibrary, remote, 0, nullptr);
        if (thread) {
            const DWORD waitResult = WaitForSingleObject(thread, 10000);
            if (waitResult == WAIT_TIMEOUT) {
                fwprintf(stderr, L"WaitForSingleObject timed out\n");
            } else if (waitResult == WAIT_FAILED) {
                PrintWin32Error(L"WaitForSingleObject");
            }
            DWORD exitCode = 0;
            if (!GetExitCodeThread(thread, &exitCode)) {
                PrintWin32Error(L"GetExitCodeThread");
            } else {
                wprintf(L"remote LoadLibrary exit_code=%lu bytes_written=%zu\n",
                    exitCode, written);
                ok = exitCode != 0;
            }
            CloseHandle(thread);
        } else {
            PrintWin32Error(L"CreateRemoteThread");
        }
    } else {
        PrintWin32Error(L"WriteProcessMemory");
    }

    VirtualFreeEx(process, remote, 0, MEM_RELEASE);
    CloseHandle(process);
    return ok;
}

}  // namespace

int wmain(int argc, wchar_t** argv) {
    if (argc != 4) {
        fwprintf(stderr,
            L"usage: save_dialog_injector.exe <pid> <hook.dll> <log>\n");
        return 2;
    }
    const DWORD pid = wcstoul(argv[1], nullptr, 10);
    if (!pid || !Inject(pid, argv[2])) {
        fwprintf(stderr, L"inject failed\n");
        return 1;
    }
    wprintf(L"inject ok pid=%lu dll=%ls log=%ls\n", pid, argv[2], argv[3]);
    return 0;
}
