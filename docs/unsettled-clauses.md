# Clauses the layered specifications do not jointly settle

Nine entries, each one a decision the instrument had to make because no single document
settles it. They are recorded here as a standalone file so that an entry can be lifted into
a working-group issue or a bis document without extracting it from a paper.

Two things about their provenance matter and are stated rather than left to be inferred.
Seven were raised while writing a check against specification text, before any deployment
was contacted; two arose when the instrument met a case it could not score. They are
therefore an output of *constructing* the instrument rather than of running it, and only
U9 could not have been found by reading the specifications alone.

The channel matters too. IETF errata are for errors in a published RFC. Under-specification
and a gap between two documents are not errata, and the entries below are written for a
working-group issue or a revision draft instead.

| ID | Type | Raised | Clauses | What is unsettled | Reading adopted | What would resolve it |
|---|---|---|---|---|---|---|
| U1 | within a document | run | RFC 9728, Sections 3.1 and 3.3 | The construction that inserts the well-known suffix strips a terminating slash, so a resource identifier cannot be recovered from its metadata URL: two identifiers map to one location | *unspecified* for C12, where the left side is inferred; a violation for C13, where it is observed | Stating which of the two identifiers a client compares against |
| U2 | within a document | reading | RFC 9728, Sections 7.6 and 4 | Selection is declined in a lower-case *should*, and the field supplying the mitigation's second list is OPTIONAL, so the only offered defence depends on a parameter nobody must publish | Descriptive only, with feasibility measured and no penalty | A profile making the field mandatory where a resource enumerates issuers, or a statement that the binding is out of band |
| U3 | across revisions | reading | MCP Authorization 2025-06-18 and 2025-11-25 | The earlier requires the `WWW-Authenticate` header. The later requires that header *or* a well-known URI. A server offering only the URI violates one and conforms to the other, and which applies is not passively observable | Scored under the most permissive revision in the pinned set, so C07 can never fail | A version indicator in a discovery document |
| U4 | across documents | reading | RFC 3986, Section 6; RFC 8414, Section 3.3 | Whether *identical* means URI equivalence or code-point identity, and therefore whether normalisation may run before comparison | Code-point identity after only the equivalences RFC 3986 itself declares (Section 4.4) | One sentence fixing the comparison form |
| U5 | within a document | reading | A2A v0.3.0, Section 5.5.6 | A signed agent identity carries no freshness, expiry or revocation requirement, so a signature valid once is valid indefinitely | Reported as prevalence, no obligation existing to score against | A validity window, or a statement that freshness is the verifier's problem |
| U6 | across documents | reading | RFC 8785; A2A v0.3.0 | Whether members holding default values are canonicalised into a signed payload, which decides whether a signature verifies | *unspecified* for C04 rather than a verification failure | Naming a canonicalisation profile normatively |
| U7 | within a document | reading | MCP Streamable HTTP, protocol-version header | Absent the header and with no other way to identify the version, a server "SHOULD assume protocol version 2025-03-26", so tooling that does not handshake is processed under a revision it did not choose. Sending the header is no fix, as an unsupported value must draw a 400 | Recorded, not scored | Narrowing the default to the transport handshake |
| U8 | within a document | reading | RFC 8414, Section 3.3 | The MUST binds the authorization server, not the resource that named it, so a failure cannot be attributed to the endpoint whose discovery chain broke | Read narrowly at the endpoint level as a broken chain, never as operator non-conformance | Stating who answers for a mismatch reached through delegation |
| U9 | across documents | run | RFC 8414, Sections 2 and 3.3; RFC 3986, Section 2 | A metadata document standing for a *family* of issuers, with a template placeholder, the shape RFC 6570 defines, where the URL should be | *template placeholder*, *unspecified* in both identity checks, attributed to the resource that declared it | A registered member declaring a document tenant-independent and giving the substitution rule normatively |

Generated from the manuscript's Table 10. If the two disagree, the manuscript is the
published record and this file is stale.
