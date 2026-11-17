# Security policy. untrusted-read

## Posture

untrusted-read is provided as-is, with NO WARRANTY (see LICENSE). Use it as one
control among several, never as a sole guarantee.

If this is a security-oriented tool, the honest ceiling applies: it **reduces,
does not eliminate**, the risk it addresses. Behavioral rules are defense-in-depth
on top of a structural limit, and the structural limit only holds if the host
environment actually enforces it (e.g. actually withholds the tools/permissions
the design assumes are withheld). State that assumption; do not let it read as a
promise the code can't keep.

## Validation status

The offline test suite has been run: 39 checks pass, 0 fail, across two Python
suites (`python3 tests/test_scrub.py`, 21 checks, and
`python3 tests/test_label_hook.py`, 18 checks). They check the scrubber and the
label hook on fixed inputs. They do not cover input shapes I did not think to
write, a live agent session, or how a model behaves when it reads scrubbed
text. There is no separate red-team corpus.

## Reporting a vulnerability

Report privately to https://github.com/justin-rhee. Please do not open a public issue for a
suspected vulnerability. give a reasonable window for a fix first.
