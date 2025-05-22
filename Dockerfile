# বেস ইমেজ হিসেবে পাইথনের একটি ভার্সন ব্যবহার করছি
FROM python:3.9-slim

# ওয়ার্কিং ডিরেক্টরি সেট করছি
WORKDIR /app

# প্রয়োজনীয় ফাইলগুলো কপি করছি
COPY requirements.txt requirements.txt
COPY bot.py bot.py

# pip ব্যবহার করে requirements.txt এ থাকা লাইব্রেরিগুলো ইনস্টল করছি
RUN pip install --no-cache-dir -r requirements.txt

# কন্টেইনার চালু হলে কোন কমান্ডটি রান হবে
CMD ["python", "bot.py"]
