"""Windows job owns all worker descendants, including after a worker crash."""
import ctypes,os,time
from ctypes import wintypes as w

class WorkerTree:
    def __init__(self):
        self.handle=None;self.error=''
        if os.name!='nt':self.error='当前平台无法确认后台进程组';return
        try:
            class Limits(ctypes.Structure):
                _fields_=[('process_time',ctypes.c_longlong),('job_time',ctypes.c_longlong),('flags',w.DWORD),('min_ws',ctypes.c_size_t),('max_ws',ctypes.c_size_t),('active_limit',w.DWORD),('affinity',ctypes.c_size_t),('priority',w.DWORD),('scheduling',w.DWORD)]
            class IO(ctypes.Structure):
                _fields_=[(n,ctypes.c_ulonglong) for n in ('read_ops','write_ops','other_ops','read_bytes','write_bytes','other_bytes')]
            class Extended(ctypes.Structure):
                _fields_=[('basic',Limits),('io',IO),('process_memory',ctypes.c_size_t),('job_memory',ctypes.c_size_t),('peak_process',ctypes.c_size_t),('peak_job',ctypes.c_size_t)]
            self.api=ctypes.WinDLL('kernel32',use_last_error=True)
            self.api.CreateJobObjectW.argtypes=[ctypes.c_void_p,w.LPCWSTR];self.api.CreateJobObjectW.restype=w.HANDLE
            self.api.SetInformationJobObject.argtypes=[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD];self.api.SetInformationJobObject.restype=w.BOOL
            self.api.AssignProcessToJobObject.argtypes=[w.HANDLE,w.HANDLE];self.api.AssignProcessToJobObject.restype=w.BOOL
            self.api.TerminateJobObject.argtypes=[w.HANDLE,w.UINT];self.api.TerminateJobObject.restype=w.BOOL
            self.api.QueryInformationJobObject.argtypes=[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD,ctypes.c_void_p];self.api.QueryInformationJobObject.restype=w.BOOL
            self.api.CloseHandle.argtypes=[w.HANDLE];self.api.CloseHandle.restype=w.BOOL
            handle=self.api.CreateJobObjectW(None,None)
            if not handle:raise ctypes.WinError(ctypes.get_last_error())
            self.handle=handle;limits=Extended();limits.basic.flags=0x2000
            if not self.api.SetInformationJobObject(handle,9,ctypes.byref(limits),ctypes.sizeof(limits)):raise ctypes.WinError(ctypes.get_last_error())
        except OSError as error:
            self.error=str(error);self.close()
    @property
    def creation_flags(self):return 4 if self.handle else 0  # CREATE_SUSPENDED
    def attach_and_resume(self,process):
        if not self.handle:return
        try:
            if not self.api.AssignProcessToJobObject(self.handle,w.HANDLE(int(process._handle))):raise ctypes.WinError(ctypes.get_last_error())
            native=ctypes.WinDLL('ntdll');native.NtResumeProcess.argtypes=[w.HANDLE];native.NtResumeProcess.restype=w.LONG
            status=native.NtResumeProcess(w.HANDLE(int(process._handle)))
            if status<0:raise OSError('无法启动已隔离后台进程：'+str(status))
        except Exception:
            process.kill();process.wait();self.close();raise
    def stop_and_confirm(self):
        if not self.handle:return False
        class Accounting(ctypes.Structure):
            _fields_=[(n,ctypes.c_longlong) for n in ('total_user','total_kernel','period_user','period_kernel')]+[(n,w.DWORD) for n in ('page_faults','total_processes','active_processes','terminated_processes')]
        if not self.api.TerminateJobObject(self.handle,1):self.error=str(ctypes.WinError(ctypes.get_last_error()));return False
        deadline=time.monotonic()+5
        while time.monotonic()<deadline:
            info=Accounting()
            if not self.api.QueryInformationJobObject(self.handle,1,ctypes.byref(info),ctypes.sizeof(info),None):return False
            if info.active_processes==0:return True
            time.sleep(.02)
        self.error='后台子进程未确认全部退出';return False
    def close(self):
        if self.handle:self.api.CloseHandle(self.handle);self.handle=None
