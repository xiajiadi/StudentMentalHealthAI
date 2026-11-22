using System;
using System.Diagnostics;
using System.IO;
using System.IO.Compression;
using System.Reflection;
using System.Security.Cryptography;

internal static class Setup
{
    private const string UvUrl = "https://github.com/astral-sh/uv/releases/download/0.13.9/uv-x86_64-pc-windows-msvc.zip";
    private const string UvSha = "EDD61F7F5728A56CC62455386661860BDFC7BAB65872F39B0C25BDCC1D8E1BEB";

    private static string Quote(string value)
    {
        return "\"" + value.Replace("\"", "\\\"") + "\"";
    }

    private static void Run(string exe, string arguments, string directory)
    {
        var start = new ProcessStartInfo(exe, arguments) {
            WorkingDirectory = directory,
            UseShellExecute = false
        };
        using (var process = Process.Start(start))
        {
            process.WaitForExit();
            if (process.ExitCode != 0)
                throw new InvalidOperationException(Path.GetFileName(exe) + " exited with " + process.ExitCode);
        }
    }

    private static void UnpackApplication(string root, string app)
    {
        if (Directory.Exists(app)) return;
        string staging = Path.Combine(root, "app-staging-" + Guid.NewGuid().ToString("N"));
        string package = staging + ".zip";
        using (Stream input = Assembly.GetExecutingAssembly().GetManifestResourceStream("psynova-source.zip"))
        using (var output = new FileStream(package, FileMode.CreateNew))
        {
            if (input == null) throw new InvalidOperationException("Application package is missing");
            input.CopyTo(output);
        }
        ZipFile.ExtractToDirectory(package, staging);
        Directory.Move(staging, app);
        File.Delete(package);
    }

    private static string PrepareUv(string root)
    {
        string bootstrap = Path.Combine(root, "bootstrap");
        Directory.CreateDirectory(bootstrap);
        string file = Path.Combine(bootstrap, "uv-0.13.9.zip");
        if (!File.Exists(file))
        {
            string curl = Path.Combine(Environment.SystemDirectory, "curl.exe");
            Run(curl, "--fail --location --proto =https --proto-redir =https --retry 2 --connect-timeout 12 --output " +
                Quote(file + ".download") + " " + Quote(UvUrl), bootstrap);
            File.Move(file + ".download", file);
        }
        using (var sha = SHA256.Create())
        using (var input = File.OpenRead(file))
        {
            string actual = BitConverter.ToString(sha.ComputeHash(input)).Replace("-", "");
            if (!String.Equals(actual, UvSha, StringComparison.Ordinal))
                throw new InvalidOperationException("uv download checksum mismatch");
        }
        string folder = Path.Combine(bootstrap, "uv-0.13.9");
        string program = Path.Combine(folder, "uv.exe");
        if (!File.Exists(program)) ZipFile.ExtractToDirectory(file, folder);
        return program;
    }

    public static int Main(string[] args)
    {
        Console.OutputEncoding = System.Text.Encoding.UTF8;
        bool unattended = false;
        bool prepareQwen = false;
        foreach (string arg in args)
        {
            if (arg == "--unattended" && !unattended) unattended = true;
            else if (arg == "--prepare-qwen" && !prepareQwen) prepareQwen = true;
            else if (arg == "--help")
            {
                Console.WriteLine("PsyNova School Setup [--unattended] [--prepare-qwen]");
                return 0;
            }
            else return 2;
        }
        if (!Environment.Is64BitOperatingSystem ||
            !String.Equals(Environment.GetEnvironmentVariable("PROCESSOR_ARCHITECTURE"), "AMD64", StringComparison.OrdinalIgnoreCase))
            return 2;
        string root = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
            "PsyNova", "school-v2-preview");
        try
        {
            Directory.CreateDirectory(root);
            for (var path = new DirectoryInfo(root); path != null; path = path.Parent)
                if ((path.Attributes & FileAttributes.ReparsePoint) != 0)
                    throw new InvalidOperationException("Installation cannot use a redirected directory");
            using (var installLock = new FileStream(Path.Combine(root, "setup.lock"), FileMode.OpenOrCreate, FileAccess.ReadWrite, FileShare.None))
            {
                Console.WriteLine("PsyNova 2.0 学校空库预览");
                Console.WriteLine(root);
                string app = Path.Combine(root, "app");
                UnpackApplication(root, app);
                string uv = PrepareUv(root);
                Environment.SetEnvironmentVariable("UV_PYTHON_INSTALL_DIR", Path.Combine(root, "python"));
                Environment.SetEnvironmentVariable("UV_CACHE_DIR", Path.Combine(root, "uv-cache"));
                Run(uv, "run --no-project --managed-python --python 3.12.13 " +
                    Quote(Path.Combine(app, "13_deployment", "windows-school", "bootstrap.py")) +
                    " --uv " + Quote(uv) +
                    (unattended ? " --no-browser" : "") +
                    (prepareQwen ? " --prepare-qwen" : ""), app);
            }
            if (!unattended)
            {
                Console.WriteLine("按回车关闭窗口");
                Console.ReadLine();
            }
            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine(error.Message);
            Console.Error.WriteLine("可重新运行安装程序。已创建的学校数据会保留");
            if (!unattended) Console.ReadLine();
            return 1;
        }
    }
}
