# Ruby arm of the Tier-1 client bench (CASE-MATRIX.md, amendment of 2 November 2026).
#
# Each case runs the SDK's own authorization flow the way an application does: an MCP::Client
# over MCP::Client::HTTP with an MCP::Client::OAuth::Provider, every option at its default, and
# a connect that meets a 401. The driver plays the user agent and nothing else: the redirect
# handler follows the authorization URL one hop, and the callback handler returns what the
# redirect carried as [code, state, iss], always three elements so that an absent iss reads as
# absent rather than as "not passed". It decides no outcome; score.py reads the server's log.
#
# Usage (inside the container sharing the bench server's network namespace):
#   GEM_HOME=/w/gems GEM_PATH=/w/gems ruby driver.rb > ../raw/ruby.jsonl

require "json"
require "net/http"
require "time"
require "timeout"
require "uri"
require "mcp"

BENCH = "http://127.0.0.1:8765"
REQUESTED = "#{BENCH}/tenant-a/mcp"
REDIRECT = "http://127.0.0.1:8766/callback"
CASE_TIMEOUT_S = 20

def bench(path, method = :get)
  uri = URI("#{BENCH}#{path}")
  res = Net::HTTP.start(uri.host, uri.port) do |http|
    method == :post ? http.post(uri.request_uri, "") : http.get(uri.request_uri)
  end
  JSON.parse(res.body)
end

# Files of the installed gem naming `needle` (the C1 count).
def source_occurrences(needle)
  dir = Gem::Specification.find_by_name("mcp").gem_dir
  Dir.glob(File.join(dir, "lib", "**", "*.rb")).count { |p| File.read(p).include?(needle) }
end

def run_case
  seen = { authorization_url: nil, callback: nil }
  redirect_handler = lambda do |url|
    # The user agent: request the authorization URL and keep the redirect it answers with.
    seen[:authorization_url] = url.to_s
    seen[:callback] = Net::HTTP.get_response(URI(url.to_s))["location"]
  end
  callback_handler = lambda do
    raise "the authorization endpoint answered with no redirect" unless seen[:callback]

    query = URI.decode_www_form(URI(seen[:callback]).query || "").to_h
    [query["code"], query["state"], query["iss"]]
  end
  provider = MCP::Client::OAuth::Provider.new(
    client_metadata: {
      client_name: "tier1-bench", redirect_uris: [REDIRECT],
      grant_types: ["authorization_code", "refresh_token"], response_types: ["code"],
      token_endpoint_auth_method: "none", scope: "mcp",
    },
    redirect_uri: REDIRECT,
    redirect_handler: redirect_handler,
    callback_handler: callback_handler,
  )
  error = nil
  begin
    Timeout.timeout(CASE_TIMEOUT_S) do
      transport = MCP::Client::HTTP.new(url: REQUESTED, oauth: provider)
      MCP::Client.new(transport: transport).connect
    end
  rescue StandardError, Timeout::Error => e
    error = "#{e.class}: #{e.message}"[0, 300]
  end
  seen.merge(error: error)
end

version = Gem::Specification.find_by_name("mcp").version.to_s
c1 = source_occurrences("protected_resources")
$stdout.sync = true
bench("/__cases").each do |case_id|
  bench("/__case?id=#{case_id}", :post)
  result = run_case
  log = bench("/__log")["log"]
  record = {
    implementation: "ruby-sdk", package: "mcp", version: version, level: "flow",
    case_id: case_id, requested_identifier: REQUESTED,
    callback_channel: "callback_handler returning [code, state, iss]",
    authorization_url: result[:authorization_url], callback: result[:callback],
    connect_error: result[:error], finish_error: nil,
    log: log, run_at: Time.now.utc.iso8601(6),
  }
  record[:c1_source_occurrences] = c1 if case_id == "C1"
  puts JSON.generate(record)
end
