RadioCharts 0.1.6

Fixes GitHub Docker build failure introduced in 0.1.5.

Dockerfile now uses the official Playwright Python v1.54.0 Noble image,
which already contains Chromium and browser system dependencies. It no longer
runs `python -m playwright install --with-deps chromium` during image build.
The Playwright Python package remains pinned to 1.54.0 in requirements.txt so
its version matches the browser image.
