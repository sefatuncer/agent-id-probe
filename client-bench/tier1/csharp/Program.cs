// C# arm of the Tier-1 client bench (CASE-MATRIX.md, amendment of 2 November 2026).
//
// Each case runs the SDK's own authorization flow the way an application does: McpClient over
// HttpClientTransport with ClientOAuthOptions, every option the bench does not need left at its
// default, and a connect that meets a 401. The driver plays the user agent and nothing else:
// AuthorizationCallbackHandler follows the authorization URL one hop and returns what the
// redirect carried (code, state and iss). It decides no outcome; score.py reads the server's log.
using System.Reflection;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Web;
using ModelContextProtocol.Authentication;
using ModelContextProtocol.Client;

const string Bench = "http://127.0.0.1:8765";
const string Requested = Bench + "/tenant-a/mcp";
var redirect = new Uri("http://127.0.0.1:8766/callback");
var benchHttp = new HttpClient();
var userAgent = new HttpClient(new HttpClientHandler { AllowAutoRedirect = false }) { Timeout = TimeSpan.FromSeconds(10) };

var version = typeof(McpClient).Assembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion?.Split('+')[0] ?? "unknown";

// C1: shipped assemblies naming the field, searched as UTF-8 and as UTF-16 (.NET user strings).
int SourceOccurrences(string needle)
{
    var root = Environment.GetEnvironmentVariable("NUGET_PACKAGES") ?? "/w/.nuget";
    var utf8 = Encoding.UTF8.GetBytes(needle);
    var utf16 = Encoding.Unicode.GetBytes(needle);
    var n = 0;
    foreach (var pkg in new[] { "modelcontextprotocol.core", "modelcontextprotocol" })
    {
        var dir = Path.Combine(root, pkg, version, "lib", "net10.0");
        if (!Directory.Exists(dir)) continue;
        foreach (var f in Directory.GetFiles(dir, "*.dll"))
        {
            var bytes = File.ReadAllBytes(f);
            if (bytes.AsSpan().IndexOf(utf8) >= 0 || bytes.AsSpan().IndexOf(utf16) >= 0) n++;
        }
    }
    return n;
}

var c1 = SourceOccurrences("protected_resources");
var cases = JsonSerializer.Deserialize<string[]>(await benchHttp.GetStringAsync($"{Bench}/__cases"))!;
var stdout = Console.Out;

foreach (var caseId in cases)
{
    await benchHttp.PostAsync($"{Bench}/__case?id={caseId}", null);
    string? authorizationUrl = null, callback = null, error = null;

    var oauth = new ClientOAuthOptions
    {
        RedirectUri = redirect,
        DynamicClientRegistration = new DynamicClientRegistrationOptions { ClientName = "tier1-bench" },
        AuthorizationCallbackHandler = async (context, ct) =>
        {
            // The user agent: request the authorization URL and keep the redirect it answers with.
            authorizationUrl = context.AuthorizationUri.ToString();
            using var res = await userAgent.GetAsync(context.AuthorizationUri, ct);
            callback = res.Headers.Location?.ToString();
            if (callback is null) throw new InvalidOperationException("the authorization endpoint answered with no redirect");
            var q = HttpUtility.ParseQueryString(new Uri(callback).Query);
            return new AuthorizationResult { Code = q["code"], State = q["state"], Iss = q["iss"] };
        },
    };

    try
    {
        using var cts = new CancellationTokenSource(TimeSpan.FromSeconds(20));
        var transport = new HttpClientTransport(new HttpClientTransportOptions { Endpoint = new Uri(Requested), OAuth = oauth }, loggerFactory: null);
        await using var client = await McpClient.CreateAsync(transport, cancellationToken: cts.Token);
    }
    catch (Exception e)
    {
        var inner = e;
        while (inner is AggregateException { InnerException: not null } ae) inner = ae.InnerException!;
        error = $"{inner.GetType().Name}: {inner.Message}";
        if (error.Length > 300) error = error[..300];
    }

    var log = JsonNode.Parse(await benchHttp.GetStringAsync($"{Bench}/__log"))!["log"];
    var record = new JsonObject
    {
        ["implementation"] = "csharp-sdk",
        ["package"] = "ModelContextProtocol",
        ["version"] = version,
        ["level"] = "flow",
        ["case_id"] = caseId,
        ["requested_identifier"] = Requested,
        ["callback_channel"] = "AuthorizationCallbackHandler returning AuthorizationResult (code, state, iss)",
        ["authorization_url"] = authorizationUrl,
        ["callback"] = callback,
        ["connect_error"] = error,
        ["finish_error"] = null,
        ["log"] = log?.DeepClone(),
        ["run_at"] = DateTime.UtcNow.ToString("o"),
    };
    if (caseId == "C1") record["c1_source_occurrences"] = c1;
    stdout.WriteLine(record.ToJsonString());
}
