#!/usr/bin/env python3
"""Offline test suite for label_hook.py. No network, no credentials, no
fixtures from any real notes directory -- every "notes directory" below is a
throwaway temp directory created and destroyed per check.

    python3 tests/test_label_hook.py

Exit 0 only if every check passes.
"""

import io
import json
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import label_hook as lh

PASS = 0
FAIL = 0

SRC_HOOK = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "label_hook.py")


def check(name, fn):
    """Run one check. A check is a function(tmpdir) that raises on failure."""
    global PASS, FAIL
    d = tempfile.mkdtemp(prefix="untrusted-read-test-")
    try:
        fn(d)
        print("  ok    %s" % name)
        PASS += 1
    except Exception as exc:
        print("  FAIL  %s: %s: %s" % (name, type(exc).__name__, exc))
        FAIL += 1
    finally:
        import shutil
        shutil.rmtree(d, ignore_errors=True)


def run_hook(payload, notes_dir=None, argv_dir=None, env_extra=None):
    """Invoke lh.main() in-process with captured stdin/stdout, returning
    (returncode, printed_json_or_None)."""
    old_stdin, old_stdout = sys.stdin, sys.stdout
    old_env = dict(os.environ)
    try:
        if notes_dir is not None:
            os.environ["UNTRUSTED_READ_NOTES_DIR"] = notes_dir
        elif "UNTRUSTED_READ_NOTES_DIR" in os.environ:
            del os.environ["UNTRUSTED_READ_NOTES_DIR"]
        if env_extra:
            os.environ.update(env_extra)

        sys.stdin = io.StringIO(json.dumps(payload) if not isinstance(payload, str) else payload)
        sys.stdout = io.StringIO()
        argv = ["label_hook.py"] + ([argv_dir] if argv_dir else [])
        rc = lh.main(argv)
        out = sys.stdout.getvalue().strip()
    finally:
        sys.stdin, sys.stdout = old_stdin, old_stdout
        os.environ.clear()
        os.environ.update(old_env)
    parsed = json.loads(out) if out else None
    return rc, parsed


# --- _under_dir direct unit checks -----------------------------------------

def t_exact_dir_is_under(d):
    assert lh._under_dir(d, d) is True


def t_nested_file_is_under(d):
    f = os.path.join(d, "note.md")
    open(f, "w").close()
    assert lh._under_dir(f, d) is True


def t_sibling_dir_is_not_under(d):
    other = tempfile.mkdtemp(prefix="untrusted-read-sibling-")
    try:
        assert lh._under_dir(os.path.join(other, "x.md"), d) is False
    finally:
        os.rmdir(other)


def t_dotdot_walkout_excluded(d):
    outside = os.path.join(d, "..", "definitely-outside.md")
    assert lh._under_dir(outside, d) is False


def t_dotdot_walkin_included(d):
    sub = os.path.join(d, "sub")
    os.mkdir(sub)
    inside = os.path.join(sub, "..", "note.md")
    open(os.path.join(d, "note.md"), "w").close()
    assert lh._under_dir(inside, d) is True


# --- the headline promise: symlinks cannot be used to walk in OR out -------

def t_symlink_outside_pointing_in_is_still_flagged(d):
    # The dangerous direction: a symlink that lives OUTSIDE the notes
    # directory but points AT a file INSIDE it. The Read tool follows the
    # symlink and returns real notes-directory bytes, so this MUST be
    # flagged even though the symlink's own path is not textually under d.
    real_note = os.path.join(d, "secret.md")
    with open(real_note, "w") as f:
        f.write("real notes content")

    outside = tempfile.mkdtemp(prefix="untrusted-read-outside-")
    try:
        link = os.path.join(outside, "looks-external.md")
        os.symlink(real_note, link)
        assert not link.startswith(d), "test setup bug: link should be lexically outside d"
        assert lh._under_dir(link, d) is True, \
            "external symlink into the notes dir was NOT flagged -- bypass"
    finally:
        import shutil
        shutil.rmtree(outside, ignore_errors=True)


