# Docker image for NovaActExecutor Lambda with Chromium for browser automation.
#
# Build:  docker build -t scg-nova-act-executor lambdas/execution/
# Push to ECR and use as Lambda container image in execution_stack.py.
#
# To switch to this mode, set EXECUTION_MODE=nova_act in CDK environment vars
# and deploy using _lambda.DockerImageFunction instead of _lambda.Function.

FROM public.ecr.aws/lambda/python:3.12

# Install Chromium + dependencies for Nova Act / Playwright
RUN dnf install -y \
    chromium \
    nss \
    atk \
    cups-libs \
    libdrm \
    libXcomposite \
    libXdamage \
    libXrandr \
    mesa-libgbm \
    pango \
    alsa-lib \
    && dnf clean all

# Install Python deps
COPY requirements.txt ${LAMBDA_TASK_ROOT}/
RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.txt

# Copy handler code
COPY nova_act_executor.py ${LAMBDA_TASK_ROOT}/
COPY approval_handler.py ${LAMBDA_TASK_ROOT}/

# Nova Act needs to know where Chromium is
ENV CHROMIUM_PATH=/usr/bin/chromium-browser
ENV EXECUTION_MODE=nova_act

CMD ["nova_act_executor.handler"]
