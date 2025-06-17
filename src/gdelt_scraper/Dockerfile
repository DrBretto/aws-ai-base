FROM public.ecr.aws/lambda/python:3.12

# Copy function code
COPY backfill_orchestrator.py ./
COPY requirements.txt ./

# Install dependencies
RUN pip install -r requirements.txt --target .

# Set the CMD to your handler
CMD ["backfill_orchestrator.lambda_handler"]