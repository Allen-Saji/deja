FROM public.ecr.aws/lambda/python:3.12

COPY requirements.lock.txt ${LAMBDA_TASK_ROOT}/

RUN pip install --no-cache-dir -r ${LAMBDA_TASK_ROOT}/requirements.lock.txt

COPY src ${LAMBDA_TASK_ROOT}/src
COPY certs ${LAMBDA_TASK_ROOT}/certs

ENV PYTHONPATH="${LAMBDA_TASK_ROOT}/src" \
    HF_HOME="/tmp/huggingface"

CMD ["deja.app.handler"]
