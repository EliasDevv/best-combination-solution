FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Mirror the repository layout: settings.REPO_ROOT is BASE_DIR.parent, so the
# CSVs must live at /app/data for `import_dataset` to find them by default.
WORKDIR /app/backend

# Dependency layer first, so editing source code does not reinstall anything.
# gunicorn is installed here rather than in pyproject.toml: it is a deployment
# concern of this image, not a dependency of the project or its test suite.
COPY pyproject.toml ./
RUN pip install --no-cache-dir -e . gunicorn

COPY . .

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
