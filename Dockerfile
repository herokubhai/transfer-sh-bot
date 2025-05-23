# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Environment variables to be set on Seenode or in .env file
ENV BOT_TOKEN=""
ENV API_ID=""
ENV API_HASH=""
ENV SESSION_STRING=""
ENV OWNER_ID="" # Optional: Your Telegram User ID for error notifications
ENV PYTHONUNBUFFERED=1

# Run main.py when the container launches
CMD ["python", "main.py"]
