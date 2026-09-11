FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml ./
COPY contracts ./contracts
COPY sim ./sim
COPY generator ./generator
COPY engine ./engine
COPY scoring ./scoring
COPY api ./api
COPY docs ./docs
COPY seeds ./seeds
COPY cli.py ./
COPY docker-entrypoint.sh ./

RUN pip install --no-cache-dir -e ".[engine,report,api]" \
    && chmod +x docker-entrypoint.sh

ENV PYTHONUNBUFFERED=1
EXPOSE 8000

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["full"]
