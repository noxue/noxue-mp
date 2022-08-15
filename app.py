import hashlib
import os
import time
from fastapi import FastAPI, Request, Response, Query, HTTPException, Depends
from fastapi.responses import HTMLResponse, FileResponse
from config import WINXIN_TOKEN, MP_APPID, MP_APPSECRET
from lxml import etree
import requests
import redis
import qrcode
from PIL import Image
import cv2
from log import log

# 连接redis
redis_client = redis.Redis(host='localhost', port=6379, db=0)


def check_sign(signature: str = Query(), timestamp: str = Query(), nonce: str = Query()):
    tmp = "".join(sorted([WINXIN_TOKEN, timestamp, nonce]))
    sign = hashlib.sha1(tmp.encode('UTF-8')).hexdigest()
    if sign != signature:
        raise HTTPException(status_code=400, detail="签名不对")


def get_access_token():

    # 如果redis中有access_token，直接返回
    if redis_client.exists('access_token'):
        log.debug(redis_client.get('access_token'))
        return str(redis_client.get('access_token'), encoding='utf-8')

    # 参考：https://mp.weixin.qq.com/wiki?t=resource/res_main&id=mp1421141115
    url = "https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={}&secret={}".format(
        MP_APPID, MP_APPSECRET)
    res = requests.get(url)
    # 判断是否请求成功
    if res.status_code != 200:
        raise HTTPException(status_code=400, detail="请求失败")
    redis_client.set('access_token', res.json()['access_token'])
    redis_client.expire('access_token', res.json()['expires_in']-60)
    return res.json()['access_token']


app = FastAPI()


@app.get("/mp", dependencies=[Depends(check_sign)])
async def verify(echostr: str = Query()):
    return HTMLResponse(content=echostr)


def upload_media(path: str) -> str:
    access_token = get_access_token()

    url = "https://api.weixin.qq.com/cgi-bin/media/upload?access_token={}&type=image".format(
        access_token)
    files = {'media': open(path, 'rb')}
    res = requests.post(url, files=files)
    log.debug(res.json())
    return res.json()['media_id']


def list_media():
    """获取素材列表"""
    access_token = get_access_token()
    url = "https://api.weixin.qq.com/cgi-bin/material/batchget_material?access_token={}".format(
        access_token)
    data = {
        "type": "image",
        "offset": 0,
        "count": 20
    }
    res = requests.post(url, json=data)
    return res.json()


def get_qrcode_info(code_img_path: str):
    """解析图片中的二维码内容

    Args:
        code_img_path (str): 带二维码的图片路径

    Raises:
        FileExistsError: 图片不存在就抛出异常

    Returns:
        (str, (float,float,float,float)): 返回数据类型(二维码内容,二维码坐标)
    """
    if not os.path.exists(code_img_path):
        raise FileExistsError(code_img_path)
    qrcode_image = cv2.imread(code_img_path)
    qrCodeDetector = cv2.QRCodeDetector()
    data, bbox, straight_qrcode = qrCodeDetector.detectAndDecode(qrcode_image)

    return (data, bbox, straight_qrcode)


def gen_qrcode(qrcode_info: str, qrcode_img_path: str):
    """生成二维码
    Args:
        qrcode_info(str): 二维码携带的数据
        qrcode_img_path(str): 二维码图片保存路径

    Returns:
        str: 二维码保存的路径
    """
    qr = qrcode.QRCode(
        version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=1, border=0)
    qr.add_data(qrcode_info)
    qr.make(fit=True)
    img = qr.make_image()
    img.save(qrcode_img_path)
    return qrcode_img_path


def replace_qrcode(old_qrcode_path: str, new_qrcode_path: str, points, out_qrcode_path: str):
    """new_qrcode_path 指定的二维码图片 替换 old_qrcode_path 指定的图片中的二维码

    Args:
        old_qrcode_path (str): 带二维码的图片路径
        new_qrcode_path (str): 只有二维码的图片路径
        points ((int,int,int,int)): old_qrcode_path 图片中二维码的坐标(左上角x,左上角y,右下角x,右下角y)
        out_qrcode_path (str): 替换后的图片像保存的路径

    Returns:
        str: 替换后的图片像保存的路径
    """
    old_qrcode = Image.open(old_qrcode_path)
    new_qrcode = Image.open(new_qrcode_path)
    new_qrcode = new_qrcode.resize((points[2]-points[0], points[3]-points[1]))
    old_qrcode.paste(new_qrcode, points)
    old_qrcode.save(out_qrcode_path)
    return out_qrcode_path


