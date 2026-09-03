# Security Policy | 安全性政策

## Reporting a vulnerability | 回報安全問題

Please report security issues privately through
[GitHub Security Advisories](https://github.com/NTUST-OpenSource/gpa-analyzer/security/advisories/new).
Do not open a public issue.

請透過 [GitHub Security Advisories](https://github.com/NTUST-OpenSource/gpa-analyzer/security/advisories/new)
私下回報，請勿開立公開 issue。

We aim to acknowledge reports within 7 days.

## Scope | 範圍

This project handles NTUST student credentials. Reports about the following are
especially welcome:

- Authentication bypass, or any path where a wrong password is accepted
- Leakage of credentials, session cookies, or another student's data
- Cross-site scripting, CSRF, or content security policy bypass
- Weaknesses in the session cookie or the on-disk caches

## Out of scope | 不在範圍內

- The design decision to store the user's password encrypted in a session
  cookie. The grade portal offers no API and no long-lived token, so every
  request must re-authenticate. See the Security section of the README.
- Vulnerabilities in NTUST systems themselves. Report those to the university.
- The ability of an instance operator to read their own users' data. This is
  inherent to self-hosting; only use an instance you trust.

## Operator responsibilities | 架設者須知

If you run an instance:

- Keep `SECRET_KEY` secret. Leaking it is equivalent to leaking every user's
  password. Rotating it invalidates all sessions.
- Serve over HTTPS and leave `COOKIE_SECURE=true`.
- Set `FORWARDED_ALLOW_IPS` to your reverse proxy's address so per-client rate
  limiting works.
- Keep the image up to date; Dependabot opens update pull requests weekly.
