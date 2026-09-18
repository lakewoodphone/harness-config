def test_sanitize_tool_call_out_of_workspace() -> None:
    from app.services.ai_gateway import _sanitize_tool_call

    # A read outside every approved root is blocked, not rewritten to a shell command.
    tc_out = {
        "id": "call_out",
        "type": "function",
        "function": {
            "name": "read_file",
            "arguments": '{"filePath": "C:\\\\Users\\\\ezabz\\\\Downloads\\\\file.txt", "startLine": 10, "endLine": 20}'
        }
    }

    sanitized = _sanitize_tool_call(tc_out)
    fn = sanitized["function"]
    assert fn["name"] == "gateway_blocked_tool_call"

    args = json.loads(fn["arguments"])
    assert args["blocked_tool"] == "read_file"
    assert "outside approved roots" in args["reason"]
    assert "Downloads" in args["reason"]

    # A read inside the repo root is preserved as-is.
    tc_in = {
        "id": "call_in",
        "type": "function",
        "function": {
            "name": "read_file",
            "arguments": '{"filePath": "README.md"}'
        }
    }
    assert _sanitize_tool_call(tc_in) == tc_in

    # ── Everything below approves a WINDOWS root by config, and what that means is
    # host-dependent (2026-09-15). On Windows the approved root is absolute and a Windows path
    # under it is readable, which is what this test asserted. On POSIX that root normalises to
    # `<repo>/C:\Users\...`, a Windows path normalises to a sibling of it, and the guard fails
    # CLOSED -- it does not pretend an uninterpretable path is inside the workspace (L1520).
    # Both outcomes are asserted rather than skipped, so the test means something on either host.
    windows_root_is_usable = os.name == "nt"

    settings = FakeSettings(
        {},
        ai_gateway_approved_file_roots_json=json.dumps(["C:\\Users\\ezabz\\Downloads"]),
    )
    if windows_root_is_usable:
        assert _sanitize_tool_call(tc_out, settings=settings) == tc_out
    else:
        still_blocked = _sanitize_tool_call(tc_out, settings=settings)
        assert still_blocked["function"]["name"] == "gateway_blocked_tool_call"
        blocked_reason = json.loads(still_blocked["function"]["arguments"])["reason"]
        assert "outside approved roots" in blocked_reason, blocked_reason

    # A VS Code chat transcript is denied by default even when its directory is approved, and
    # this one holds on both hosts.
    tc_sensitive = {
        "id": "call_sensitive",
        "type": "function",
        "function": {
            "name": "read_file",
            "arguments": json.dumps({
                "filePath": "C:\\Users\\ezabz\\AppData\\Roaming\\Code\\User\\workspaceStorage\\abc\\GitHub.copilot-chat\\transcripts\\session.jsonl",
            }),
        },
    }
    sensitive_settings = FakeSettings(
        {},
        ai_gateway_approved_file_roots_json=json.dumps(["C:\\Users\\ezabz\\AppData"]),
    )
    blocked_sensitive = _sanitize_tool_call(tc_sensitive, settings=sensitive_settings)
    sensitive_args = json.loads(blocked_sensitive["function"]["arguments"])
    assert blocked_sensitive["function"]["name"] == "gateway_blocked_tool_call"
    assert "AppData" in sensitive_args["reason"]
    assert "denied by default" in sensitive_args["reason"]

    # A MUTATING call into a root approved only for reading is blocked. On Windows the reason
    # names the write roots; on POSIX the read-root check reports first, because a Windows path
    # is under neither. Either way it is blocked, which is the property that matters.
    tc_write_extra_root = {
        "id": "call_write_extra_root",
        "type": "function",
        "function": {
            "name": "create_file",
            "arguments": json.dumps({
                "filePath": "C:\\Users\\ezabz\\Downloads\\file.txt",
                "content": "hello",
            }),
        },
    }
    blocked_write = _sanitize_tool_call(tc_write_extra_root, settings=settings)
    blocked_args = json.loads(blocked_write["function"]["arguments"])
    assert blocked_write["function"]["name"] == "gateway_blocked_tool_call"
    assert (
        "outside approved write roots" in blocked_args["reason"]
        or "outside approved roots" in blocked_args["reason"]
    ), blocked_args["reason"]

    # A write root approved as well: usable on Windows, still refused on POSIX for the reason
    # above -- the root is not a root this host can resolve.
    write_settings = FakeSettings(
        {},
        ai_gateway_approved_file_roots_json=json.dumps(["C:\\Users\\ezabz\\Downloads"]),
        ai_gateway_approved_file_write_roots_json=json.dumps(["C:\\Users\\ezabz\\Downloads"]),
    )
    if windows_root_is_usable:
        assert _sanitize_tool_call(tc_write_extra_root, settings=write_settings) == tc_write_extra_root
    else:
        refused_write = _sanitize_tool_call(tc_write_extra_root, settings=write_settings)
        assert refused_write["function"]["name"] == "gateway_blocked_tool_call"

