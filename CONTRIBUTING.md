# Contributing

Thanks for helping improve Sales Agent.

## Development

1. Fork the repository and create a topic branch.
2. Copy `.env.example` to `.env` and provide your own local credentials.
3. Keep changes focused and include tests when behavior changes.
4. Run the relevant checks before opening a pull request.

```bash
python scripts/quality_gate.py
```

## Security

Never commit real API keys, customer data, QR login links, production domains,
or private deployment details. See `SECURITY.md` for reporting instructions.

## License

By contributing, you agree that your contributions are licensed under the
Apache License 2.0.
