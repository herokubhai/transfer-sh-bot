# Use an official Python runtime as a parent image
FROM python:3.9-slim

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container at /app
COPY . /app

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Make port 80 available to the world outside this container (if your bot needs a webhook, otherwise not strictly necessary for polling)
# Seenode might manage ports differently, but it's good practice if webhooks were used.
# For polling, it's not directly used by the bot for incoming connections from outside.
# EXPOSE 80

# Define environment variable for the bot token (you will set this in Seenode.com)
ENV BOT_TOKEN=""

# Run main.py when the container launches
CMD ["python", "main.py"]