@app.post("/mp", dependencies=[Depends(check_sign)])
async def do(request: Request, response: Response):
    data = await request.body()
    log.debug(data)
    # 解析xml
    xml = etree.fromstring(data)

    from_user = xml.find("FromUserName").text
    to_user = xml.find("ToUserName").text
    log.debug(from_user)

    msg_type = xml.find('MsgType').text
    media_id = ""
    if msg_type == 'image':
        # 获取图片地址
        pic_url = xml.find('PicUrl').text
        log.debug(pic_url)
        # 下载图片到本地
        res = requests.get(pic_url)
        # md5加密 from_user
        md5_from_user = hashlib.md5(from_user.encode('utf-8')).hexdigest()
        qrcode_path = "{}/{}.jpg".format("./qrcode", md5_from_user)
        with open(qrcode_path, 'wb') as f:
            f.write(res.content)

        data, points, _ = get_qrcode_info(qrcode_path)
        log.debug(data)
        log.debug(points)
        if points is None:
            return HTMLResponse(content="")

        log.debug(points)
        # 左上角点坐标
        points = (int(points[0][0][0]-2), int(points[0][0][1]-2),
                  int(points[0][2][0]+2), int(points[0][2][1]+2))
        log.debug(points)
        new_qrcode_path = "{}/{}-new.jpg".format("./qrcode", md5_from_user)
        qrcode_info = "http://mp.noxue.com/group-qrcode/{}?t={}".format(
            md5_from_user, int(time.time()))

        new_qrcode_path = gen_qrcode(qrcode_info, new_qrcode_path)

        out_qrcode_path = "./qrcode/{}-out.jpg".format(md5_from_user)
        replace_qrcode(qrcode_path, new_qrcode_path, points, out_qrcode_path)

        # 上传图片到微信服务器
        media_id = upload_media(out_qrcode_path)

        # 返回图片
        reply = """<xml>
            <ToUserName><![CDATA[{}]]></ToUserName>
            <FromUserName><![CDATA[{}]]></FromUserName>
            <CreateTime><![CDATA[{}]]></CreateTime>
            <MsgType><![CDATA[image]]></MsgType>
            <Image>
                <MediaId><![CDATA[{}]]></MediaId>
            </Image>
        </xml>""".format(from_user, to_user, int(time.time()), media_id)
        log.debug(reply)

        return HTMLResponse(content=reply)
    elif msg_type == 'text':
        content = xml.find('Content').text
        data = ""
        if content in ['codeblocks', '开发工具']:
            data = "浏览器打开：\r\n    http://files.noxue.com \r\n [开发工具>codeblocks目录下]\r\n祝你学业有成😊"
        elif content.startswith('noxue-'):
            data = "压缩密码已经搞忘记了，非常抱歉😢\r\n\r\n需要什么资源可以加我微信，免费给你推荐😊\r\n\r\n微信号：noxuecom"

        if data:
            reply = """<xml>
    <ToUserName><![CDATA[{}]]></ToUserName>
    <FromUserName><![CDATA[{}]]></FromUserName>
    <CreateTime>{}</CreateTime>
    <MsgType><![CDATA[text]]></MsgType>
    <Content><![CDATA[{}]]></Content>
</xml>""".format(from_user, to_user, int(time.time()), data)

            return HTMLResponse(content=reply)

    # res = list_media()
    # log.debug(res)
    # 不回复

    return HTMLResponse(content="success")


@app.get("/group-qrcode/{id}")
async def group_qrcode(id: str):
    qrcode_path = "{}/{}.jpg".format("./qrcode", id)
    log.debug(qrcode_path)
    if not os.path.exists(qrcode_path):
        return HTMLResponse(status_code=404)
    # 返回图片jpg  不缓存
    return FileResponse(qrcode_path, media_type="image/jpeg",
                        headers={
                            "Pragma": "no-cache", "Expires": "0",
                            "Last-Modified": "Thu, 01 Jan 1970 00:00:00 GMT",
                            "Cache-Control": "no-store, no-cache, must-revalidate, post-check=0, pre-check=0"
                        })
