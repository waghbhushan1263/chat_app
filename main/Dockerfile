# Use official Python base image
FROM python:3.10

# Set working directory
WORKDIR /app

# Copy requirements and install
COPY requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire app
COPY . .

# Expose port your app runs on
EXPOSE 8150

# Command to run your app
CMD ["python", "main.py"]

