# Stage: base image
FROM python:3.11-slim AS base

ENV TZ=Europe/London
RUN ln -snf "/usr/share/zoneinfo/$TZ" /etc/localtime && echo "$TZ" > /etc/timezone

RUN groupadd --gid 2000 --system appgroup && \
    useradd --uid 2000 --system appuser --gid 2000

WORKDIR /app

RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get autoremove -y && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir --upgrade pip setuptools wheel

# Stage: development image
FROM base AS dev

ENV PYTHONENVIRONMENT=development

RUN pip install --no-cache-dir watchdog[watchmedo]

COPY ./bin/docker-entrypoint.dev.sh /app/bin/entrypoint.sh
RUN chmod +x /app/bin/entrypoint.sh

ENTRYPOINT [ "/app/bin/entrypoint.sh" ]

# Stage: build assets / dependencies
FROM base AS build

# Install light compilation dependencies required by heavy ML packages (NumPy, Scipy, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir --user -r requirements.txt

# Stage: copy production assets and dependencies
FROM base

# Copy only the compiled Python packages from the build stage user space
COPY --from=build --chown=appuser:appgroup /root/.local /home/appuser/.local
COPY --from=build --chown=appuser:appgroup /app /app

# Copy python app source files
COPY --chown=appuser:appgroup . .

# Ensure python binary path discovering and instant log streaming to K8s terminal
ENV PATH=/home/appuser/.local/bin:$PATH
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

USER 2000

ENTRYPOINT []

# Runs Uvicorn for production serving. Switch to Gunicorn if needed.
CMD [ "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080" ]
