# -----------------------------------------------------------------------------
# Dockerfile for Telegram Bot
# -----------------------------------------------------------------------------

# ধাপ ১: বেস ইমেজ (Base Image)
FROM python:3.9-slim

# ধাপ ২: এনভায়রনমেন্ট ভ্যারিয়েবল (Environment Variables) - ঐচ্ছিক
ENV PYTHONUNBUFFERED 1

# ধাপ ৩: ওয়ার্কিং ডিরেক্টরি (Working Directory)
WORKDIR /app

# ধাপ ৪: ডিপেন্ডেন্সি ইনস্টলেশন (Dependency Installation)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ধাপ ৫: সোর্স কোড কপি (Copy Source Code)
COPY . .

# ধাপ ৬: কমান্ড (Command to Run)
CMD ["python", "bot.py"]