def t_symlink_inside_pointing_out_is_not_flagged(d):
    # The mirror case, and the reason _under_dir resolves BOTH sides with
    # realpath instead of only the candidate: a symlink that lives INSIDE
    # the notes directory but points to a target OUTSIDE it. The bytes the
    # Read tool returns come from the external target, not from the notes
    # directory, so labeling them "untrusted notes data" would be wrong --
    # this is not a bypass to close, it is the correct, symmetric behavior
    # of resolving by real content origin rather than by lexical path.
    outside = tempfile.mkdtemp(prefix="untrusted-read-target-")
    try:
        target = os.path.join(outside, "elsewhere.md")
        open(target, "w").close()
        link = os.path.join(d, "points-out.md")
        os.symlink(target, link)
        assert lh._under_dir(link, d) is False, \
            "a symlink pointing OUTSIDE the notes dir should not be labeled as notes-dir content"
    finally:
        import shutil
        shutil.rmtree(outside, ignore_errors=True)


def t_suite_detects_a_vulnerable_abspath_only_check(d):
    # Meta-test: prove the symlink check above actually discriminates.
    # A "vulnerable" stand-in that uses abspath (lexical only, no symlink
    # resolution) -- the shape of the ORIGINAL, unfixed behavior this
    # package's design note flags as a defect -- must MISS the external
    # symlink case that the real _under_dir catches.
    def vulnerable_under_dir(p, base):
        if not p or not base:
            return False
        ap = os.path.abspath(os.path.expanduser(p))
        ab = os.path.abspath(os.path.expanduser(base))
        return ap == ab or ap.startswith(ab + os.sep)

    real_note = os.path.join(d, "secret.md")
    with open(real_note, "w") as f:
        f.write("real notes content")
    outside = tempfile.mkdtemp(prefix="untrusted-read-outside2-")
    try:
        link = os.path.join(outside, "looks-external.md")
        os.symlink(real_note, link)

        assert vulnerable_under_dir(link, d) is False, \
            "sanity: the vulnerable check should MISS this case"
        assert lh._under_dir(link, d) is True, \
            "the shipped check should CATCH this case"
    finally:
        import shutil
        shutil.rmtree(outside, ignore_errors=True)


# --- full PostToolUse pipeline ----------------------------------------------

