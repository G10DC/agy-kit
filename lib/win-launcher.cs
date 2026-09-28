// agy-kit: launcher nativo per Windows (compilato da install.sh con il csc.exe di .NET Framework).
//
// install.sh lo copia in BIN_DIR come <comando>.exe accanto al wrapper bash <comando>.
// Da PowerShell o cmd, `<comando> ...` avvia questo .exe, che passa l'argv ricevuto da
// Windows al wrapper tramite il bash di Git for Windows, senza ripassare dal parser di
// cmd.exe: & % ^ e le virgolette arrivano intatti (uno shim .cmd con %* li interpreterebbe).
// Il percorso di bash.exe arriva da AgyKitConfig.Bash, generato da install.sh.
using System;
using System.Diagnostics;
using System.IO;
using System.Text;

static class AgyKitLauncher
{
    // Regole di Cygwin/MSYS per la riga di comando: dentro le virgolette una barra
    // rovesciata protegge la barra o la virgoletta che segue. Ogni argomento è sempre tra
    // virgolette, così bash non espande * e ? negli argomenti.
    static string Quote(string a)
    {
        return "\"" + a.Replace("\\", "\\\\").Replace("\"", "\\\"") + "\"";
    }

    static int Main(string[] args)
    {
        string self = Process.GetCurrentProcess().MainModule.FileName;
        string wrapper = Path.Combine(Path.GetDirectoryName(self), Path.GetFileNameWithoutExtension(self));
        if (!File.Exists(wrapper))
        {
            Console.Error.WriteLine("agy-kit: wrapper non trovato: " + wrapper + " (reinstalla con ./install.sh)");
            return 127;
        }
        if (!File.Exists(AgyKitConfig.Bash))
        {
            Console.Error.WriteLine("agy-kit: bash di Git for Windows non trovato: " + AgyKitConfig.Bash + " (reinstalla con ./install.sh)");
            return 127;
        }
        var line = new StringBuilder(Quote(wrapper.Replace('\\', '/')));
        foreach (string a in args)
        {
            line.Append(' ').Append(Quote(a));
        }
        // Ctrl+C arriva a tutti i processi della console: lo gestisce il programma avviato
        // (claude, agy), il launcher resta in attesa del suo codice d'uscita.
        Console.CancelKeyPress += delegate (object sender, ConsoleCancelEventArgs e) { e.Cancel = true; };
        var psi = new ProcessStartInfo(AgyKitConfig.Bash, line.ToString());
        psi.UseShellExecute = false;
        try
        {
            using (Process p = Process.Start(psi))
            {
                p.WaitForExit();
                return p.ExitCode;
            }
        }
        catch (Exception e)
        {
            Console.Error.WriteLine("agy-kit: impossibile avviare " + AgyKitConfig.Bash + ": " + e.Message);
            return 127;
        }
    }
}
