FROM python:3.11-slim-buster

RUN export LC_ALL=C.UTF-8 && export LANG=C.UTF-8

ENV TZ=UTC
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

RUN groupadd -g 1001 appgroup && useradd -m -u 1001 appuser
ENV PATH="${PATH}:/home/appuser/.local/bin"

RUN python3 -m pip install --no-cache-dir -U setuptools pip && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

USER appuser:appgroup

WORKDIR .

COPY . .

RUN python3 -m pip install --no-cache-dir -r requirements.txt

CMD ["python", "-u", "bot.py"]