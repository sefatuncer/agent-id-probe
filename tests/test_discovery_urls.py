"""Well-known URL derivation.

Reviewer A flagged the original probe as only trying the root form of the
protected-resource metadata URI. RFC 9728 uses the *path-suffixed* form when the
resource identifier has a path, which is the common case for MCP endpoints mounted at
/mcp. Probing only the root form manufactures failures for correctly configured
servers and inflates the headline number — a denominator bug that cannot be repaired
after collection, hence these tests.
"""

from agentidprobe.config import as_metadata_candidate_urls, prm_candidate_urls


def test_prm_path_suffixed_form_is_tried_first_when_resource_has_a_path():
    urls = prm_candidate_urls("https://example.org/mcp")
    assert urls[0] == "https://example.org/.well-known/oauth-protected-resource/mcp"
    assert "https://example.org/.well-known/oauth-protected-resource" in urls


def test_prm_wellknown_segment_is_inserted_not_substituted():
    """The path must survive: /a/b becomes /.well-known/...-resource/a/b."""
    urls = prm_candidate_urls("https://example.org/a/b")
    assert urls[0] == "https://example.org/.well-known/oauth-protected-resource/a/b"


def test_prm_root_only_when_resource_has_no_path():
    urls = prm_candidate_urls("https://example.org")
    assert urls == ["https://example.org/.well-known/oauth-protected-resource"]


def test_prm_trailing_slash_does_not_create_a_duplicate_segment():
    urls = prm_candidate_urls("https://example.org/mcp/")
    assert urls[0] == "https://example.org/.well-known/oauth-protected-resource/mcp"


def test_prm_query_string_is_dropped():
    urls = prm_candidate_urls("https://example.org/mcp?session=1")
    assert all("?" not in u for u in urls)


def test_as_metadata_tries_both_rfc8414_and_oidc_forms():
    urls = as_metadata_candidate_urls("https://issuer.example/tenant1")
    assert "https://issuer.example/.well-known/oauth-authorization-server/tenant1" in urls
    assert "https://issuer.example/tenant1/.well-known/openid-configuration" in urls


def test_as_metadata_for_bare_issuer():
    urls = as_metadata_candidate_urls("https://issuer.example")
    assert "https://issuer.example/.well-known/oauth-authorization-server" in urls
    assert "https://issuer.example/.well-known/openid-configuration" in urls
