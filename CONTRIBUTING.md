# Contributing to Samuraizer

Thanks for taking the time to contribute! 🎉

## Getting Started

1. **Fork** the repository and clone your fork.
2. **Set up the environment** (see [README.md](README.md#️-setup-local) for the full setup guide).
3. Create a **feature branch** from `master`:
   ```bash
   git checkout -b feat/my-feature
   ```

## Development Setup

```bash
# Backend
cp .env.example .env   # fill in your GEMINI_API_KEY at minimum
pip install -r requirements.txt
python server.py

# Frontend (separate terminal)
cd frontend
npm install
npm run dev
```

## Making Changes

- Keep changes focused — one feature or fix per PR.
- Follow existing code style (the codebase uses plain Python + React functional components).
- If you add a new API endpoint, document it in `README.md` under the **API Endpoints** section.
- Tag sanitization rules must be preserved: lowercase, hyphens for spaces, alphanumerics only.

## Submitting a Pull Request

1. Ensure the backend starts without errors (`python server.py`).
2. Ensure the frontend builds without errors (`cd frontend && npm run build`).
3. Push your branch and open a Pull Request against `master`.
4. Fill in the PR template — describe what changed and why.

## Reporting Bugs

Use the [Bug Report](.github/ISSUE_TEMPLATE/bug_report.md) issue template.  
Include steps to reproduce, expected behaviour, and actual behaviour.

## Proposing Features

Use the [Feature Request](.github/ISSUE_TEMPLATE/feature_request.md) issue template.

## Code of Conduct

Be respectful. This project follows basic open-source community standards.

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
