#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shobjidl.h>
#include <objbase.h>

#include <cstdio>

int wmain() {
    if (FAILED(CoInitializeEx(nullptr, COINIT_APARTMENTTHREADED))) {
        return 2;
    }

    Sleep(1500);

    IFileSaveDialog* dialog = nullptr;
    const HRESULT createResult = CoCreateInstance(
        CLSID_FileSaveDialog,
        nullptr,
        CLSCTX_INPROC_SERVER,
        IID_PPV_ARGS(&dialog));
    wprintf(L"CoCreateInstance hr=0x%08lx dialog=%p\n",
        static_cast<unsigned long>(createResult), dialog);
    if (dialog) {
        dialog->Release();
    }
    CoUninitialize();
    return FAILED(createResult) ? 1 : 0;
}
