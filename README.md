# Offline seed evidence for Together issue #454

Target: [Together Python SDK issue #454](https://github.com/togethercomputer/together-py/issues/454).

Issue #454's need is a **versioned, diffable report**. This small, freely reusable
synthetic seed packet reduces fixture preparation for a first slice of that work:
three SSE cases, pinned inputs and a deterministic observed report. It complements
the issue author's planned harness rather than introducing another framework.
The packet supplies data for that proposal; it does not define the scope of the
author's broader harness or imply upstream acceptance.

## Set up and run

From this packet directory, with `uv` and Git available, create a fresh isolated
environment and install the pinned dependencies:

```sh
uv venv --python 3.12.13 .venv
uv pip install --python .venv/bin/python -r requirements.txt
```

**Setup needs network access** to fetch Python if needed, the pinned SDK and its
dependencies. An independent verifier ran these exact setup commands in a newly
created environment on 15 October 2026; installation and dependency checks passed.
Available package caches were used; this was not an empty-cache installation test.

Then replay the fixtures and run the existing tests **offline**:

```sh
.venv/bin/python -B reproduce.py
.venv/bin/python -B -m unittest -v test_reproduce
```

The first command prints JSON only. The second compares two independently run
reports byte-for-byte and against `observed.json`. No server, inference, API key,
provider account, GPU, test framework, or SDK mock-server is needed for replay;
neither replay command installs anything.

The recorded replay was tested on **macOS arm64, CPython 3.12.13**, first in the
development environment and independently in the fresh environment above. No
other platform has been verified.
For an existing environment matching `requirements.txt`, substitute its Python
interpreter for `.venv/bin/python` in the two replay commands.

## Three cases and their interpretation

| Fixture | Framing / finish | SDK observation |
|---|---|---|
| `control.sse` | Completed tool arguments, `tool_calls` finish reason, usage, `[DONE]` | Three yielded chunks |
| `clean-eof.sse` | Literal first-event prefix of control, ending with `\n\n`; partial arguments; no finish reason or `[DONE]` | One yielded chunk; partial arguments preserved |
| `null-usage.sse` | Same completed control, but final usage explicitly `null` | Three yielded chunks; usage field present with value `None` |

All three: **iteration exhausted without exception**. That phrase does not imply
semantic completion. `_streaming.py` consumes `[DONE]` internally; it is not an SDK
chunk. Fixture marker presence is therefore recorded separately from SDK-yielded
chunks, finish reasons, and iteration exceptions. Clean EOF is not a socket reset
or malformed/truncated SSE framing: its one JSON event is complete, but the
*string inside* that event contains incomplete tool arguments (`{"value":`).

The first chunks omit usage. The control's final usage is **fixture data**
(`7`, `3`, `10`), not measured tokens. No absent usage is inferred or replaced by
zero. Missing and explicit-null usage both read as `None`; `model_fields_set`
distinguishes them. This is already documented in the pinned SDK's README,
“How to tell whether `None` means `null` or missing” (lines 484–494), and covered
generically in `tests/test_models.py::test_omitted_fields`; it is not a new bug.
The report also preserves `delta` field presence rather than filling defaults.

## Safety and evidence boundaries

Before SDK import/execution, a process-local guard replaces ambient environment
with the fixed allowlist `LANG=C`, `LC_ALL=C`, `TZ=UTC`, disables logging, and
denies socket connect/send-to and DNS entry points. The client has an explicit
fake key, synthetic project, `synthetic.invalid` URL, zero retries, and
`httpx.Client(trust_env=False, transport=httpx.MockTransport(...))`. Only the three
bundled fixtures are replayed. No headers, auth envelopes, ambient values, or raw
exception messages are reported. Tests inject fake ambient key/project/custom
header/proxy sentinels and assert they never reach intercepted requests or JSON.
They also deliberately attempt a socket connection and DNS lookup and verify
denial; case runs record **zero** network attempts independently of handler counts.

This guard temporarily changes process-global state and is for standalone,
single-threaded use, not concurrent embedding or a hostile-code security sandbox.
It is not an OS firewall. SDK stream and client context managers close resources;
the report records response and HTTP-client closure explicitly.

## Provenance and hash definitions

The executed SDK was a **non-editable installed distribution**, built from the
read-only `togethercomputer/together-py` checkout at
`5f22a566d22d135dccfcbb76901bca69bfdf0222` (SDK `2.41.0`), not an import of that
checkout. `source-manifest.json` pins ten relevant SDK files: client, transport,
stream decoder, response/model construction, request transform/resource and chunk
types. Their SHA-256 values were compared directly between checkout and installed
distribution. Every run checks these installed source bytes and verifies each
selected imported module's origin against the installed distribution. A mismatch
fails with a fixed diagnostic, rather than silently reporting a different SDK.
This is a selected-source fingerprint, not a whole-environment attestation.

`observed.json` records Python, SDK, httpx and Pydantic versions, commit and source
hashes, fixture hashes, synthetic model, yielded data, and resource closure.
`requirements.txt` pins all 25 distributions in the tested environment, including
Together. The independent installation confirmed the non-editable VCS commit and
all ten selected source fingerprints. This is not wheel/build-tool hash locking.
No package source or machine-specific install path is embedded in this packet.

* `fixture_sha256`: SHA-256 of exact `.sse` file bytes, including final newlines.
* `request_body_sha256`: SHA-256 of `httpx.Request.content` bytes observed inside
  MockTransport, after SDK serialization; one digest per request, **not** a hash
  of canonicalized JSON or an HTTP envelope. Headers/auth are excluded.
* Report encoding: sorted JSON keys, two-space indent, final LF, no timestamps,
  hostnames, or absolute local paths. Reformatting changes report-byte hashes.

Out of scope / missing evidence: async behavior, socket resets, incomplete SSE
framing, retries, cancellation, real network chunk boundaries, provider billing,
live model behavior, and conformance across models/providers. The SDK's default
permissive response construction is used, not strict schema validation. Tools are
described and arguments observed; no tool is executed. Passing these checks is
only an observation of this pinned synchronous public client on synthetic bytes.

## Verification receipt

On 15 October 2026, an independent verifier followed the fresh setup and replay
commands above: **8 tests passed**, dependency compatibility passed, and two
separate CLI processes each produced 8,558 JSON bytes with empty stderr. Both
reports matched `observed.json` byte-for-byte. Its SHA-256 is:

```text
a97f01574ec17aea32c19298534e0bb51c2430db73f4640e5af6714995fc0993
```

The independent check also confirmed source/import provenance, fixture semantics,
environment-sentinel isolation, explicit socket/DNS denial tests, zero runtime
network attempts, and resource closure. The source SDK checkout was unchanged.
Implementation was AI-assisted; these statements describe executed checks, not
manual authorship or live-provider conformance.

## Reuse

Original packet code and fixtures: SPDX `Apache-2.0`, offered without charge;
see `LICENSE` for the full terms.
No SDK implementation is copied or modified. The dependency retains its own
Apache-2.0 license and Together attribution. No company affiliation is implied.
The delivery archive contains only the reusable packet files, not internal
handoff drafts, development environments, or private project material.
