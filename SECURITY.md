# Security Policy

## Reporting a Vulnerability

Please do not report security vulnerabilities in public issues. Use GitHub's
private vulnerability reporting feature for this repository instead.

Include a clear description, affected versions or commits, reproduction steps,
and the potential impact. Avoid including real customer data or live secrets.

## Secret Handling

- Never commit `.env`, `server.env`, API keys, tokens, QR login links, or runtime credentials.
- Use `.env.example` as the template for local configuration.
- Rotate any credential immediately if it is accidentally committed or shared.
- Review production domains, webhook URLs, and deployment details before making a fork public.
