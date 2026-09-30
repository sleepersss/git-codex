using Playnite.SDK;
using Playnite.SDK.Models;
using Playnite.SDK.Plugins;
using System;
using System.Collections.Generic;
using System.Linq;

namespace FolderGameManager
{
    public class FolderGameManager : LibraryPlugin
    {
        private static readonly ILogger logger = LogManager.GetLogger();
        private readonly FolderGameManagerSettings settings;

        private static readonly Guid PluginId = Guid.Parse("e6726d85-ec1c-4f64-894c-e050346af700");

        public override Guid Id { get { return PluginId; } }
        public override string Name { get { return "文件夹游戏管理器"; } }

        public FolderGameManager(IPlayniteAPI api) : base(api)
        {
            settings = new FolderGameManagerSettings();
            Properties = new LibraryPluginProperties
            {
                HasSettings = false
            };
        }

        public override IEnumerable<GameMetadata> GetGames(LibraryGetGamesArgs args)
        {
            try
            {
                var scanner = new FolderGameScanner(settings);
                var games = scanner.Scan().ToList();
                logger.Info(string.Format("文件夹游戏管理器扫描完成，共发现 {0} 个游戏。", games.Count));
                return games;
            }
            catch (Exception exception)
            {
                logger.Error(exception, "文件夹游戏管理器扫描失败。");
                PlayniteApi.Dialogs.ShowErrorMessage(
                    string.Format("扫描游戏目录时发生错误：{0}", exception.Message),
                    "文件夹游戏管理器");
                return Enumerable.Empty<GameMetadata>();
            }
        }
    }
}
