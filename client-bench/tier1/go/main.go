// Go arm of the Tier-1 client bench (CASE-MATRIX.md, amendment of 2 November 2026).
//
// Each case runs the SDK's own authorization flow the way an application does: an
// mcp.Client connecting over StreamableClientTransport with an auth.AuthorizationCodeHandler,
// every option left at its default. The driver plays the user agent and nothing else: the
// AuthorizationCodeFetcher follows the authorization URL one hop and returns what the redirect
// carried (code, state and iss). It decides no outcome; score.py reads the server's log.
package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"io/fs"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"runtime/debug"
	"strings"
	"time"

	"github.com/modelcontextprotocol/go-sdk/auth"
	"github.com/modelcontextprotocol/go-sdk/mcp"
	"github.com/modelcontextprotocol/go-sdk/oauthex"
)

const (
	bench     = "http://127.0.0.1:8765"
	requested = bench + "/tenant-a/mcp"
	redirect  = "http://127.0.0.1:8766/callback"
	module    = "github.com/modelcontextprotocol/go-sdk"
)

var noRedirect = &http.Client{
	CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
	Timeout:       10 * time.Second,
}

func benchJSON(method, path string, out any) {
	req, _ := http.NewRequest(method, bench+path, nil)
	res, err := http.DefaultClient.Do(req)
	if err != nil {
		panic(err)
	}
	defer res.Body.Close()
	if out != nil {
		if err := json.NewDecoder(res.Body).Decode(out); err != nil {
			panic(err)
		}
	}
}

func moduleVersion() string {
	if info, ok := debug.ReadBuildInfo(); ok {
		for _, d := range info.Deps {
			if d.Path == module {
				return strings.TrimPrefix(d.Version, "v")
			}
		}
	}
	return "unknown"
}

// sourceOccurrences counts the module's non-test Go files naming needle (the C1 count).
func sourceOccurrences(needle string) int {
	root := filepath.Join(os.Getenv("GOPATH"), "pkg", "mod", module+"@v"+moduleVersion())
	n := 0
	_ = filepath.WalkDir(root, func(p string, d fs.DirEntry, err error) error {
		if err != nil || d.IsDir() || !strings.HasSuffix(p, ".go") || strings.HasSuffix(p, "_test.go") {
			return nil
		}
		if b, err := os.ReadFile(p); err == nil && strings.Contains(string(b), needle) {
			n++
		}
		return nil
	})
	return n
}

type outcome struct {
	authorizationURL string
	callback         string
	err              error
}

func runCase() outcome {
	var o outcome
	fetcher := func(ctx context.Context, args *auth.AuthorizationArgs) (*auth.AuthorizationResult, error) {
		// The user agent: request the authorization URL and keep the redirect it answers with.
		o.authorizationURL = args.URL
		res, err := noRedirect.Get(args.URL)
		if err != nil {
			return nil, err
		}
		io.Copy(io.Discard, res.Body)
		res.Body.Close()
		o.callback = res.Header.Get("Location")
		if o.callback == "" {
			return nil, errors.New("the authorization endpoint answered with no redirect")
		}
		u, err := url.Parse(o.callback)
		if err != nil {
			return nil, err
		}
		q := u.Query()
		return &auth.AuthorizationResult{Code: q.Get("code"), State: q.Get("state"), Iss: q.Get("iss")}, nil
	}
	handler, err := auth.NewAuthorizationCodeHandler(&auth.AuthorizationCodeHandlerConfig{
		DynamicClientRegistrationConfig: &auth.DynamicClientRegistrationConfig{
			Metadata: &oauthex.ClientRegistrationMetadata{
				ClientName: "tier1-bench", RedirectURIs: []string{redirect},
				GrantTypes: []string{"authorization_code", "refresh_token"}, ResponseTypes: []string{"code"},
				TokenEndpointAuthMethod: "none", Scope: "mcp",
			},
		},
		RedirectURL:              redirect,
		AuthorizationCodeFetcher: fetcher,
	})
	if err != nil {
		o.err = err
		return o
	}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	client := mcp.NewClient(&mcp.Implementation{Name: "tier1-bench", Version: "0"}, nil)
	session, err := client.Connect(ctx, &mcp.StreamableClientTransport{Endpoint: requested, OAuthHandler: handler}, nil)
	if session != nil {
		session.Close()
	}
	o.err = err
	return o
}

func main() {
	version := moduleVersion()
	c1 := sourceOccurrences("protected_resources")
	var cases []string
	benchJSON("GET", "/__cases", &cases)
	enc := json.NewEncoder(os.Stdout)
	for _, id := range cases {
		benchJSON("POST", "/__case?id="+id, nil)
		o := runCase()
		var log struct {
			Log []any `json:"log"`
		}
		benchJSON("GET", "/__log", &log)
		var errText *string
		if o.err != nil {
			s := fmt.Sprintf("%T: %v", o.err, o.err)
			if len(s) > 300 {
				s = s[:300]
			}
			errText = &s
		}
		rec := map[string]any{
			"implementation": "go-sdk", "package": module, "version": version, "level": "flow",
			"case_id": id, "requested_identifier": requested,
			"callback_channel":  "AuthorizationResult (code, state, iss)",
			"authorization_url": o.authorizationURL, "callback": o.callback,
			"connect_error": errText, "finish_error": nil,
			"log": log.Log, "run_at": time.Now().UTC().Format(time.RFC3339Nano),
		}
		if id == "C1" {
			rec["c1_source_occurrences"] = c1
		}
		enc.Encode(rec)
	}
}
