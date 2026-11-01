# Personal data and publication rules

This repository may be **public**. Before every push, keep host-specific runtime data and personal media out of commits. No subtitle sources, sidecars, model output, translation memories, queue DBs, movie filenames, host logs, server addresses, credentials, media mounts, or approved personal edits belong in a commit.

The `.gitignore` excludes common generated artifacts, but it cannot prevent deliberate `git add -f`. Inspect `git status` and `git diff --cached --name-only` before each push.

The dashboard is a read-only development UI, not a production authenticated web service. Keep port 8686 restricted to the host/authorized tunnel until access controls are implemented. Avoid publishing the server's Tailscale endpoint.

The existing publisher is allowed to create Japanese sidecars only for verified English-audio media. Checkpoints and legacy media state belong outside this repository; updates should be staged and reversible, not installed during active inference.
