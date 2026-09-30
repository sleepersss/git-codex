namespace FolderGameManager
{
    internal sealed class FolderGameManagerSettings
    {
        public string RootDirectory { get; private set; }
        public string ExcludedTypeFolders { get; private set; }
        public int MaximumScanDepth { get; private set; }
        public bool AddAllExecutableActions { get; private set; }

        public FolderGameManagerSettings()
        {
            RootDirectory = @"E:\1_Game\some games";
            ExcludedTypeFolders = "game manage";
            MaximumScanDepth = 6;
            AddAllExecutableActions = true;
        }
    }
}
