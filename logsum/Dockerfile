FROM python:3.12-slim

# tiktoken downloads its BPE table on first use; bake it into the image so the container works offline.
ENV TIKTOKEN_CACHE_DIR=/app/.tiktoken \
    LOGSUM_STATS=/data/stats.jsonl \
    LOGSUM_INSPECT_LOGS=/inspect/opencode.log:/inspect/claude-code.log \
    LOGSUM_OPENCODE_DB=/opencode-data/opencode.db \
    PYTHONUNBUFFERED=1

WORKDIR /app
RUN pip install --no-cache-dir "drain3>=0.9.11" "tiktoken>=0.7" \
 && python -c "import tiktoken; tiktoken.get_encoding('cl100k_base')" \
 && useradd -u 1000 -m logsum && mkdir -p /data /inspect && chown -R logsum:logsum /data /app

COPY logsum.py logsum_stats.py server.py ./
USER logsum
VOLUME ["/data"]
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=3s --start-period=5s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/health', timeout=2).status==200 else 1)"
CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8765"]
