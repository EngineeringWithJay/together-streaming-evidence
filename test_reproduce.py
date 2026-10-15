# SPDX-License-Identifier: Apache-2.0
import json
import os
import socket
import subprocess
import sys
import unittest
from unittest.mock import patch

import reproduce as r


class EvidenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.report = r.run()
        cls.control, cls.eof, cls.null = cls.report["cases"]

    def test_fixture_boundary_and_partial_arguments(self):
        control = (r.ROOT / "fixtures/control.sse").read_bytes()
        eof = (r.ROOT / "fixtures/clean-eof.sse").read_bytes()
        self.assertEqual(eof, control[:control.index(b"\n\n") + 2])
        event = json.loads(eof.removeprefix(b"data: "))
        partial = event["choices"][0]["delta"]["tool_calls"][0]["function"]["arguments"]
        self.assertEqual(partial, '{"value":')
        self.assertEqual(self.eof["chunks"][0]["choices"][0]["delta"]["tool_calls"][0]["function"]["arguments"], partial)
        with self.assertRaises(json.JSONDecodeError):
            json.loads(partial)

    def test_control_and_clean_eof_are_not_equivalent(self):
        self.assertEqual([c["sdk_yielded_chunks"] for c in self.report["cases"]], [3, 1, 3])
        self.assertTrue(self.control["fixture_done_present"])
        self.assertFalse(self.eof["fixture_done_present"])
        self.assertEqual(self.control["chunks"][-1]["choices"][0]["finish_reason"], "tool_calls")
        self.assertIsNone(self.eof["chunks"][-1]["choices"][0]["finish_reason"])
        parts = [c["choices"][0]["delta"].get("tool_calls", []) for c in self.control["chunks"]]
        self.assertEqual(json.loads("".join(t["function"]["arguments"] for ts in parts for t in ts)), {"value": 1})
        for case in self.report["cases"]:
            self.assertEqual(case["iteration_outcome"], "iteration exhausted without exception")
            self.assertIsNone(case["iteration_exception"])
            self.assertTrue(case["all_responses_closed"])
            self.assertTrue(case["response_closed_on_iteration_exit"])
            self.assertTrue(case["http_client_closed"])
            self.assertEqual(case["mock_requests"], 1)

    def test_missing_null_usage_and_delta_presence(self):
        control = (r.ROOT / "fixtures/control.sse").read_bytes()
        self.assertEqual((r.ROOT / "fixtures/null-usage.sse").read_bytes(), control.replace(
            b'{"prompt_tokens":7,"completion_tokens":3,"total_tokens":10}', b'null'))
        absent, null = self.eof["chunks"][0], self.null["chunks"][-1]
        self.assertEqual((absent["usage_state"], null["usage_state"]), ("absent", "null"))
        self.assertIsNone(absent["usage"])
        self.assertIsNone(null["usage"])
        self.assertNotIn("usage", absent["fields_set"])
        self.assertIn("usage", null["fields_set"])
        self.assertEqual(self.control["chunks"][-1]["usage"], {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10})
        self.assertEqual(null["choices"][0]["delta_fields_set"], [])
        self.assertIn("content", absent["choices"][0]["delta_fields_set"])

    def test_environment_sentinels_never_reach_transport_or_report(self):
        marker = "AMBIENT_FAKE_SECRET_SENTINEL"
        ambient = {k: marker for k in ("TOGETHER_API_KEY", "TOGETHER_PROJECT_ID", "TOGETHER_BASE_URL", "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "SSL_CERT_FILE", "UNRELATED_SECRET")}
        ambient.update(TOGETHER_CUSTOM_HEADERS="X-Ambient: " + marker + "\nAuthorization: " + marker, TOGETHER_LOG="debug")
        seen = []

        def inspect(request):
            # Boolean assertions only: a failure must not print intercepted headers.
            self.assertTrue(all(marker not in k and marker not in v for k, v in request.headers.items()))
            self.assertTrue(marker not in str(request.url) and marker.encode() not in request.content)
            self.assertTrue(request.headers.get("authorization") == "Bearer synthetic-not-a-key")
            self.assertTrue(dict(os.environ) == {"LANG": "C", "LC_ALL": "C", "TZ": "UTC"})
            seen.append(True)

        with patch.dict(os.environ, ambient):
            report = r.run(inspect)
            self.assertTrue(os.environ["TOGETHER_API_KEY"] == marker)
        self.assertNotIn(marker, r.encode(report))
        self.assertEqual(len(seen), 3)
        self.assertEqual(report["network_attempts"], 0)

    def test_real_socket_and_dns_calls_are_denied(self):
        with r.offline() as attempts:
            with socket.socket() as sock:
                with self.assertRaises(r.NetworkDenied):
                    sock.connect(("127.0.0.1", 9))
            with self.assertRaises(r.NetworkDenied):
                socket.create_connection(("127.0.0.1", 9))
            with self.assertRaises(r.NetworkDenied):
                socket.getaddrinfo("synthetic.invalid", 443)
            self.assertEqual(len(attempts), 3)

    def test_fingerprint_mismatch_is_rejected(self):
        with r.offline(), patch.object(r, "digest", return_value="wrong"):
            with self.assertRaisesRegex(r.PacketError, "^code_fingerprint_mismatch$"):
                r.provenance()

    def test_deterministic_report_matches_saved_observation(self):
        command = [sys.executable, "-B", str(r.ROOT / "reproduce.py")]
        first, second = [subprocess.run(command, check=True, capture_output=True) for _ in range(2)]
        self.assertEqual(first.stderr, b"")
        self.assertEqual(second.stderr, b"")
        first, second = first.stdout, second.stdout
        self.assertEqual(first, second)
        self.assertEqual(first, (r.ROOT / "observed.json").read_bytes())

    def test_environment_pins_match_installed_distributions(self):
        def canonical(name):
            return name.lower().replace("_", "-")
        lines = (r.ROOT / "requirements.txt").read_text().splitlines()
        pins = dict(line.split("==") for line in lines if "==" in line)
        expected = {canonical(name): version for name, version in pins.items()}
        expected["together"] = "2.41.0"
        actual = {name: r.metadata.version(name) for name in expected}
        self.assertEqual(expected, actual)


if __name__ == "__main__":
    unittest.main()
