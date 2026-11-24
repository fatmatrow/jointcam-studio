/* JointCam Studio launcher.
 *
 * Hosts the bundled CPython runtime inside this process, so Windows shows
 * "JointCam Studio" with its own icon in Task Manager and on the taskbar, and a
 * pinned taskbar button starts the app correctly.
 *
 * Layout:  <install>\JointCam Studio.exe
 *          <install>\boot.py  (and the rest of the app)
 *          <install>\runtime\python312.dll, python312._pth, Lib\...
 *
 * runtime\python312._pth makes the runtime self-contained: it ignores PYTHONPATH,
 * PYTHONHOME, the registry and the user's site-packages, so another Python on
 * the PC cannot interfere.
 *
 * The launcher deliberately uses no C runtime (built with -nostdlib). Python's
 * Universal CRT is then the only CRT in the process, exactly as with pythonw.exe.
 * A second CRT would initialise the standard handles separately and Python's
 * stream setup fails with "invalid handle".
 */
#define WIN32_LEAN_AND_MEAN
#ifndef UNICODE
#define UNICODE
#endif
#include <windows.h>
#include <shellapi.h>

#define PATH_CHARS 32768

typedef int (*PyMainFunction)(int, wchar_t **);

static wchar_t root[PATH_CHARS], runtime[PATH_CHARS], library[PATH_CHARS], boot[PATH_CHARS];
static wchar_t message[4096];

static void join(wchar_t *target, const wchar_t *base, const wchar_t *tail)
{
    lstrcpynW(target, base, PATH_CHARS);
    int used = lstrlenW(target);
    lstrcpynW(target + used, tail, PATH_CHARS - used);
}

static void report(const wchar_t *text)
{
    DWORD code = GetLastError();
    wchar_t number[16];
    int i = 15;
    number[i] = L'\0';
    do { number[--i] = (wchar_t)(L'0' + code % 10); code /= 10; } while (code && i > 0);
    lstrcpynW(message, text, 4096);
    lstrcatW(message, L"\n\nWindows error ");
    lstrcatW(message, number + i);
    lstrcatW(message, L".\n\nRun the JointCam Studio installer again to repair the installation.");
    MessageBoxW(NULL, message, L"JointCam Studio", MB_ICONERROR | MB_OK);
}

/* Some launchers (stream tools, game overlays) start GUI programs with standard
 * handles that are not valid. Python treats a missing handle as "no console" but
 * stops on an invalid one, so clear any handle Windows cannot identify. */
static void sanitize_std_handles(void)
{
    static const DWORD ids[3] = { STD_INPUT_HANDLE, STD_OUTPUT_HANDLE, STD_ERROR_HANDLE };
    for (int i = 0; i < 3; i++) {
        HANDLE handle = GetStdHandle(ids[i]);
        if (handle == NULL || handle == INVALID_HANDLE_VALUE) continue;
        SetLastError(NO_ERROR);
        if (GetFileType(handle) == FILE_TYPE_UNKNOWN && GetLastError() != NO_ERROR)
            SetStdHandle(ids[i], NULL);
    }
}

static int run(void)
{
    DWORD length = GetModuleFileNameW(NULL, root, PATH_CHARS);
    if (length == 0 || length >= PATH_CHARS) {
        report(L"JointCam Studio could not locate its installation folder.");
        return 1;
    }
    int cut = -1;
    for (int i = 0; root[i]; i++)
        if (root[i] == L'\\') cut = i;
    if (cut < 0) return 1;
    root[cut] = L'\0';

    join(runtime, root, L"\\runtime");
    join(library, runtime, L"\\python312.dll");
    join(boot, root, L"\\boot.py");

    if (GetFileAttributesW(boot) == INVALID_FILE_ATTRIBUTES) {
        report(L"JointCam Studio's program files are missing.");
        return 1;
    }

    sanitize_std_handles();

    /* Python loads extension modules with LOAD_LIBRARY_SEARCH_DEFAULT_DIRS, which
     * includes directories added here. The Visual C++ runtime DLLs shipped in
     * runtime\ then serve every module, even on a PC without the VC++ redistributable. */
    AddDllDirectory(runtime);

    /* Resolve python312.dll's own dependencies (vcruntime140.dll) from runtime\. */
    HMODULE python = LoadLibraryExW(library, NULL, LOAD_WITH_ALTERED_SEARCH_PATH);
    if (python == NULL) {
        report(L"JointCam Studio could not load its Python runtime.");
        return 1;
    }
    PyMainFunction py_main = (PyMainFunction)(void *)GetProcAddress(python, "Py_Main");
    if (py_main == NULL) {
        report(L"JointCam Studio's Python runtime is damaged.");
        return 1;
    }

    int count = 0;
    wchar_t **given = CommandLineToArgvW(GetCommandLineW(), &count);
    if (given == NULL) count = 0;
    wchar_t **argv = (wchar_t **)HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY,
                                           sizeof(wchar_t *) * ((SIZE_T)count + 3));
    if (argv == NULL) return 1;
    int argc = 0;
    argv[argc++] = count > 0 ? given[0] : root;
    argv[argc++] = boot;
    for (int i = 1; i < count; i++) argv[argc++] = given[i];
    argv[argc] = NULL;

    return py_main(argc, argv);
}

/* Entry point without a C runtime. */
void WINAPI start(void)
{
    ExitProcess((UINT)run());
}
