# SPDX-License-Identifier: Apache-2.0
"""Small offline public-client reproduction; stdout is deterministic JSON."""
import hashlib
import importlib
import importlib.metadata as metadata
import json
import logging
import os
from pathlib import Path
import platform
import socket
import sys
from contextlib import ExitStack, contextmanager
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
MODEL = "synthetic-tool-model"
CASES = ("control", "clean-eof", "null-usage")


class PacketError(Exception):
    pass


class NetworkDenied(RuntimeError):
    pass


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encode(value):
    return json.dumps(value, sort_keys=True, indent=2) + "\n"


@contextmanager
def offline():
    """Process-global guard for this single-threaded script, not a sandbox."""
    attempts = []

    def deny(*args, **kwargs):
        attempts.append("blocked")  # Never retain addresses, headers or credentials.
        raise NetworkDenied("network_disabled")

    old_level = logging.root.manager.disable
    with ExitStack() as stack:
        stack.enter_context(patch.dict(os.environ, {"LANG": "C", "LC_ALL": "C", "TZ": "UTC"}, clear=True))
        for name in ("create_connection", "getaddrinfo", "gethostbyname", "gethostbyname_ex", "gethostbyaddr", "getnameinfo"):
            stack.enter_context(patch.object(socket, name, deny))
        for name in ("connect", "connect_ex", "sendto", "sendmsg"):
            if hasattr(socket.socket, name):
                stack.enter_context(patch.object(socket.socket, name, deny))
        logging.disable(logging.CRITICAL)
        try:
            yield attempts
        finally:
            logging.disable(old_level)


def provenance():
    expected = json.loads((ROOT / "source-manifest.json").read_text())
    dist = metadata.distribution("together")
    if dist.version != expected["sdk_version"]:
        raise PacketError("sdk_version_mismatch")
    actual = {}
    for relative, fingerprint in expected["sha256_relative_to_together"].items():
        installed = Path(dist.locate_file("together/" + relative)).resolve()
        actual[relative] = digest(installed.read_bytes())
        if actual[relative] != fingerprint:
            raise PacketError("code_fingerprint_mismatch")
        module = importlib.import_module("together." + relative[:-3].replace("/", "."))
        if Path(module.__file__).resolve() != installed:
            raise PacketError("import_origin_mismatch")
    return {"reference_commit": expected["reference_commit"],
            "import_origin": "installed distribution; selected module origins verified",
            "source_sha256": actual, "python": platform.python_version(),
            "packages": {name: metadata.version(name) for name in ("together", "httpx", "pydantic")}}


def observe(case, inspect_request=None):
    import httpx
    from together import Together

    fixture = (ROOT / "fixtures" / (case + ".sse")).read_bytes()
    requests, responses, chunks = [], [], []

    def handler(request):
        if request.url.host != "synthetic.invalid" or request.method != "POST":
            raise PacketError("unexpected_request")
        requests.append(digest(request.content))
        if inspect_request is not None:
            inspect_request(request)  # Tests assert in memory; nothing is logged.
        response = httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  stream=httpx.ByteStream(fixture))
        responses.append(response)
        return response

    iteration_exception = None
    with httpx.Client(transport=httpx.MockTransport(handler), trust_env=False) as http:
        with Together(api_key="synthetic-not-a-key", project_id="synthetic-project",
                      base_url="https://synthetic.invalid/v1", http_client=http, max_retries=0) as client:
            stream = client.chat.completions.create(
                model=MODEL, stream=True,
                messages=[{"role": "user", "content": "Synthetic fixture request."}],
                tools=[{"type": "function", "function": {"name": "record_value", "parameters": {
                    "type": "object", "properties": {"value": {"type": "integer"}}, "required": ["value"]}}}])
            with stream:
                try:
                    for chunk in stream:
                        usage = chunk.usage
                        chunks.append({"fields_set": sorted(chunk.model_fields_set),
                                       "usage_state": "absent" if "usage" not in chunk.model_fields_set else "null" if usage is None else "value",
                                       "usage": None if usage is None else usage.model_dump(exclude_unset=True),
                                       "choices": [{"finish_reason": c.finish_reason,
                                                    "delta_fields_set": sorted(c.delta.model_fields_set),
                                                    "delta": c.delta.model_dump(exclude_unset=True)} for c in chunk.choices]})
                except Exception as error:
                    iteration_exception = type(error).__name__  # No raw exception text.
                closed_on_iteration_exit = stream.response.is_closed
    return {"case": case, "fixture_sha256": digest(fixture), "fixture_bytes": len(fixture),
            "fixture_done_present": b"data: [DONE]\n\n" in fixture,
            "fixture_ends_at_event_boundary": fixture.endswith(b"\n\n"),
            "request_body_sha256": requests, "mock_requests": len(requests),
            "sdk_yielded_chunks": len(chunks), "chunks": chunks,
            "iteration_exception": iteration_exception,
            "iteration_outcome": "iteration exhausted without exception" if iteration_exception is None else "iteration raised",
            "response_closed_on_iteration_exit": closed_on_iteration_exit,
            "all_responses_closed": bool(responses) and all(r.is_closed for r in responses),
            "http_client_closed": http.is_closed}


def run(inspect_request=None):
    with offline() as attempts:
        source = provenance()  # Fingerprint and imports happen under denial.
        control = (ROOT / "fixtures/control.sse").read_bytes()
        eof = (ROOT / "fixtures/clean-eof.sse").read_bytes()
        prefix = len(eof) < len(control) and control.startswith(eof) and eof.endswith(b"\n\n")
        if not prefix:
            raise PacketError("invalid_eof_fixture_boundary")
        cases = [observe(case, inspect_request) for case in CASES]
        if attempts:
            raise PacketError("unexpected_network_attempt")
        return {"schema": 1, "synthetic_model": MODEL, "provenance": source,
                "network_attempts": len(attempts), "eof_is_control_prefix_at_event_boundary": prefix,
                "usage_numbers_are_fixture_data": True, "cases": cases}


if __name__ == "__main__":
    try:
        print(encode(run()), end="")
    except PacketError as error:
        print("offline packet rejected: " + str(error), file=sys.stderr)
        sys.exit(1)
    except Exception:
        print("offline packet failed; check pinned environment and packet integrity", file=sys.stderr)
        sys.exit(1)
