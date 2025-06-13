FROM public.ecr.aws/lambda/python:3.12

# Copy function code
COPY backfill_orchestrator.py ./

# Set the CMD to your handler
CMD ["backfill_orchestrator.lambda_handler"]