# Security Policy

## Supported Versions

This project is currently in active development. Security fixes are applied to the latest version on `master`.

| Version | Supported |
| ------- | --------- |
| latest (master) | ✅ |

## Reporting a Vulnerability

**Please do not report security vulnerabilities through public GitHub issues.**

To report a security vulnerability, open a [GitHub Security Advisory](https://github.com/zomry1/Samuraizer/security/advisories/new) (private disclosure).

Include:
- A description of the vulnerability
- Steps to reproduce it
- Potential impact
- (Optional) a suggested fix

You can expect an acknowledgement within 48 hours. I'll aim to release a patch within 7 days of a confirmed vulnerability.

## Security Notes for Self-Hosted Deployments

- **Never expose the Flask dev server (`python server.py`) to the public internet.** Use a production WSGI server (e.g. `gunicorn`) behind a reverse proxy (e.g. nginx) with TLS.
- Keep your `.env` file out of version control — it is gitignored by default.
- The SQLite database (`samuraizer.db`) contains your knowledge base. Back it up and restrict file-system access appropriately.
- The `/analyze` endpoint fetches arbitrary URLs. Run the backend in a sandboxed or firewalled environment if exposing it to untrusted users.
