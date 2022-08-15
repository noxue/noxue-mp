### 识别二维码 cv2
```
pip install opencv-python
apt update
apt install libgl1-mesa-glx
```

# 安装库 

```
pip3 install python-dotenv
```

### 运行
```
mkdir qrcode
nohup uvicorn app:app --env-file=.env --host=127.0.0.1 --port=8001 --workers=4 &
```