def t_read_under_notes_dir_gets_banner(d):
    f = os.path.join(d, "note.md")
    open(f, "w").close()
    rc, out = run_hook({"tool_input": {"file_path": f}, "cwd": "/somewhere/else"}, notes_dir=d)
    assert rc == 0
    assert out is not None, "expected a banner, got no output"
    assert out["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    assert "UNTRUSTED NOTE DATA" in out["hookSpecificOutput"]["additionalContext"]


def t_read_outside_notes_dir_silent(d):
    other = tempfile.mkdtemp(prefix="untrusted-read-other-")
    try:
        f = os.path.join(other, "note.md")
        open(f, "w").close()
        rc, out = run_hook({"tool_input": {"file_path": f}, "cwd": other}, notes_dir=d)
        assert rc == 0
        assert out is None, "expected silence for a non-notes-dir read"
    finally:
        import shutil
        shutil.rmtree(other, ignore_errors=True)


def t_grep_with_no_path_uses_cwd(d):
    rc, out = run_hook({"tool_input": {}, "cwd": d}, notes_dir=d)
    assert out is not None, "grep with cwd under notes dir should be flagged"


def t_grep_with_explicit_path_field(d):
    sub = os.path.join(d, "sub")
    os.mkdir(sub)
    rc, out = run_hook({"tool_input": {"path": sub}, "cwd": "/tmp"}, notes_dir=d)
    assert out is not None


def t_argv_override_takes_precedence_over_env(d):
    f = os.path.join(d, "note.md")
    open(f, "w").close()
    # Set env to some OTHER (non-matching) dir; pass the real dir via argv.
    other = tempfile.mkdtemp(prefix="untrusted-read-envdir-")
    try:
        rc, out = run_hook({"tool_input": {"file_path": f}, "cwd": "/tmp"},
                            notes_dir=other, argv_dir=d)
        assert out is not None, "argv-supplied notes dir should take effect over env"
    finally:
        os.rmdir(other)


def t_not_configured_is_a_silent_noop(d):
    f = os.path.join(d, "note.md")
    open(f, "w").close()
    rc, out = run_hook({"tool_input": {"file_path": f}, "cwd": "/tmp"}, notes_dir=None)
    assert rc == 0
    assert out is None, "with no NOTES_DIR configured, hook must stay silent even on a real hit"


def t_malformed_json_fails_open(d):
    rc, out = run_hook("not valid json {{{", notes_dir=d)
    assert rc == 0
    assert out is None


def t_missing_tool_input_fails_open(d):
    rc, out = run_hook({"cwd": "/tmp/not/notes"}, notes_dir=d)
    assert rc == 0
    assert out is None


# --- run the actual script as a subprocess, including through a symlink ---

def t_script_runs_as_subprocess(d):
    f = os.path.join(d, "note.md")
    open(f, "w").close()
    env = dict(os.environ)
    env["UNTRUSTED_READ_NOTES_DIR"] = d
    p = subprocess.run(
        [sys.executable, SRC_HOOK],
        input=json.dumps({"tool_input": {"file_path": f}, "cwd": "/tmp"}),
        capture_output=True, text=True, env=env,
    )
    assert p.returncode == 0, "stderr: %s" % p.stderr
    out = json.loads(p.stdout.strip())
    assert "UNTRUSTED NOTE DATA" in out["hookSpecificOutput"]["additionalContext"]


def t_script_runs_via_symlink(d):
    # Same class of regression guard as scrub.py: run the real file through
    # a differently-named symlink and confirm it still does its job instead
    # of silently no-op'ing.
    f = os.path.join(d, "note.md")
    open(f, "w").close()
    env = dict(os.environ)
    env["UNTRUSTED_READ_NOTES_DIR"] = d
    with tempfile.TemporaryDirectory() as linkdir:
        link = os.path.join(linkdir, "some-other-name.py")
        os.symlink(os.path.abspath(SRC_HOOK), link)
        p = subprocess.run(
            [sys.executable, link],
            input=json.dumps({"tool_input": {"file_path": f}, "cwd": "/tmp"}),
            capture_output=True, text=True, env=env,
        )
        assert p.returncode == 0, "stderr: %s" % p.stderr
        assert p.stdout.strip() != "", "hook printed NOTHING when run through a symlink"
        out = json.loads(p.stdout.strip())
        assert "UNTRUSTED NOTE DATA" in out["hookSpecificOutput"]["additionalContext"]


CHECKS = [
    ("the notes dir itself is 'under' the notes dir", t_exact_dir_is_under),
    ("a file nested inside the notes dir is under it", t_nested_file_is_under),
    ("a sibling directory is not under the notes dir", t_sibling_dir_is_not_under),
    ("'..' cannot walk a path out of the notes dir", t_dotdot_walkout_excluded),
    ("'..' that lands back inside is still counted as inside", t_dotdot_walkin_included),
    ("an external symlink INTO the notes dir is flagged (bypass closed)", t_symlink_outside_pointing_in_is_still_flagged),
    ("a symlink inside the notes dir pointing OUT is not flagged (correct, symmetric)", t_symlink_inside_pointing_out_is_not_flagged),
    ("this suite detects an abspath-only (vulnerable) implementation (meta-test)", t_suite_detects_a_vulnerable_abspath_only_check),
    ("a Read under the notes dir gets the banner", t_read_under_notes_dir_gets_banner),
    ("a Read outside the notes dir is silent", t_read_outside_notes_dir_silent),
    ("a Grep with no path field falls back to cwd", t_grep_with_no_path_uses_cwd),
    ("a Grep with an explicit path field is checked", t_grep_with_explicit_path_field),
    ("an argv-supplied notes dir overrides the environment", t_argv_override_takes_precedence_over_env),
    ("with no NOTES_DIR configured, the hook is a silent no-op", t_not_configured_is_a_silent_noop),
    ("malformed JSON on stdin fails open", t_malformed_json_fails_open),
    ("missing tool_input fails open", t_missing_tool_input_fails_open),
    ("the script runs standalone via subprocess + stdin", t_script_runs_as_subprocess),
    ("the script runs correctly when invoked through a symlink", t_script_runs_via_symlink),
]


def main():
    print("label_hook.py: %d offline checks" % len(CHECKS))
    for name, fn in CHECKS:
        check(name, fn)
    print("")
    print("%d passed, %d failed" % (PASS, FAIL))
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
