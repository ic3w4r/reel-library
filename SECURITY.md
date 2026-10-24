# Security policy

Reel Library stores API keys and an Instagram login cookie, and its web app has no login of its own
(it binds to `127.0.0.1` by default for that reason). Please treat security issues seriously.

## Reporting a vulnerability

**Don't open a public issue.** Use GitHub's private reporting instead:
**Security tab → Report a vulnerability** on this repository.

Include what's affected, how to reproduce it, and the impact you expect. You'll get a reply within a
week. Once a fix is released, you're welcome to be credited in the release notes.

## Supported versions

Only the latest release on the `main` branch gets security fixes.

## Running it safely

- Keep the port bound to `127.0.0.1` (the default). Don't expose it to the internet or an untrusted
  network: anyone who can reach it can read your library and use your API keys.
- Library backups (`instamcp-library.tgz`) contain your API keys and Instagram login. Keep them private.
