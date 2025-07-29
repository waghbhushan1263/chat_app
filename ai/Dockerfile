FROM python:3.10-slim  
# base image
WORKDIR /app
#working dire
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# whole proje copi
EXPOSE 5001

CMD ["python", "ai_service.py"]
#cmd
