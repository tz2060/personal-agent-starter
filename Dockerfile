FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home --uid 10001 agent
COPY app ./app
COPY vault/rules ./vault/rules
COPY .env.example README.md ./
RUN mkdir -p data vault/knowledge vault/rules vault/attachments vault/_inbox vault/topics && chown -R agent:agent /app
USER agent
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
