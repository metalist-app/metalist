# GitHub's Linux browser-suite runner, close enough to reproduce its failures here (run-suites.sh):
# Linux fonts, Python 3.12, Node 22, Firefox 160, and Debian's Chromium standing in for Google
# Chrome (no arm64 Linux build), with lsof, which the server uses to free its ports.
FROM python:3.12-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends \
      lsof procps chromium fonts-dejavu-core fonts-liberation fonts-noto-color-emoji fontconfig \
      xz-utils bzip2 rsync ca-certificates curl libgtk-3-0 libdbus-glib-1-2 libasound2 libx11-xcb1 \
    && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL https://nodejs.org/dist/v22.23.4/node-v22.23.4-linux-arm64.tar.xz | tar -xJ -C /opt \
    && ln -s /opt/node-v22.23.4-linux-arm64/bin/* /usr/local/bin/
RUN curl -fsSL -o /tmp/ff.tar.xz https://ftp.mozilla.org/pub/firefox/releases/160.0/linux-aarch64/en-US/firefox-160.0.tar.xz \
    && tar -xJf /tmp/ff.tar.xz -C /opt && ln -s /opt/firefox/firefox /usr/local/bin/firefox && rm /tmp/ff.tar.xz
# The suites look for google-chrome on Linux (installed-browser.mjs): Debian's Chromium stands in.
RUN ln -s /usr/bin/chromium /usr/local/bin/google-chrome
RUN useradd -m runner
USER runner
WORKDIR /home/runner/work
