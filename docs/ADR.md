# Architecture Decision Records (ADRs)

Why this stays a dumb string transform, why its README hides the one thing its tests can't, and two defects testing found that reading the code didn't.

## My agent reads its own notes directory before I've typed anything, and it never asked permission first

The directory is written by a less-privileged process. The agent reading it is the most privileged thing on the machine, and in the places that content gets injected into context automatically, there is no per-read decision by the model at all. An ordinary note carrying forged system or tool-call markers doesn't have to convince anyone of anything. It just has to get parsed. That's why the fix has no model anywhere on its path: a model deciding whether a piece of text is hostile is exactly the thing this tool exists to not depend on. Put a classifier here and the job changes from defeating a string transform, which is hard, to writing persuasive text, which is what the attacker already does for a living.

The result is two small pieces. `scrub.py` escapes every unescaped `<` to `<\` and wraps the result in an explicit BEGIN/END fence, so a forged control tag arrives as inert characters instead of structure. `label_hook.py` fires only when a read resolves under the configured notes directory and appends a banner telling the model to treat what follows as data, not instructions.

## Scrubbing the same note twice used to corrupt it

The original escaper did a naive global replace with no guard against re-escaping its own output, so a second pass accumulated backslashes and visibly mangled the content. Any pipeline stage that runs the scrub twice, nesting, a retry, a second choke point downstream, would have hit this. I proved it against the original before writing anything new: one pass produced the correct escaped form, a second pass doubled every escape, idempotence check false. The fix is a negative-lookahead regex paired with a callable replacement rather than a backslash-laden replacement string, which also removes any ambiguity about how many backslashes come out the other side. A five-times-repeated scrub is now a regression test in the suite.

## A symlink sitting outside the notes directory could still point at a file inside it, and the old check missed that completely

Membership used to be decided by lexical, absolute-path string comparison, which never follows a symlink. A link living outside the notes directory but pointing at a file inside it kept a path string that read as outside, while the actual read followed the link and returned the real protected bytes. Feeding a full PostToolUse payload for exactly that case against the original produced no output at all and exit 0, a silent bypass indistinguishable from an ordinary safe read. The fix resolves symlinks on both the candidate path and the configured directory before the prefix comparison runs. That also fixes the reverse case correctly: a symlink living inside the notes directory that points outward is now left unflagged, since the bytes actually read never originated there. The original flagged that case too, but only by accident, checking the link's location instead of where the bytes came from.

## A live control tag printed in this README would be the exact delivery path the tool exists to close

The example in this file uses a placeholder marker rather than any harness's actual system or tool-call syntax. That's not caution about giving away implementation details, since the escape works identically no matter what follows the `<`, and real marker names are already sitting in every user's own transcripts. A README is exactly the kind of file an agent reads into its own context, so a live tag printed here would be the same delivery path this package exists to close, right there in the documentation. The test suite carries the real thing instead, because a test that can't reproduce the actual marker syntax isn't testing the claim it's making.

## Making the notes directory configurable created a failure mode the hardcoded version never had

The original had the directory baked in as a constant, so there was no unconfigured state to reach. The shipped version reads it from an explicit argument, then an environment variable, and if neither is set it does nothing: exit 0, no output, no banner, forever. That state is byte-identical to a working hook that correctly found nothing to flag. Failing closed would be wrong, since a hook that blocks reads on misconfiguration breaks the very agent it's defending. The gap is narrower than that: nothing here currently distinguishes an unconfigured hook from a quiet one, so the only real proof it's live is to read a file inside the notes directory after installing it and confirm the banner shows up.
