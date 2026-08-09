FROM python:3.12-slim
WORKDIR /app

# WeasyPrint runtime dependencies (Pango, Cairo, GdkPixbuf + fonts)
RUN apt-get update && apt-get install -y --no-install-recommends \
      libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b \
      libcairo2 libgdk-pixbuf-2.0-0 shared-mime-info \
      fontconfig fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

RUN pip install uv

COPY pyproject.toml .
RUN uv sync --no-dev

COPY src/ src/
COPY data/fatty_liver_diabetes_guidelines.yaml data/fatty_liver_diabetes_guidelines.yaml
COPY data/ingredient_categories.json data/ingredient_categories.json
COPY cli.py .

# The USDA FoodData Central CSV bundle (multi-GB) is NOT baked into the image —
# place it under ./usda_source_data/ on the host (it's mounted read-only by
# docker-compose) and run `build-nutrition-db` once; the built data/usda.db
# then persists via the ./data volume.

ENTRYPOINT ["uv", "run", "python", "cli.py"]
