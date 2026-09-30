using Playnite.SDK.Models;
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Security.Cryptography;
using System.Text;

namespace FolderGameManager
{
    internal sealed class FolderGameScanner
    {
        private static readonly HashSet<string> ExcludedExecutableNames = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "config.exe", "configuration.exe", "settings.exe", "setup.exe", "install.exe",
            "uninstall.exe", "uninstaller.exe", "unitycrashhandler.exe", "unitycrashhandler64.exe",
            "crashreporter.exe", "crashpad_handler.exe", "dxsetup.exe"
        };

        private static readonly string[] ExcludedExecutableFragments =
        {
            "unins", "setup", "patch", "translator", "crashhandler", "crashreport", "reportcrash",
            "vcredist", "redistributable", "benchmark", "eac_launcher", "easyanticheat",
            "ue4prereq", "ue5prereq"
        };

        private static readonly HashSet<string> InfrastructureFolders = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "bin", "bin32", "bin64", "binary", "binaries", "build", "game", "windows",
            "win32", "win64", "x86", "x64", "windowsnoeditor"
        };

        private readonly FolderGameManagerSettings settings;
        private readonly HashSet<string> excludedTypes;

        public FolderGameScanner(FolderGameManagerSettings settings)
        {
            this.settings = settings;
            excludedTypes = new HashSet<string>(
                SplitList(settings.ExcludedTypeFolders),
                StringComparer.OrdinalIgnoreCase);
        }

        public IEnumerable<GameMetadata> Scan()
        {
            var root = Path.GetFullPath(settings.RootDirectory.Trim());

            foreach (var typeDirectory in SafeDirectories(root)
                .Where(directory => !excludedTypes.Contains(directory.Name))
                .OrderBy(directory => directory.Name, StringComparer.CurrentCultureIgnoreCase))
            {
                foreach (var entryDirectory in SafeDirectories(typeDirectory.FullName)
                    .OrderBy(directory => directory.Name, StringComparer.CurrentCultureIgnoreCase))
                {
                    foreach (var game in ScanEntry(root, typeDirectory.Name, entryDirectory))
                    {
                        yield return game;
                    }
                }
            }
        }

        private IEnumerable<GameMetadata> ScanEntry(string root, string typeName, DirectoryInfo entryDirectory)
        {
            var executableDirectories = FindExecutableDirectories(entryDirectory, 0)
                .OrderBy(item => item.Directory.FullName.Length)
                .ToList();

            if (executableDirectories.Count == 0)
            {
                yield break;
            }

            var selected = new List<ExecutableDirectory>();
            foreach (var candidate in executableDirectories)
            {
                if (selected.Any(existing => IsSameOrParent(existing.Directory.FullName, candidate.Directory.FullName)))
                {
                    continue;
                }

                selected.Add(candidate);
            }

            foreach (var item in selected)
            {
                var installDirectory = CollapseInfrastructurePath(entryDirectory, item.Directory);
                yield return CreateGame(root, typeName, installDirectory, item.Executables);
            }
        }

        private IEnumerable<ExecutableDirectory> FindExecutableDirectories(DirectoryInfo directory, int depth)
        {
            var executables = SafeFiles(directory.FullName, "*.exe")
                .Where(IsUsableExecutable)
                .OrderByDescending(file => ScoreExecutable(file, directory.Name))
                .ThenBy(file => file.Name, StringComparer.CurrentCultureIgnoreCase)
                .ToList();

            if (executables.Count > 0)
            {
                yield return new ExecutableDirectory(directory, executables);
                yield break;
            }

            if (depth >= settings.MaximumScanDepth)
            {
                yield break;
            }

            foreach (var child in SafeDirectories(directory.FullName))
            {
                foreach (var result in FindExecutableDirectories(child, depth + 1))
                {
                    yield return result;
                }
            }
        }

        private GameMetadata CreateGame(
            string root,
            string typeName,
            DirectoryInfo installDirectory,
            IList<FileInfo> executables)
        {
            var orderedExecutables = executables
                .OrderByDescending(file => ScoreExecutable(file, installDirectory.Name))
                .ThenBy(file => file.Name, StringComparer.CurrentCultureIgnoreCase)
                .ToList();
            var primary = orderedExecutables[0];
            var actions = new List<GameAction>();
            var actionExecutables = settings.AddAllExecutableActions
                ? orderedExecutables
                : orderedExecutables.Take(1).ToList();

            for (var index = 0; index < actionExecutables.Count; index++)
            {
                var executable = actionExecutables[index];
                actions.Add(new GameAction
                {
                    Name = executable.Name,
                    Type = GameActionType.File,
                    Path = executable.FullName,
                    WorkingDir = executable.DirectoryName,
                    IsPlayAction = index == 0
                });
            }

            var relativePath = MakeRelativePath(root, installDirectory.FullName);
            return new GameMetadata
            {
                Name = installDirectory.Name,
                GameId = CreateStableId(relativePath),
                IsInstalled = true,
                InstallDirectory = installDirectory.FullName,
                GameActions = actions,
                Icon = new MetadataFile(primary.FullName),
                Categories = new HashSet<MetadataProperty>
                {
                    new MetadataNameProperty(typeName)
                },
                CompletionStatus = new MetadataNameProperty("未玩"),
                Tags = new HashSet<MetadataProperty>
                {
                    new MetadataNameProperty("未备份")
                },
                Version = primary.Name
            };
        }

        private static bool IsUsableExecutable(FileInfo file)
        {
            if (ExcludedExecutableNames.Contains(file.Name))
            {
                return false;
            }

            var normalized = file.Name.ToLowerInvariant();
            return !ExcludedExecutableFragments.Any(fragment => normalized.Contains(fragment));
        }

        private static int ScoreExecutable(FileInfo file, string folderName)
        {
            var executableName = Path.GetFileNameWithoutExtension(file.Name);
            var normalizedExecutable = NormalizeName(executableName);
            var normalizedFolder = NormalizeName(folderName);
            var score = 0;

            if (normalizedExecutable == normalizedFolder)
            {
                score += 100;
            }
            else if (normalizedFolder.Contains(normalizedExecutable) || normalizedExecutable.Contains(normalizedFolder))
            {
                score += 60;
            }

            if (normalizedExecutable == "game" || normalizedExecutable == "start")
            {
                score += 35;
            }
            else if (normalizedExecutable.Contains("launcher"))
            {
                score += 10;
            }

            try
            {
                score += (int)Math.Min(20, file.Length / (1024 * 1024));
            }
            catch
            {
                // File metadata can be unavailable while scanning removable or protected locations.
            }

            return score;
        }

        private static DirectoryInfo CollapseInfrastructurePath(DirectoryInfo entry, DirectoryInfo executableDirectory)
        {
            var current = executableDirectory;
            while (current.Parent != null
                && !PathsEqual(current.FullName, entry.FullName)
                && InfrastructureFolders.Contains(current.Name))
            {
                current = current.Parent;
            }

            return PathsEqual(current.FullName, entry.FullName) ? entry : current;
        }

        private static IEnumerable<DirectoryInfo> SafeDirectories(string path)
        {
            try
            {
                return new DirectoryInfo(path).EnumerateDirectories()
                    .Where(directory => (directory.Attributes & FileAttributes.ReparsePoint) == 0)
                    .ToList();
            }
            catch
            {
                return Enumerable.Empty<DirectoryInfo>();
            }
        }

        private static IEnumerable<FileInfo> SafeFiles(string path, string pattern)
        {
            try
            {
                return new DirectoryInfo(path).EnumerateFiles(pattern, SearchOption.TopDirectoryOnly).ToList();
            }
            catch
            {
                return Enumerable.Empty<FileInfo>();
            }
        }

        private static IEnumerable<string> SplitList(string value)
        {
            return (value ?? string.Empty)
                .Split(new[] { ';', '；', '\r', '\n' }, StringSplitOptions.RemoveEmptyEntries)
                .Select(item => item.Trim())
                .Where(item => item.Length > 0);
        }

        private static string NormalizeName(string value)
        {
            return new string((value ?? string.Empty)
                .Where(char.IsLetterOrDigit)
                .Select(char.ToLowerInvariant)
                .ToArray());
        }

        private static bool IsSameOrParent(string parent, string child)
        {
            var normalizedParent = Path.GetFullPath(parent).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
            var normalizedChild = Path.GetFullPath(child).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar;
            return normalizedChild.StartsWith(normalizedParent, StringComparison.OrdinalIgnoreCase);
        }

        private static bool PathsEqual(string left, string right)
        {
            return string.Equals(
                Path.GetFullPath(left).TrimEnd(Path.DirectorySeparatorChar),
                Path.GetFullPath(right).TrimEnd(Path.DirectorySeparatorChar),
                StringComparison.OrdinalIgnoreCase);
        }

        private static string MakeRelativePath(string root, string path)
        {
            var rootUri = new Uri(Path.GetFullPath(root).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar);
            var pathUri = new Uri(Path.GetFullPath(path).TrimEnd(Path.DirectorySeparatorChar) + Path.DirectorySeparatorChar);
            return Uri.UnescapeDataString(rootUri.MakeRelativeUri(pathUri).ToString())
                .Replace('/', Path.DirectorySeparatorChar)
                .TrimEnd(Path.DirectorySeparatorChar);
        }

        private static string CreateStableId(string relativePath)
        {
            using (var sha256 = SHA256.Create())
            {
                var bytes = sha256.ComputeHash(Encoding.UTF8.GetBytes(relativePath.ToLowerInvariant()));
                return BitConverter.ToString(bytes).Replace("-", string.Empty).ToLowerInvariant();
            }
        }

        private sealed class ExecutableDirectory
        {
            public DirectoryInfo Directory { get; private set; }
            public IList<FileInfo> Executables { get; private set; }

            public ExecutableDirectory(DirectoryInfo directory, IList<FileInfo> executables)
            {
                Directory = directory;
                Executables = executables;
            }
        }
    }
}
